"""Opt-in paired writing evaluation; no production writes, no search, no model changes."""
import argparse,asyncio,copy,hashlib,json,os,sqlite3,sys,time
from pathlib import Path


def arguments():
    p=argparse.ArgumentParser()
    p.add_argument('--code-root',type=Path,required=True)
    p.add_argument('--settings-root',type=Path,required=True)
    p.add_argument('--bundle',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--variant',choices=('baseline','candidate'),required=True)
    p.add_argument('--ids',default='')
    p.add_argument('--timeout',type=int,default=3600)
    p.add_argument('--concurrency',type=int,default=2)
    return p.parse_args()


async def main(args):
    output=args.output.resolve();production=args.settings_root.resolve();code=args.code_root.resolve()
    if output==production or output==production/'data' or production/'data' in output.parents:
        raise ValueError('Evaluation output must be isolated from production')
    output.mkdir(parents=True,exist_ok=True)
    os.environ['WEWRITE_STUDIO_DATA']=str(output/'data');os.environ['WEWRITE_HOME']=str(output/'upstream-home')
    sys.path.insert(0,str(code))
    from backend import store,providers,workflow
    with sqlite3.connect((production/'data/studio.sqlite').as_uri()+'?mode=ro',uri=True) as db:
        cfg=json.loads(db.execute('select data from settings where id=1').fetchone()[0])
        secrets=dict(db.execute('select id,value from secrets'))
    cfg['search']['enabled']=False
    store.init();store.set_settings(cfg);store.get_secret=lambda sid:secrets.get(sid)
    blob=args.bundle.read_bytes();bundle=json.loads(blob)
    manifest=dict(variant=args.variant,bundle_sha256=hashlib.sha256(blob).hexdigest(),code_root=str(code),
        code_sha256=hashlib.sha256(b''.join(p.read_bytes() for p in sorted((code/'backend').glob('*.py')))).hexdigest(),
        routes={k:dict(service_id=v.get('service_id'),model=v.get('model')) for k,v in cfg.get('routes',{}).items()})
    path=output/'manifest.json'
    if path.exists() and json.loads(path.read_text('utf8'))!=manifest:raise ValueError('Inputs changed; use a new output folder')
    path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    semaphore=asyncio.Semaphore(args.concurrency)
    async def run(item):
        result_path=output/(item['case']+'.json')
        if result_path.exists():return
        async with semaphore:
            a=store.create_article(item['brief'],diagnostic=True)
            a=store.save_article(a['id'],a['revision'],lambda v:v.update(sources=copy.deepcopy(item['sources'])),'Frozen evaluation materials')
            request=dict(stage='write',revision=a['revision'],instruction='',section_id='',selected_text='',chain=False)
            j=store.create_job(a['id'],request);store.update_job(j['id'],status='running')
            result=dict(case=item['case'],variant=args.variant);started=time.monotonic()
            print(json.dumps(dict(event='start',case=item['case'],variant=args.variant)),flush=True)
            try:
                async with asyncio.timeout(args.timeout):
                    if args.variant=='candidate':
                        from backend import editorial,research_contract
                        research_contract.ensure(a)
                        a=await editorial.synthesize(a,j['id'])
                    for stage in ('outline','write','review'):
                        generated=await workflow.call(j['id'],stage,a,request)
                        a=workflow.apply_result(a,stage,generated,request)
                        if stage=='write':result['initial_content']=a['content']
                    if args.variant=='candidate':
                        for _ in range(2):
                            if a['review']['decision']=='pass':break
                            a,candidate=await workflow.edit_candidate(a,j['id'],request)
                            report=candidate['review'];scores=report.get('dimensions',{})
                            if any(x['severity']=='blocker' for x in report.get('issues',[])) or any(type(scores.get(k)) is not int or scores[k]<3 for k in editorial.DIMENSIONS):break
                            a=editorial.adopt(a,candidate['id'],automatic=True)
                    result.update(status='completed',content=a['content'],review=a['review'],outline=a['outline'],
                        argument_synthesis=a.get('argument_synthesis'),editorial_candidates=a.get('editorial_candidates',[]))
            except Exception as exc:result.update(status='incomplete',error=type(exc).__name__+': '+str(exc))
            result.update(seconds=round(time.monotonic()-started,1),article_id=a['id'],job_id=j['id'],usage=store.usage(a['id']))
            result_path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
            store.update_job(j['id'],status='completed' if result['status']=='completed' else 'failed',ended=store.now())
            print(json.dumps({k:result.get(k) for k in ('case','variant','status','seconds','error')},ensure_ascii=False),flush=True)
    await asyncio.gather(*(run(x) for x in bundle['cases'] if not args.ids or x['case'] in args.ids.split(',')))


if __name__=='__main__':asyncio.run(main(arguments()))
