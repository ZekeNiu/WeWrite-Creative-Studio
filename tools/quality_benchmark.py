"""Opt-in live evaluation. Production settings/secrets are read-only; all writes isolated."""
import argparse, asyncio, copy, hashlib, json, os, re, sqlite3, sys, time
from pathlib import Path
from urllib.parse import urlsplit

METRIC_VERSION=3


def arguments():
    p=argparse.ArgumentParser()
    p.add_argument('--code-root',type=Path,default=Path(__file__).resolve().parents[1])
    p.add_argument('--settings-root',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--cases',type=Path,default=Path(__file__).resolve().parents[1]/'tests/fixtures/quality_cases.json')
    p.add_argument('--mode',choices=['known','blind'],default='blind')
    p.add_argument('--round',type=int,default=1)
    p.add_argument('--ids',default='')
    p.add_argument('--concurrency',type=int,default=2)
    p.add_argument('--timeout',type=int,default=1200)
    return p.parse_args()


def found(case,sources):
    def normal(s):return re.sub(r'[^a-z0-9]+','',s.lower())
    for s in sources:
        meta=s.get('bibliography') or {}
        if case.get('doi') and case['doi'].lower() in (s.get('doi','').lower(),meta.get('doi','').lower()):return True
        if case.get('arxiv') and case['arxiv'] in (s.get('arxiv_id','')+' '+s.get('url','')):return True
        actual=urlsplit(s.get('url',''))
        expected=[urlsplit('https://'+u) for u in case.get('urls',[])]
        host=(actual.hostname or '').removeprefix('www.')
        if any(host==(u.hostname or '').removeprefix('www.') and actual.path.rstrip('/')==u.path.rstrip('/') for u in expected):return True
        # A secondary page can repeat the exact paper title. Its title alone does
        # not establish the original publication's identity.
        # A publisher PDF may retain its filename as title. Check its own first-page
        # heading on the already accepted official host, never mentions in body/references.
        official={(u.hostname or '').removeprefix('www.') for u in expected}
        front=(s.get('pages') or [{}])[0].get('text','')
        heading=normal(case['title']) in normal(front[:500])
        if not heading:continue
        if re.search(r'\b(presented\s+by|presenter|lecture|slides)\b',front[:500],re.I):continue
        if host in official:return True
        # Author-hosted original PDFs may have filenames rather than title/DOI
        # metadata. Require the heading and abstract on the same first page;
        # a lecture cover or a bibliography mention cannot satisfy this path.
        # This is a discovery metric; original-source review remains mandatory.
        if normal(front).startswith(normal(case['title'])) and re.search(r'\babstract\b',front,re.I) and len(front)>1000:return True
    return False


async def main(args):
    output=args.output.resolve();root=args.settings_root.resolve();code=args.code_root.resolve()
    if output==root or output==root/'data' or root/'data' in output.parents:
        raise ValueError('Benchmark output must not be in production data')
    os.environ['WEWRITE_STUDIO_DATA']=str(output/'data')
    os.environ['WEWRITE_HOME']=str(output/'upstream-home')
    sys.path.insert(0,str(code))
    from backend import store,providers,research
    with sqlite3.connect((root/'data/studio.sqlite').as_uri()+'?mode=ro',uri=True) as db:
        cfg=json.loads(db.execute('select data from settings where id=1').fetchone()[0])
        secrets=dict(db.execute('select id,value from secrets'))
    from tools.benchmark_support import identity,manifest_once,Capture
    payload=args.cases.read_bytes();cases=json.loads(payload)['cases']
    manifest=dict(metric_version=METRIC_VERSION,cases_sha256=hashlib.sha256(payload).hexdigest(),code_root=str(code),mode=args.mode,round=args.round,
                  code_sha256=hashlib.sha256(b''.join(p.read_bytes() for p in sorted((code/'backend').glob('*.py')))).hexdigest(),
                  timeout_seconds=args.timeout,
                  search_limits={k:cfg['search'].get(k) for k in ('max_calls','max_pages','max_rounds')},
                  runner_sha256=hashlib.sha256(Path(__file__).read_bytes()+Path(__file__).with_name('benchmark_support.py').read_bytes()).hexdigest(),
                  concurrency=args.concurrency,**identity(cfg))
    manifest_once(output,manifest)
    store.init();store.set_settings(cfg);store.get_secret=lambda sid:secrets.get(sid)
    capture=Capture(providers,output)
    sem=asyncio.Semaphore(args.concurrency)
    async def run(case):
        path=output/(case['id']+'.json')
        if path.exists():return
        async with sem:
            capture.case.set(case['id'])
            a=store.create_article(dict(topic=case[args.mode],column=case['domain']),diagnostic=True)
            # The research engine's diagnostic flag has a special short path; exercise normal behavior.
            a.pop('diagnostic',None)
            j=store.create_job(a['id'],dict(stage='sources',revision=0,chain=False))
            store.update_job(j['id'],status='running')
            w=research.Research(copy.deepcopy(a),j['id'],'sources');start=time.monotonic()
            print(json.dumps(dict(event='start',case=case['id'],mode=args.mode)),flush=True)
            result={}
            try:
                async with asyncio.timeout(args.timeout):pending=await w.run('')
                result.update(status='completed',pending=pending,found=found(case,w.a['sources']))
            except (Exception,asyncio.CancelledError) as e:result.update(status='interrupted' if isinstance(e,asyncio.CancelledError) else 'incomplete',error=type(e).__name__+': '+str(e),found=False)
            result.update(case=case['id'],seconds=round(time.monotonic()-start,1),plan=w.plan,notes=w.notes,coverage=getattr(w,'coverage',None),stats=w.stats,
                          found_readable=found(case,[s for s in w.a['sources'] if s.get('status') in ('retrieved','abstract_only','user_provided')]),
                          query_ledger=getattr(w,'query_ledger',[]),candidates=list(getattr(w,'candidates',{}).values()),
                          article_id=a['id'],job_id=j['id'],research_contract=w.a.get('research_contract'),
                          stop_reason=w.stop_reason,stop_code=w.stop_code,sources=w.a['sources'],log=w.log,usage=store.usage(a['id']))
            path.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
            store.update_job(j['id'],status='completed' if result['status']=='completed' else 'failed',ended=store.now())
            print(json.dumps({k:result.get(k) for k in ('case','status','seconds','found','pending','error')},ensure_ascii=False),flush=True)
    tasks=[asyncio.create_task(run(c)) for c in cases if not args.ids or c['id'] in args.ids.split(',')]
    async def watch_stop():
        while any(not task.done() for task in tasks):
            if (output/'STOP').exists():
                for task in tasks:task.cancel()
                return
            await asyncio.sleep(1)
    watcher=asyncio.create_task(watch_stop())
    outcomes=await asyncio.gather(*tasks,return_exceptions=True)
    watcher.cancel()
    await asyncio.gather(watcher,return_exceptions=True)
    for outcome in outcomes:
        if isinstance(outcome,BaseException) and not isinstance(outcome,asyncio.CancelledError):raise outcome
    results=[json.loads((output/(c['id']+'.json')).read_text('utf8')) for c in cases if (output/(c['id']+'.json')).exists()]
    print(json.dumps(dict(completed=sum(x['status']=='completed' for x in results),found=sum(x['found'] for x in results),
        completed_readable=sum(x['status']=='completed' and x['found_readable'] for x in results),total=len(results),expected=len(cases))),flush=True)


if __name__=='__main__':asyncio.run(main(arguments()))
