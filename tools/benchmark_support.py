"""Reproducible, private records for opt-in live benchmarks; no production writes."""
import contextvars
import hashlib
import json
from pathlib import Path


def identity(cfg):
    services={s['id']:s for s in cfg.get('services',[])}
    routes={}
    for stage in sorted(set(cfg.get('routes',{}))|{'research','sources','outline','write','review','search'}):
        route=cfg.get('routes',{}).get(stage,{})
        if stage=='research' and not route.get('service_id'):
            route={**cfg.get('routes',{}).get('sources',{}),**{k:v for k,v in route.items() if v}}
        if stage=='search':
            route=dict(service_id=cfg['search'].get('native_service_id'),model=cfg['search'].get('native_model'))
        sid=route.get('service_id') or cfg.get('default_service');s=services.get(sid,{})
        model=route.get('model') or s.get('model','');protocol=s.get('protocol','')
        if stage=='search':
            match=next((x for x in cfg.get('model_connections',[]) if x['service_id']==sid and x['model']==model),None)
            choice=match['search_protocol'] if match else cfg['search'].get('native_protocol','inherit')
            if choice!='inherit':protocol=choice
        routes[stage]=dict(service_id=sid,model=model,protocol=protocol,max_tokens=s.get('max_tokens'),temperature=s.get('temperature'))
    # Include all execution settings but never credentials, even in local manifests.
    def redact(value):
        if isinstance(value,dict):return {k:redact(v) for k,v in value.items() if k not in ('key','secret','openalex_key')}
        if isinstance(value,list):return [redact(v) for v in value]
        return value
    return dict(routes=routes,settings_sha256=hashlib.sha256(json.dumps(redact(cfg),sort_keys=True,ensure_ascii=False).encode()).hexdigest())


def manifest_once(output,manifest):
    output=Path(output);path=output/'manifest.json'
    if path.exists():
        if json.loads(path.read_text('utf8'))!=manifest:
            raise ValueError('Evaluation inputs changed; use a new output folder. Existing records are untouched.')
    else:
        if output.exists() and any(output.iterdir()):
            raise ValueError('Nonempty evaluation folder has no manifest; use a new output folder.')
        output.mkdir(parents=True,exist_ok=True)
        with path.open('x',encoding='utf8') as stream:json.dump(manifest,stream,ensure_ascii=False,indent=2)


class Capture:
    def __init__(self,providers,output):
        self.case=contextvars.ContextVar('benchmark_case',default='unassigned')
        self.frames=contextvars.ContextVar('benchmark_frames',default=None)
        self.output=Path(output);self.counts={}
        generate=providers.generate;frames=providers.frames

        async def captured_frames(response):
            async for frame in frames(response):
                path=self.frames.get()
                if path:
                    with path.open('a',encoding='utf8') as stream:stream.write(json.dumps(frame,ensure_ascii=False)+'\n')
                yield frame

        async def captured_generate(service,system,prompt,emit=None):
            case=self.case.get();self.counts[case]=self.counts.get(case,0)+1
            folder=self.output/'raw'/case;folder.mkdir(parents=True,exist_ok=True)
            stem=f'{self.counts[case]:04d}'
            while (folder/(stem+'.json')).exists():
                self.counts[case]+=1;stem=f'{self.counts[case]:04d}'
            path=folder/(stem+'.json')
            record=dict(service={k:service.get(k) for k in ('id','model','protocol','max_tokens','temperature')},system=system,prompt=prompt,partial='')
            token=self.frames.set(folder/(stem+'.frames.jsonl'))
            async def receive(delta):
                record['partial']+=delta
                if emit:await emit(delta)
            try:
                raw,usage=await generate(service,system,prompt,receive)
                record.update(status='completed',raw=raw,usage=usage)
                return raw,usage
            except BaseException as exc:
                record.update(status='incomplete',error=type(exc).__name__+': '+str(exc))
                raise
            finally:
                path.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf8')
                self.frames.reset(token)
        providers.generate=captured_generate;providers.frames=captured_frames
