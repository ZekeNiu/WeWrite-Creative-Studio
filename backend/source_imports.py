"""Cancellable source acquisition; importing never invokes a language model."""
import asyncio
import copy
import hashlib
import io
import re
from pathlib import Path
from . import academic,materials,store,source_reader,flow_state


def normalized(text):
    return re.sub(r'[^\w]','',text or '').casefold()


async def identify_file(src,blob=None):
    if src.get('identity_verified'): return src
    front=(src.get('pages') or [{}])[0].get('text') or src.get('text','')[:6000]
    front=re.split(r'\n\s*(?:References|参考文献)\s*\n',front,flags=re.I)[0]
    title=''
    if blob and src.get('original_filename','').lower().endswith('.pdf'):
        from pypdf import PdfReader
        title=str((PdfReader(io.BytesIO(blob)).metadata or {}).get('/Title',''))
        if title.lower() in ('untitled','title') or len(title)<20: title=''
    compact=re.sub(r'(10\.\d{4,9}/)\s+',r'\1',front)
    doi_candidates=list(dict.fromkeys(academic.normalized_doi(x) for x in re.findall(r'10\.\d{4,9}/[^\s<>]+',compact[:1800])))
    source_reader.progress('正在识别文件文献信息')
    scholarly=bool(src.get('pages')) and bool(re.search(r'\babstract\b|摘要',front,re.I))
    if not doi_candidates and not scholarly:
        src['identity_status']='pending';return src
    try:
        async with asyncio.timeout(25):
            candidates=[]
            if doi_candidates: candidates=[await academic.lookup_doi(doi_candidates[0])]
            elif title: candidates=await academic.crossref(title)
            elif len(front)>100: candidates=await academic.crossref(' '.join(front.split())[:500])
            for row in candidates:
                b=row.get('bibliography',{});paper_title=normalized(b.get('title'))
                matches=len(paper_title)>15 and (paper_title in normalized(front) or paper_title==normalized(title))
                author=(b.get('authors') or [{}])[0]
                author=author.get('family','') if isinstance(author,dict) else str(author)
                confirmed_doi=academic.normalized_doi(row.get('doi','')) in doi_candidates
                if matches and (confirmed_doi or (author and normalized(author) in normalized(front) and b.get('year','') in front)):
                    src.update(title=b['title'],doi=row.get('doi',''),bibliography=b,identity_verified=True,identity_status='identified',
                        metadata_provenance=src.get('metadata_provenance',[])+row.get('metadata_provenance',[]))
                    return src
    except (ValueError,TimeoutError): pass
    src['identity_status']='pending'
    return src


def remap(a,old_id,new_id):
    for claim in a.get('evidence',{}).get('claims',[]):
        claim['source_ids']=list(dict.fromkeys(new_id if s==old_id else s for s in claim.get('source_ids',[])))
        for e in claim.get('evidence',[]):
            if e.get('source_id')==old_id:e['source_id']=new_id
    for issue in a.get('research',{}).get('issues',[]):
        issue['source_ids']=list(dict.fromkeys(new_id if s==old_id else s for s in issue.get('source_ids',[])))
    for e in a.get('research',{}).get('evidence',[]):
        if e.get('source_id')==old_id:e['source_id']=new_id
    # Preserve historical citations while their canonical record keeps the original id.
    a['content']=a['content'].replace('['+old_id+']','['+new_id+']')


def append(a,src,issue_ids=()):
    if not isinstance(issue_ids,(list,tuple)) or len(issue_ids)>40 or not all(isinstance(x,str) for x in issue_ids): raise ValueError('建议关联格式无效')
    aliases=a.get('research',{}).get('issue_aliases',{})
    ids=list(dict.fromkeys(aliases.get(x,x) for x in issue_ids))
    if set(ids)-{x['id'] for x in flow_state.issues(a)}: raise ValueError('关联建议已改变，请重新选择')
    src['issue_ids']=list(dict.fromkeys(src.get('issue_ids',[])+ids))
    old=next((s for s in a['sources'] if s['id']==src['id'] or academic.same(s,src) or
        (src.get('content_hash') and src['content_hash']==s.get('content_hash'))),None)
    if not old:a['sources'].append(src);return src['id'],'added'
    merged=academic.combine(old,src)
    for key in ('attachments','issue_ids'):
        merged[key]=list(old.get(key,[]))
        for item in src.get(key,[]):
            if item not in merged[key]:merged[key].append(item)
    if src.get('identity_verified'):
        merged.update(title=src['title'],bibliography=src['bibliography'],identity_verified=True,identity_status='identified')
    old.update(merged)
    return old['id'],'updated'


def consolidate(a):
    kept=[];aliases={}
    for source in a['sources']:
        old=next((x for x in kept if academic.same(x,source)),None)
        if old:
            append(dict(a,sources=kept),source,source.get('issue_ids',[]));remap(a,source['id'],old['id']);aliases[source['id']]=old['id']
        else:kept.append(source)
    a['sources']=kept
    return aliases


async def enrich_existing(a):
    """Called only during an explicit verification, never while browsing old articles."""
    for source in a['sources']:
        if source.get('selected') and source.get('filename') and not source.get('identity_verified'):
            source.setdefault('original_filename',source['title'])
            await identify_file(source)


async def acquire(kind,value,blob=None):
    if kind=='url':return [await materials.from_url(value['url'])]
    name=value['filename']
    if Path(name).suffix.lower() in ('.bib','.ris'):
        from .bibliography import import_records
        return import_records(name,blob)
    source_reader.progress('正在提取文件正文')
    text,pages=await asyncio.to_thread(materials.extract_file,name,blob)
    src=materials.source(name,text,pages=pages)
    src.update(original_filename=name,content_hash=hashlib.sha256(blob).hexdigest())
    await identify_file(src,blob)
    return [src]


def start(id,kind,value,blob=None):
    from . import workflow
    a=store.get_article(id)
    if a['revision']!=value['revision']:raise store.Conflict('文章已更新，请完成保存后重试')
    key=hashlib.sha256(store.encode([kind,value.get('url'),hashlib.sha256(blob).hexdigest() if blob else '',value.get('issue_ids',[]),value.get('source_id'),value['revision']]).encode()).hexdigest()
    for job in store.jobs(id):
        if job['request'].get('import_key')==key and job['status'] in ('queued','running','completed'):return job
    request=dict(stage='source_import',revision=a['revision'],kind=kind,import_key=key,issue_ids=value.get('issue_ids',[]),source_id=value.get('source_id',''))
    job=store.create_job(id,request)
    workflow.TASKS[job['id']]=asyncio.create_task(run(job['id'],copy.deepcopy(a),kind,value,blob))
    return job


async def run(jid,snapshot,kind,value,blob=None):
    from . import workflow,evidence_state
    written=None;committed=False
    token=source_reader.READ_PROGRESS.set(lambda msg:store.update_job(jid,message=msg,phase='reading' if '读取' in msg else 'identifying'))
    try:
        store.update_job(jid,status='running',message='正在识别文献',phase='identifying')
        async with asyncio.timeout(90):
            if kind=='identify':
                src=next((s for s in snapshot['sources'] if s['id']==value['source_id']),None)
                if not src:raise ValueError('素材不存在')
                rows=[await identify_file(src)]
            else:rows=await acquire(kind,value,blob)
        if store.job(jid)['status']=='cancelled':return
        with store.LOCK:
            current=store.get_article(snapshot['id'])
            if evidence_state.objective(current)!=evidence_state.objective(snapshot):raise store.Conflict('文章方向已变化，未添加本次材料；请确认后重试')
            if kind=='identify':
                old=next((s for s in current['sources'] if s['id']==value['source_id']),None)
                before=next(s for s in snapshot['sources'] if s['id']==value['source_id'])
                if not old or old.get('text')!=before.get('text'):raise store.Conflict('原素材已改变，未覆盖当前内容')
            if blob and rows and Path(value['filename']).suffix.lower() not in ('.bib','.ris'):
                existing=next((s for s in current['sources'] if s.get('content_hash')==rows[0].get('content_hash')),None)
                if existing and existing.get('attachments'):rows[0]['attachments']=existing['attachments']
                else:
                    filename=store.uid()+Path(value['filename']).suffix.lower()
                    folder=store.article_dir(snapshot['id'])/'materials';folder.mkdir(exist_ok=True)
                    written=folder/filename;written.write_bytes(blob)
                    rows[0].update(filename=filename,attachments=[dict(filename=filename,name=value['filename'],hash=rows[0]['content_hash'])])
            store.update_job(jid,message='正在保存素材',phase='saving')
            result=[]
            def change(a):
                for source in rows:
                    sid,operation=append(a,source,value.get('issue_ids',[]))
                    result.append(dict(source_id=sid,title=source['title'],operation=operation,scope=source.get('access_scope','file'),identity_status=source.get('identity_status','identified' if source.get('doi') else 'pending')))
                aliases=consolidate(a)
                for item in result:item['source_id']=aliases.get(item['source_id'],item['source_id'])
            saved=store.save_article(current['id'],current['revision'],change,'导入并识别素材',invalidate='sources');committed=True
            store.update_job(jid,status='completed',phase='completed',ended=store.now(),message='资料已加入，等待核实',result=dict(sources=result,issue_ids=value.get('issue_ids',[]),revision=saved['revision']))
    except asyncio.CancelledError:store.update_job(jid,status='cancelled',ended=store.now(),message='已取消导入，未添加材料')
    except Exception as exc:
        store.update_job(jid,status='conflict' if isinstance(exc,store.Conflict) else 'failed',ended=store.now(),message='读取超过 90 秒，已停止；可重试或上传原文' if isinstance(exc,TimeoutError) else str(exc))
    finally:
        source_reader.READ_PROGRESS.reset(token)
        if written and not committed:written.unlink(missing_ok=True)
        workflow.TASKS.pop(jid,None)
