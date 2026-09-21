"""Opt-in live evaluation. Production settings/secrets are read-only; all writes isolated."""
import argparse, asyncio, copy, hashlib, json, os, re, sqlite3, sys, time
from pathlib import Path
from urllib.parse import urlsplit

METRIC_VERSION=2


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
        meta=s.get('bibliography',{})
        if case.get('doi') and case['doi'].lower() in (s.get('doi','').lower(),meta.get('doi','').lower()):return True
        if case.get('arxiv') and case['arxiv'] in (s.get('arxiv_id','')+' '+s.get('url','')):return True
        if any(u in s.get('url','') for u in case.get('urls',[])):return True
        if normal(case['title']) in normal(s.get('title','')):return True
        # A publisher PDF may retain its filename as title. Check its own first-page
        # heading on the already accepted official host, never mentions in body/references.
        host=(urlsplit(s.get('url','')).hostname or '').removeprefix('www.')
        official={(urlsplit('https://'+u).hostname or '').removeprefix('www.') for u in case.get('urls',[])}
        front=(s.get('pages') or [{}])[0].get('text','')[:500]
        if host in official and normal(case['title']) in normal(front):return True
    return False


async def main(args):
    output=args.output.resolve();root=args.settings_root.resolve();code=args.code_root.resolve()
    if output==root or output==root/'data' or root/'data' in output.parents:
        raise ValueError('Benchmark output must not be in production data')
    output.mkdir(parents=True,exist_ok=True)
    os.environ['WEWRITE_STUDIO_DATA']=str(output/'data')
    os.environ['WEWRITE_HOME']=str(output/'upstream-home')
    sys.path.insert(0,str(code))
    from backend import store,providers,research
    with sqlite3.connect((root/'data/studio.sqlite').as_uri()+'?mode=ro',uri=True) as db:
        cfg=json.loads(db.execute('select data from settings where id=1').fetchone()[0])
        secrets=dict(db.execute('select id,value from secrets'))
    store.init();store.set_settings(cfg);store.get_secret=lambda sid:secrets.get(sid)
    payload=args.cases.read_bytes();cases=json.loads(payload)['cases']
    manifest=dict(metric_version=METRIC_VERSION,cases_sha256=hashlib.sha256(payload).hexdigest(),code_root=str(code),mode=args.mode,round=args.round,
                  code_sha256=hashlib.sha256(b''.join(p.read_bytes() for p in sorted((code/'backend').glob('*.py')))).hexdigest(),
                  timeout_seconds=args.timeout,
                  search_limits={k:cfg['search'].get(k) for k in ('max_calls','max_pages','max_rounds')},
                  routes={k:dict(service_id=v.get('service_id'),model=v.get('model')) for k,v in cfg.get('routes',{}).items()})
    (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),'utf8')
    sem=asyncio.Semaphore(args.concurrency)
    async def run(case):
        path=output/(case['id']+'.json')
        if path.exists():return
        async with sem:
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
            except Exception as e:result.update(status='incomplete',error=type(e).__name__+': '+str(e),found=False)
            result.update(case=case['id'],seconds=round(time.monotonic()-start,1),plan=w.plan,notes=w.notes,coverage=getattr(w,'coverage',None),stats=w.stats,
                          found_readable=found(case,[s for s in w.a['sources'] if s.get('status') in ('retrieved','abstract_only','user_provided')]),
                          query_ledger=getattr(w,'query_ledger',[]),candidates=list(getattr(w,'candidates',{}).values()),
                          stop_reason=w.stop_reason,sources=w.a['sources'],log=w.log,usage=store.usage(a['id']))
            path.write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf8')
            store.update_job(j['id'],status='completed' if result['status']=='completed' else 'failed',ended=store.now())
            print(json.dumps({k:result.get(k) for k in ('case','status','seconds','found','pending','error')},ensure_ascii=False),flush=True)
    await asyncio.gather(*(run(c) for c in cases if not args.ids or c['id'] in args.ids.split(',')))
    results=[json.loads((output/(c['id']+'.json')).read_text('utf8')) for c in cases if (output/(c['id']+'.json')).exists()]
    print(json.dumps(dict(completed=sum(x['status']=='completed' for x in results),found=sum(x['found'] for x in results),total=len(results))),flush=True)


if __name__=='__main__':asyncio.run(main(arguments()))
