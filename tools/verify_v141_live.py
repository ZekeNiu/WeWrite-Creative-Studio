"""Explicit billable full-workflow acceptance, using private isolated copies only."""
import argparse
import asyncio
import copy
import hashlib
import json
import shutil
import sqlite3
import sys
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import store,providers,workflow,issue_actions,outputs,flow_state,bibliography
from backend.models import JobRequest,IssueAction,STAGES


def integrity(path):
    with sqlite3.connect(path) as db:
        return {t:hashlib.sha256(json.dumps(db.execute('SELECT * FROM '+t+' ORDER BY id').fetchall()).encode()).hexdigest()
                for t in ('articles','versions','settings','secrets')}


async def main(case,resume=False,stage=None):
    if stage and not resume: raise ValueError('--stage requires an inspected existing workspace and --resume')
    production=store.DATA;before=integrity(production/'studio.sqlite')
    folder=store.ROOT/'output/test-workspaces'/('live-v141-'+case)
    report_path=store.ROOT/'output/diagnostics'/('live-v141-'+case+'.json')
    if not resume:
        if folder.exists(): raise ValueError('Workspace exists; inspect the last result and use --resume explicitly')
        folder.mkdir(parents=True)
        with sqlite3.connect(production/'studio.sqlite') as src,sqlite3.connect(folder/'studio.sqlite') as dst: src.backup(dst)
    store.DATA=folder;store.init()
    report=json.loads(report_path.read_text('utf-8')) if resume else dict(simulated=False,case=case,steps=[])
    def save(): report_path.parent.mkdir(parents=True,exist_ok=True);report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    def article(): return store.get_article(report['article_id'])
    async def finish(j):
        last='';started=time.monotonic()
        while j['id'] in workflow.TASKS:
            current=store.job(j['id']);message=current.get('message','')
            if message!=last: print(json.dumps(dict(stage=current['stage'],status=current['status'],message=message),ensure_ascii=True),flush=True);last=message
            if time.monotonic()-started>2400: workflow.cancel(j['id']);raise TimeoutError('Live task exceeded 40 minutes; request is not replayed')
            await asyncio.sleep(2)
        j=store.job(j['id']);report['steps'].append(dict(job=j['id'],stage=j['stage'],status=j['status'],message=j.get('message')));save()
        if j['status'] in ('failed','cancelled','conflict','interrupted'): raise ValueError('Live task ended '+j['status']+': '+j['message'])
        return j
    async def run(stage,**kw):
        a=article();return await finish(workflow.start(a['id'],JobRequest(stage=stage,revision=a['revision'],**kw)))
    try:
        if not resume:
            if case=='manual':
                originals=[store.get_article(x['id']) for x in store.list_articles()]
                original=next(a for a in originals if a.get('research',{}).get('pending'))
                a=store.create_article(original['brief'],diagnostic=True)
                fields={k:copy.deepcopy(original[k]) for k in ('title','sources','outline','content','evidence','research','stages')}
                # Copy the former paused task so the recovery path is exercised without touching the original.
                old=store.job(original['research']['job_id']);paused=store.create_job(a['id'],dict(old['request'],revision=a['revision']))
                store.update_job(paused['id'],status='needs_input',stage='outline',research=old.get('research',{}))
                fields['research']['job_id']=paused['id'];fields['research'].pop('resume_job_id',None)
                a=store.save_article(a['id'],a['revision'],lambda v:v.update(fields),'Copy for isolated live acceptance')
                src=production/'articles'/original['id']
                if src.exists(): shutil.copytree(src,store.article_dir(a['id']),dirs_exist_ok=True)
            else:
                a=store.create_article(dict(column='AI',domain='如何核对 AI 回答的来源，面向普通用户的常青科普',purpose='给出可执行的核对方法，不讨论需要新实验才能证明的效果',words=900),auto={s:True for s in STAGES},diagnostic=True)
            a=store.save_article(a['id'],a['revision'],lambda v:v.update(visual={**v['visual'],'enabled':True,'count':1}),'Enable test image')
            report['article_id']=a['id'];save()
        if case=='manual':
            a=article()
            if not report.get('verified_materials'):
                ids=[x['id'] for x in flow_state.issues(a) if x['status']=='open']
                if ids:
                    result=issue_actions.apply(a['id'],IssueAction(revision=a['revision'],issue_ids=ids,action='verify',action_id='live-manual-verify'))
                    await finish(result['job'])
                else: await run('sources',chain=False)
                report['verified_materials']=True;save()
            a=article();remaining=[x['id'] for x in flow_state.issues(a) if x['kind']=='blocking' and x['status']=='open']
            if remaining:
                issue_actions.apply(a['id'],IssueAction(revision=a['revision'],issue_ids=remaining,action='waive',action_id='live-bounded-continue'))
                report['explicit_bounded_continue']=True;save()
            a=article()
            if not a['outline'].get('sections'):
                parent=issue_actions.parent(a)
                await run('outline',chain=False,resume_job_id=parent['id'] if parent else '')
            if not article()['content']: await run('write',chain=False)
            if article()['stages']['review'] not in ('done','needs_input'): await run('review',chain=False)
            if not article()['image_plans']: await run('visual',chain=False)
            if not article()['images']: await run('image',image_id=article()['image_plans'][0]['id'],chain=False)
            await run('layout',chain=False)
        elif article()['stages']['layout']!='done':
            current=article()
            next_stage=stage or next(s for s in STAGES if current['stages'][s]!='done')
            await run(next_stage,chain=True)
        a=article()
        assert a['outline'].get('sections') and a['content'] and a.get('review') and a['images'], 'Incomplete workflow; inspect pause before retrying'
        snapshot=outputs.archive(a)
        import zipfile
        with zipfile.ZipFile(Path(snapshot['path'])/snapshot['files']['zip']) as z:
            assert z.testzip() is None and any(n.startswith('images/') for n in z.namelist())
            assert z.read('文章.md') and z.read('排版.html')
            assert all((Path(snapshot['path'])/n).read_bytes()==z.read(n) for n in z.namelist())
            for im in a['images']:
                if im.get('selected',True):
                    for name in ('文章.md','排版.html'): assert 'images/'+im['filename'] in z.read(name).decode('utf-8')
        _,references,unknown=bibliography.citations(a['content'],a['sources'])
        assert not unknown, 'Export contains unassociated citations'
        report['artifact_checks']=dict(references=len(references),unknown_references=unknown,snapshot_bytes_equal=True,image_links=True)
        report.update(passed=True,error=None,archive=snapshot['path'],content_characters=len(a['content']),outline_sections=len(a['outline']['sections']),images=len(a['images']),review_decision=a['review'].get('decision'),review_stage=a['stages']['review'],review_requires_input=a['stages']['review']!='done')
    except Exception as exc:
        report.update(passed=False,error=str(exc));raise
    finally:
        report['production_unchanged']=integrity(production/'studio.sqlite')==before
        report['usage']=store.usage(report['article_id']) if report.get('article_id') else []
        save();print(json.dumps({k:report.get(k) for k in ('case','passed','production_unchanged','error')},ensure_ascii=True),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('case',choices=['manual','auto']);p.add_argument('--resume',action='store_true');p.add_argument('--stage',choices=STAGES)
    args=p.parse_args();asyncio.run(main(args.case,args.resume,args.stage))
