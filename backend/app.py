import asyncio
import io
import json
import os
import re
import secrets
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit,quote
from fastapi import FastAPI,Request,UploadFile,File,Form,HTTPException
from fastapi.responses import JSONResponse,FileResponse,Response,StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image
from pydantic import ValidationError
from . import store,providers,security,materials,rendering,workflow,prompts,search_tools,browser_search,search_check,bibliography,outputs,capabilities
from . import flow_state,issue_actions,source_imports
from .models import IssueAction,Settings,Brief,Layout,VisualSettings,ArticlePatch,JobRequest,STAGES,OutlineResult,ImagePlan,CapabilityTest

APP_VERSION=json.loads((store.ROOT/'package.json').read_text('utf-8'))['version']


@asynccontextmanager
async def lifespan(app):
    store.init()
    providers.migrate_settings()
    yield
    for t in list(workflow.TASKS.values()): t.cancel()
    if workflow.TASKS: await asyncio.gather(*list(workflow.TASKS.values()),return_exceptions=True)


app=FastAPI(title='WeWrite 本地工作台',lifespan=lifespan,docs_url=None,redoc_url=None)


@app.middleware('http')
async def local_only(request: Request,call_next):
    host=request.headers.get('host','').split(':')[0]
    allowed={'127.0.0.1','localhost','testserver'}
    if host not in allowed: return JSONResponse({'detail':'仅允许本机访问'},403)
    origin=request.headers.get('origin')
    if origin and urlsplit(origin).netloc != request.headers.get('host'):
        if not (os.environ.get('STUDIO_DEV')=='1' and origin=='http://127.0.0.1:5173'):
            return JSONResponse({'detail':'访问来源不匹配'},403)
    if request.method not in ('GET','HEAD','OPTIONS') and request.headers.get('x-studio-request')!='1':
        return JSONResponse({'detail':'请从工作台界面执行此操作'},403)
    if request.method not in ('GET','HEAD','OPTIONS') and getattr(app.state,'restarting',False):
        return JSONResponse({'detail':'后台正在更新，请稍后重试；尚未保存的文字请保留在当前页面'},409)
    try: result=await call_next(request)
    except Exception: return JSONResponse({'detail':'服务遇到异常，已有内容已保存；请重试或重新启动工作台'},500)
    result.headers['X-Content-Type-Options']='nosniff'
    result.headers['Referrer-Policy']='no-referrer'
    if request.url.path.startswith('/api') or 'text/html' in result.headers.get('content-type',''):
        result.headers['Cache-Control']='no-store'
    return result


@app.exception_handler(ValueError)
async def value_error(request,exc): return JSONResponse({'detail':str(exc)},400)


@app.exception_handler(KeyError)
async def missing(request,exc): return JSONResponse({'detail':str(exc).strip("'")},404)


@app.exception_handler(store.Conflict)
async def conflict(request,exc): return JSONResponse({'detail':str(exc)},409)


@app.get('/api/health')
def health():
    try: available=json.loads((store.ROOT/'package.json').read_text('utf-8'))['version']
    except (OSError,ValueError,KeyError): available=APP_VERSION
    return {'app':'wewrite-studio','version':APP_VERSION,'available_version':available,'upstream':'4.2.1','workspace':str(store.ROOT)}


@app.get('/api/meta')
def meta():
    return {'personas':[dict(id=k,name=v[0],description=v[1],example=v[2]) for k,v in prompts.PERSONAS.items()],
            'themes':rendering.themes(),'stages':STAGES}


@app.get('/api/settings')
def settings(): return providers.settings()


@app.get('/api/themes/{id}/preview')
def theme_preview(id:str): return rendering.theme_preview(id)


@app.put('/api/settings')
def settings_save(value:Settings): return providers.save_settings(value)


def get_service(id,require_model=True):
    cfg=providers.settings(); s=next((x.copy() for x in cfg['services'] if x['id']==id),None)
    if not s: raise ValueError('请先保存服务设置')
    s['secret']=security.key(id)
    if not s['secret']: raise ValueError('请先填写并保存 API Key')
    if require_model and not s['model']: raise ValueError('请先填写并保存模型名称')
    return s


@app.post('/api/services/{id}/models')
async def model_list(id:str): return {'models':await providers.list_models(get_service(id,False))}


@app.post('/api/services/{id}/capability-tests')
async def test_capability(id:str,value:CapabilityTest):
    return await capabilities.test(id,value)


@app.post('/api/services/{id}/test')
async def test_service(id:str):
    s=get_service(id)
    return await capabilities.test(id,CapabilityTest(model=s['model'],kind='text'))


@app.post('/api/services/{id}/test-image')
async def test_image(id:str):
    s=providers.effective_service('image')
    if id!=s['id']: raise ValueError('请在节点分工中选择图片服务，再测试实际图片节点')
    return await capabilities.test(id,CapabilityTest(model=s['model'],kind='image'))


@app.get('/api/connection-tests/{filename}')
def connection_image(filename:str):
    if not re.fullmatch(r'[a-f0-9]{32}\.png',filename): raise HTTPException(404)
    p=outputs.diagnostics()/filename
    if not p.is_file(): p=store.DATA/'connection-tests'/filename
    if not p.is_file(): raise HTTPException(404)
    return FileResponse(p,media_type='image/png')


@app.post('/api/search/native/test')
async def test_native(value:dict|None=None):
    value=value or {};cfg=providers.settings();search=cfg['search']
    sid=value.get('service_id') or search['native_service_id'] or cfg['default_service']
    service=get_service(sid)
    return await capabilities.test(sid,CapabilityTest(model=value.get('model') or search['native_model'] or service['model'],
        kind='search',protocol=value.get('protocol') or search['native_protocol']))


@app.post('/api/search/test')
async def test_search():
    rows=await providers.search('运动科学 研究',90)
    return {'message':f'搜索连接成功，返回 {len(rows)} 条结果'}


@app.post('/api/search/check')
async def start_search_check(value:search_check.CheckRequest):
    return search_check.start(value)


@app.get('/api/search/check/latest')
def latest_search_check():
    return search_check.result(store.latest_search_check())


@app.get('/api/search/check/{id}')
def get_search_check(id:str):
    job=store.job(id)
    if job['request'].get('kind')!='search_check': raise HTTPException(404)
    return search_check.result(job)


@app.get('/api/articles')
def articles(state:str='active'):
    if state not in ('active','trash'):raise ValueError('文章列表分类无效')
    return store.list_articles(state)


@app.post('/api/articles/{id}/trash')
def trash_article(id:str,value:dict):return store.trash_article(id,value['revision'])


@app.post('/api/articles/{id}/untrash')
def untrash_article(id:str,value:dict):return store.trash_article(id,value['revision'],restore=True)


@app.delete('/api/articles/{id}')
def purge_article(id:str,value:dict):return store.purge_article(id,value['revision'])


@app.post('/api/articles/{id}/source-imports')
async def import_url(id:str,value:dict):
    if not isinstance(value.get('url'),str):raise ValueError('请输入公开网页链接')
    return source_imports.start(id,'url',value)


@app.post('/api/articles/{id}/source-imports/file')
async def import_file(id:str,file:UploadFile=File(),revision:int=Form(),issue_ids:str=Form('[]')):
    blob=await file.read(materials.MAX_BYTES+1)
    if len(blob)>materials.MAX_BYTES:raise ValueError('文件不能超过 20 MB')
    ids=json.loads(issue_ids)
    if not isinstance(ids,list) or len(ids)>40 or not all(isinstance(x,str) for x in ids):raise ValueError('建议关联格式无效')
    return source_imports.start(id,'file',dict(filename=Path(file.filename or '').name,revision=revision,issue_ids=ids),blob)


@app.post('/api/articles/{id}/sources/{sid}/identify')
async def identify_source(id:str,sid:str,value:dict):return source_imports.start(id,'identify',dict(value,source_id=sid))


@app.post('/api/articles')
def create(brief:Brief): return store.create_article(brief.model_dump(),providers.settings()['default_auto'])


@app.get('/api/articles/{id}')
def article(id:str): return store.get_article(id)


@app.patch('/api/articles/{id}')
def patch(id:str,payload:ArticlePatch):
    stage=payload.stage
    if stage not in ['setup',*STAGES,'preferences']: raise ValueError('未知编辑环节')
    allowed={'title','brief','auto','outline','content','layout','visual','image_plans','images','sources','current_stage'}
    if set(payload.changes)-allowed: raise ValueError('包含不可修改的字段')
    c=payload.changes.copy()
    if 'brief' in c: c['brief']=Brief.model_validate(c['brief']).model_dump()
    if 'layout' in c:
        c['layout']=Layout.model_validate(c['layout']).model_dump()
        if c['layout']['theme'] not in {t['id'] for t in rendering.themes()}: raise ValueError('排版主题不存在')
    if 'visual' in c: c['visual']=VisualSettings.model_validate(c['visual']).model_dump()
    if 'outline' in c and c['outline']: c['outline']=OutlineResult.model_validate(c['outline']).model_dump()
    if 'auto' in c: c['auto']={s:bool(c['auto'].get(s,False)) for s in STAGES}
    if 'image_plans' in c: c['image_plans']=[ImagePlan.model_validate(p).model_dump() for p in c['image_plans']]
    if 'sources' in c:
        for s in c['sources']:
            if 'bibliography' in s: s['bibliography']=bibliography.Metadata.model_validate(s['bibliography']).model_dump()
    for k in ('content','title'):
        if k in c and (not isinstance(c[k],str) or len(c[k])>500000): raise ValueError('文章内容格式或长度不正确')
    def mutate(a):
        for key,fields in [('sources',('selected','personal_material','use','title','bibliography')),('images',('selected','caption','role','after_heading'))]:
            if key in c:
                incoming={x['id']:x for x in c[key]}
                if set(incoming)-{x['id'] for x in a[key]}: raise ValueError('不能引用未知素材')
                if key=='sources':
                    a.setdefault('excluded_sources',[]).extend(x for x in a[key] if x['id'] not in incoming)
                c[key]=[{**x,**{f:incoming[x['id']][f] for f in fields if f in incoming.get(x['id'],{})}} for x in a[key] if x['id'] in incoming]
        a.update(c)
        if stage in STAGES: a['current_stage']=stage
        if stage=='setup' and a['brief']['topic']:
            a['title']=a['brief']['topic']; a['stages']['topic']='done'
        if stage in ('write','outline','layout'):
            a['stages'][stage]='done' if (a['content'] if stage=='write' else a.get(stage)) else 'idle'
    return store.save_article(id,payload.revision,mutate,'手动编辑',invalidate=None if stage=='preferences' else stage)


@app.post('/api/articles/{id}/research/issues/actions')
async def issue_action(id:str,value:IssueAction): return issue_actions.apply(id,value)


@app.get('/api/articles/{id}/research/history')
def research_history(id:str):
    store.get_article(id)
    with store.connection() as db:
        rows=db.execute('SELECT data FROM jobs WHERE article_id=? ORDER BY rowid DESC LIMIT 100',(id,)).fetchall()
    return [dict(id=j['id'],created=j['created'],stage=j.get('stage'),status=flow_state.job_view(j)['status'],research=j['research'])
            for row in rows if (j:=json.loads(row['data'])).get('research')]


@app.post('/api/articles/{id}/confirm/{stage}')
def confirm_stage(id:str,stage:str,value:dict):
    if stage!='outline': raise ValueError('此环节请通过选择或审核完成确认')
    def change(a):
        if stage=='outline':
            if not a['outline'].get('sections'): raise ValueError('请先生成或填写大纲')
            if a['stages']['sources']=='stale': raise ValueError('资料已改变，请先重新分析素材')
        a['stages'][stage]='done'
    return store.save_article(id,value['revision'],change,'人工确认'+stage,invalidate=stage)


@app.post('/api/articles/{id}/topic')
def select_topic(id:str,value:dict):
    title=str(value.get('title','')).strip()
    if not title: raise ValueError('请输入或选择题目')
    def change(a):
        from .creative import adopt
        adopt(a,title,value.get('topic_id',''))
    return store.save_article(id,value['revision'],change,'确认选题',invalidate='topic')


def append_source(a,src,issue_ids=()):
    return source_imports.append(a,src,issue_ids)


@app.post('/api/articles/{id}/sources/text')
def add_text(id:str,value:dict):
    text=str(value.get('text','')).strip()
    if not text or len(text)>1_000_000: raise ValueError('请输入有效素材正文（不超过 100 万字符）')
    src=materials.source(str(value.get('title') or '我的素材'),text)
    return store.save_article(id,value['revision'],lambda a:append_source(a,src,value.get('issue_ids',[])),'添加文字素材',invalidate='sources')


@app.post('/api/articles/{id}/sources/url')
async def add_url(id:str,value:dict):
    src=await materials.from_url(value['url'])
    return store.save_article(id,value['revision'],lambda a:append_source(a,src,value.get('issue_ids',[])),'导入网页素材',invalidate='sources')


@app.post('/api/articles/{id}/sources/file')
async def add_file(id:str,file:UploadFile=File(),revision:int=Form(),as_draft:bool=Form(False),issue_ids:str=Form('[]')):
    ids=json.loads(issue_ids)
    if not isinstance(ids,list) or not all(isinstance(i,str) for i in ids): raise ValueError('问题关联格式无效')
    blob=await file.read(materials.MAX_BYTES+1)
    if len(blob)>materials.MAX_BYTES: raise ValueError('文件不能超过 20 MB')
    if Path(file.filename or '').suffix.lower() in ('.bib','.ris'):
        rows=bibliography.import_records(file.filename,blob)
        def merge(a):
            for row in rows:
                append_source(a,row,ids)
        return store.save_article(id,revision,merge,'导入文献记录',invalidate='sources')
    text,pages=await asyncio.to_thread(materials.extract_file,file.filename or '',blob)
    filename=store.uid()+Path(file.filename or '').suffix.lower()
    folder=store.article_dir(id)/'materials'; folder.mkdir(exist_ok=True); (folder/filename).write_bytes(blob)
    src=materials.source(file.filename or '文件素材',text,pages=pages,filename=filename)
    src.update(original_filename=file.filename or '文件素材',content_hash=__import__('hashlib').sha256(blob).hexdigest(),attachments=[dict(filename=filename,name=file.filename or '文件素材')])
    if not as_draft: await source_imports.identify_file(src,blob)
    def change(a):
        if as_draft:
            a['content']=text; a['title']=Path(file.filename or '导入文章').stem
            a['brief']['topic']=a['title']; a['stages']['write']='done'; a['current_stage']='write'
        else: append_source(a,src,ids)
    return store.save_article(id,revision,change,'导入稿件' if as_draft else '导入文件素材',invalidate='write' if as_draft else 'sources')


@app.post('/api/articles/{id}/sources/search')
async def search_sources(id:str,value:dict):
    return workflow.start(id,JobRequest(stage='research',revision=value['revision'],instruction=value.get('query',''),chain=False))


@app.post('/api/articles/{id}/sources/{sid}/metadata')
async def source_metadata(id:str,sid:str,value:dict):
    from . import academic
    a=store.get_article(id)
    src=next((s for s in a['sources'] if s['id']==sid),None)
    if not src: raise ValueError('素材不存在')
    result=await academic.lookup_doi(value.get('doi') or bibliography.metadata(src).get('doi',''))
    def update(a):
        s=next(s for s in a['sources'] if s['id']==sid)
        s['bibliography']=result['bibliography'];s['doi']=result['doi']
        s['metadata_provenance']=s.get('metadata_provenance',[])+result['metadata_provenance']
    return store.save_article(id,value['revision'],update,'从 DOI 核对文献信息',invalidate='sources')


@app.get('/api/hotspots')
async def hotspots():
    import subprocess
    env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8',WEWRITE_HOME=str(store.DATA/'wewrite'))
    process=await asyncio.create_subprocess_exec(sys.executable,'-m','wewrite.commands.fetch_hotspots','--limit','20',stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    try:
        out,_=await asyncio.wait_for(process.communicate(),timeout=60)
        return json.loads(out.decode('utf-8'))
    except asyncio.TimeoutError:
        process.kill(); await process.wait(); raise ValueError('公开热点读取超时，可自行输入领域生成常青选题') from None


@app.post('/api/articles/{id}/jobs')
async def start_job_async(id:str,request:JobRequest):
    if getattr(app.state,'restarting',False): raise store.Conflict('后台正在更新，请稍后重试')
    return workflow.start(id,request)


@app.get('/api/articles/{id}/jobs')
def jobs(id:str): return [flow_state.job_view(j) for j in store.jobs(id)]


@app.get('/api/jobs/{id}')
def job(id:str): return flow_state.job_view(store.job(id))


@app.post('/api/jobs/{id}/cancel')
async def stop_job(id:str): return workflow.cancel(id)


@app.get('/api/jobs/{id}/events')
async def job_events(id:str,after:int=0):
    store.job(id)
    async def stream():
        cursor=after
        while True:
            rows=store.events(id,cursor)
            for r in rows:
                cursor=r['seq']; yield 'id: '+str(cursor)+'\ndata: '+json.dumps(r,ensure_ascii=False)+'\n\n'
            if store.job(id)['status'] not in ('running','queued'): break
            if not rows: yield ': keepalive\n\n'
            await asyncio.sleep(.5)
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'X-Accel-Buffering':'no'})


@app.post('/api/articles/{id}/review/{issue_id}')
def apply_issue(id:str,issue_id:str,value:dict):
    action=value.get('action')
    if action not in ('accept','reject'): raise ValueError('未知审核操作')
    def change(a):
        issue=next((x for x in a['review'].get('issues',[]) if x['id']==issue_id),None)
        if not issue: raise ValueError('审核意见不存在')
        if issue['status']!='pending': raise ValueError('这条意见已处理')
        if action=='accept':
            quote=issue['quote']
            if not quote or a['content'].count(quote)!=1: raise ValueError('原文已改变或存在重复，请在正文中手动修改后复审')
            issue['applied_replacement']=value.get('replacement',issue['suggestion'])
            a['content']=a['content'].replace(quote,issue['applied_replacement'],1)
            a['stages']['review']='stale'
        issue['status']='accepted' if action=='accept' else 'rejected'
    return store.save_article(id,value['revision'],change,'接受审核修改' if action=='accept' else '拒绝审核意见',invalidate='write' if action=='accept' else None,review_action=True)


@app.post('/api/articles/{id}/suggestions/{sid}')
def apply_suggestion(id:str,sid:str,value:dict):
    def change(a):
        s=next((x for x in a['suggestions'] if x['id']==sid),None)
        if not s: raise ValueError('修改建议不存在')
        if value.get('action')=='accept':
            if not s['original'] or a['content'].count(s['original'])!=1: raise ValueError('原文已改变或有重复，无法安全替换，请重新选段')
            a['content']=a['content'].replace(s['original'],value.get('replacement',s['replacement']),1)
        a['suggestions']=[x for x in a['suggestions'] if x['id']!=sid]
    return store.save_article(id,value['revision'],change,'处理修改建议',invalidate='write' if value.get('action')=='accept' else None)


@app.post('/api/articles/{id}/images/upload')
async def upload_image(id:str,file:UploadFile=File(),revision:int=Form(),role:str=Form('article'),plan_id:str=Form('')):
    article=store.get_article(id)
    if article['revision']!=revision: raise store.Conflict('文章已有更新，为避免覆盖，未应用本次修改。请先查看最新版本。')
    plan=next((p for p in article['image_plans'] if p['id']==plan_id),None) if plan_id else None
    if plan_id and plan is None: raise ValueError('配图方案已改变，请刷新后重新选择上传位置')
    blob=await file.read(30*1024*1024+1)
    if len(blob)>30*1024*1024: raise ValueError('图片不能超过 30 MB')
    try:
        image=Image.open(io.BytesIO(blob)); image.load()
    except Exception: raise ValueError('无法读取图片，请选择 PNG、JPEG 或 WebP') from None
    if image.width*image.height>40_000_000: raise ValueError('图片像素过大，请缩小后上传')
    filename=store.uid()+'.png'; p=store.article_dir(id)/'assets'; p.mkdir(exist_ok=True)
    image.convert('RGB').save(p/filename,'PNG')
    item=dict(id=store.uid(),filename=filename,role='cover' if role=='cover' else 'article',caption='',after_heading='',selected=True,created=store.now())
    if plan:
        item.update(plan_id=plan_id,role=plan['role'],caption=plan.get('caption',''),after_heading=plan.get('after_heading',''))
    try:
        return store.save_article(id,revision,lambda a:a['images'].append(item),'上传图片',invalidate='visual')
    except Exception:
        (p/filename).unlink(missing_ok=True)
        raise


@app.get('/api/articles/{id}/assets/{filename}')
def asset(id:str,filename:str):
    a=store.get_article(id)
    if not any(x['filename']==filename for x in a['images']): raise HTTPException(404)
    return FileResponse(store.article_dir(id)/'assets'/filename,media_type='image/png')


@app.post('/api/articles/{id}/preview')
def preview(id:str): return rendering.render(store.get_article(id))


@app.post('/api/references/preview')
def reference_preview(value:dict):
    _,references,unresolved=bibliography.citations(str(value.get('content',''))[:500000],value.get('sources',[])[:500])
    return dict(references=references,unresolved=unresolved)


@app.get('/api/articles/{id}/export/{kind}')
def export(id:str,kind:str):
    if kind not in ('zip','md','html'): raise ValueError('未知导出类型')
    info=outputs.archive(store.get_article(id))
    return FileResponse(Path(info['path'])/info['files'][kind],filename=info['basename']+'.'+kind,
                        media_type={'zip':'application/zip','md':'text/markdown','html':'text/html'}[kind])


@app.post('/api/articles/{id}/exports')
def archive_article(id:str,value:dict):
    a=store.get_article(id)
    if value.get('revision')!=a['revision']: raise store.Conflict('文章已更新，请保存后重新导出')
    return outputs.public_info(outputs.archive(a))


@app.post('/api/articles/{id}/exports/open')
def open_exports(id:str,value:dict):
    a=store.get_article(id)
    if value.get('revision')!=a['revision']: raise store.Conflict('文章已更新，请保存后重新导出')
    info=outputs.archive(a)
    if os.name!='nt': raise ValueError('请使用显示的归档路径打开文件夹')
    os.startfile(info['path'])
    return outputs.public_info(info)


@app.get('/api/articles/{id}/exports/{digest}/{kind}')
def download_archive(id:str,digest:str,kind:str):
    store.get_article(id)
    if kind not in ('zip','md','html') or not re.fullmatch('[a-f0-9]{64}',digest): raise HTTPException(404)
    import json
    for record in (outputs.root()/'articles'/id).glob('*/manifest.json'):
        info=json.loads(record.read_text('utf-8'))
        if info.get('digest')==digest:
            return FileResponse(record.parent/info['files'][kind],filename=info['basename']+'.'+kind)
    raise HTTPException(404)


@app.get('/api/articles/{id}/versions')
def get_versions(id:str): return store.versions(id)


@app.post('/api/articles/{id}/restore')
def restore(id:str,value:dict): return store.restore(id,value['version'],value['revision'])


@app.get('/api/articles/{id}/usage')
def usage(id:str): return store.usage(id)


@app.post('/api/shutdown')
async def shutdown(request:Request):
    if not os.environ.get('STUDIO_STOP_TOKEN') or not secrets.compare_digest(request.headers.get('x-stop-token',''),os.environ['STUDIO_STOP_TOKEN']): raise HTTPException(403)
    if (await request.json()).get('restart'):
        with store.connection() as db:
            if db.execute("SELECT 1 FROM jobs WHERE status IN ('running','queued') LIMIT 1").fetchone():
                raise ValueError('仍有生成任务运行，请等待完成或先停止任务后再更新工作台')
        app.state.restarting=True
    async def stop():
        for t in list(workflow.TASKS.values()): t.cancel()
        if workflow.TASKS: await asyncio.gather(*list(workflow.TASKS.values()),return_exceptions=True)
        await asyncio.sleep(.4)
        os._exit(0)
    asyncio.create_task(stop()); return {'message':'已停止工作台'}


if (store.ROOT/'dist').is_dir():
    app.mount('/',StaticFiles(directory=store.ROOT/'dist',html=True),name='frontend')
