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
    p.add_argument('--engine',choices=('native','legacy'),default='native')
    p.add_argument('--ids',default='')
    p.add_argument('--timeout',type=int,default=3600)
    p.add_argument('--concurrency',type=int,default=2)
    return p.parse_args()


async def legacy_main(args):
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


def isolated_output(output, settings_root):
    output=output.resolve(); settings_root=settings_root.resolve()
    data=settings_root/'data'
    if output==settings_root or output.is_relative_to(data) or settings_root.is_relative_to(output):
        raise ValueError('Evaluation output must be isolated from production')
    return output


async def native_case(item,variant,output,timeout):
    """Both variants use exactly the production stage runner and candidate handoff."""
    from backend import store,workflow,models
    original=item.get('article') or dict(brief=item['brief'],sources=item['sources'])
    a=store.create_article(original['brief'],diagnostic=True)
    def seed(v):
        for key in ('title','sources','evidence','creative_intent','native_brief','research',
                    'research_decisions','excluded_sources','argument_synthesis'):
            if key in original:v[key]=copy.deepcopy(original[key])
        v['native_brief']=dict(v.get('native_brief',{}),sections=[])
        v['auto']={key:False for key in v['auto']}
        v['stages'].update(topic='done',sources='done')
    a=store.save_article(a['id'],a['revision'],seed,'Frozen evaluation inputs')
    result=dict(case=item['case'],variant=variant,engine='native',article_id=a['id'],jobs=[])
    started=time.monotonic()
    print(json.dumps(dict(event='start',case=item['case'],variant=variant)),flush=True)
    try:
        async with asyncio.timeout(timeout):
            for stage in ('outline','write','review'):
                request=models.JobRequest(stage=stage,revision=a['revision'],chain=False).model_dump()
                job=store.create_job(a['id'],request);result['jobs'].append(job['id'])
                await workflow.run(job['id'])
                job=store.job(job['id']);a=store.get_article(a['id'])
                if job['status'] not in ('completed','needs_input') or (job['status']=='needs_input' and stage!='review'):
                    raise ValueError(stage+': '+job.get('message',job['status']))
                if stage=='write':result['initial_content']=a['content']
            candidate=next((c for c in reversed(a.get('editorial_candidates',[])) if c.get('job_id')==job['id']),None)
            result.update(status='completed',content=candidate['content'] if candidate else a['content'],
                review=candidate['review'] if candidate else a['review'])
    except Exception as exc:result.update(status='incomplete',error=type(exc).__name__+': '+str(exc))
    finally:
        a=store.get_article(a['id'])
        result.update(seconds=round(time.monotonic()-started,1),outline=a.get('outline'),
            native_executions=a.get('native_executions',[]),editorial_candidates=a.get('editorial_candidates',[]),
            usage=store.usage(a['id']))
        (output/(item['case']+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps({k:result.get(k) for k in ('case','variant','status','seconds','error')},ensure_ascii=False),flush=True)
    return result


async def native_main(args):
    output=isolated_output(args.output,args.settings_root);code=args.code_root.resolve()
    isolated_output(output,code)
    output.mkdir(parents=True,exist_ok=True)
    os.environ['WEWRITE_STUDIO_DATA']=str(output/'data');os.environ['WEWRITE_HOME']=str(output/'upstream-home')
    sys.path.insert(0,str(code))
    from backend import store,native_runtime,native_skills
    blob=args.bundle.read_bytes();bundle=json.loads(blob);runner=Path(__file__).read_bytes()
    with sqlite3.connect((args.settings_root.resolve()/'data/studio.sqlite').as_uri()+'?mode=ro',uri=True) as source:
        cfg=json.loads(source.execute('SELECT data FROM settings WHERE id=1').fetchone()[0])
        account=source.execute('SELECT data FROM account_memory WHERE id=1').fetchone()
        manifest=dict(engine='native',variant=args.variant,bundle_sha256=hashlib.sha256(blob).hexdigest(),
            code_root=str(code),code_sha256=hashlib.sha256(b''.join(p.read_bytes() for p in sorted((code/'backend').glob('*.py')))).hexdigest(),
            settings_sha256=hashlib.sha256(json.dumps(cfg,sort_keys=True).encode()).hexdigest(),
            account_sha256=hashlib.sha256((account[0] if account else '').encode()).hexdigest(),
            upstream_revision=native_skills.verify(),runner_sha256=hashlib.sha256(runner).hexdigest())
        path=output/'manifest.json'
        if path.exists() and json.loads(path.read_text('utf8'))!=manifest:raise ValueError('Inputs changed; use a new output folder')
        if not (store.DATA/'studio.sqlite').exists():
            store.DATA.mkdir(parents=True,exist_ok=True)
            with sqlite3.connect(store.DATA/'studio.sqlite') as target:source.backup(target)
    path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    (output/'runner.py').write_bytes(runner)
    store.init();cfg['search']['enabled']=False;store.set_settings(cfg)
    # Frozen inputs must not grow through WebFetch even when search is disabled.
    execute=native_runtime.Session.execute
    async def frozen_execute(session,name,arguments):
        if name in ('WebSearch','WebFetch'):
            raise ValueError('本次对照的资料已冻结，请用 Read/Find 阅读 source-texts 中已有原文，不补充外部资料。')
        return await execute(session,name,arguments)
    native_runtime.Session.execute=frozen_execute
    semaphore=asyncio.Semaphore(args.concurrency)
    async def run(item):
        saved=output/(item['case']+'.json')
        if saved.exists():return json.loads(saved.read_text('utf-8'))
        async with semaphore:return await native_case(item,args.variant,output,args.timeout)
    try:results=await asyncio.gather(*(run(item) for item in bundle['cases'] if not args.ids or item['case'] in args.ids.split(',')))
    finally:native_runtime.Session.execute=execute
    return bool(results) and all(result.get('status')=='completed' for result in results)


async def main(args):
    if args.engine=='native':return await native_main(args)
    else:await legacy_main(args)


if __name__=='__main__':
    if asyncio.run(main(arguments())) is False:raise SystemExit(1)
