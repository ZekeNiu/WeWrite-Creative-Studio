"""Explicit live acceptance: synthetic task, isolated DB, existing local credentials.

Run manually with --image to include one potentially billable generated image.
Never imported by the application and never prints credentials or article content.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import store,providers,security,research,capabilities
from backend.models import Settings,CapabilityTest


async def main(include_image=False):
    original_data=store.DATA;raw=store.get_settings();cfg=providers.settings()
    baseline=research.digest(raw)
    native=providers.effective_service('search');image=providers.effective_service('image') if include_image else None
    # Only synthetic inputs enter this isolated workspace.
    config=Settings.model_validate(cfg).model_dump()
    for s in config['services']: s['key']=security.key(s['id'])
    store.DATA=store.ROOT/'output/test-workspaces/live-v14';store.init()
    providers.save_settings(Settings.model_validate(config));config=None
    report={'simulated':False,'checks':[]}
    candidates=[('configured',native)]
    gemini=next((s for s in cfg['services'] if 'gemini' in s['model'].lower()),None)
    if gemini and (gemini['id'],gemini['model'])!=(native['id'],native['model']):
        candidates.append(('gemini',capabilities.resolve(providers.settings(),gemini['id'],gemini['model'],'search','gemini')))
    for label,s in candidates:
        a=store.create_article({'column':'公开指南','domain':'公开机构资料','topic':'WHO physical activity guidelines adults 150 300 minutes'},diagnostic=True)
        j=store.create_job(a['id'],{'stage':'research','revision':0,'chain':False})
        w=research.Research(a,j['id'],'sources');w.search_model=s
        w.cfg.update(academic_enabled=False,tavily_enabled=False,browser_enabled=False,page_render_enabled=False,allow_fallback=False)
        print('Starting live search: '+label,flush=True)
        try:
            await w.discover([a['brief']['topic']])
            result=dict(kind='search',label=label,passed=any(e.get('source_status')=='retrieved' for e in w.notes.get('evidence',[])),
                        strategy=w.strategy(),calls=w.calls,pages=w.pages,notes=w.notes,log=w.log)
        except Exception as exc:
            result=dict(kind='search',label=label,passed=False,error=str(exc) if isinstance(exc,ValueError) else type(exc).__name__)
        report['checks'].append(result);print(json.dumps({k:result[k] for k in ('kind','label','passed')},ensure_ascii=True),flush=True)
        if result['passed']: break
    if include_image:
        print('Starting live image test: one image',flush=True)
        try:
            result=await capabilities.test(image['id'],CapabilityTest(model=image['model'],kind='image'))
            report['checks'].append(dict(kind='image',passed=True,width=result['width'],height=result['height']))
        except Exception as exc:
            report['checks'].append(dict(kind='image',passed=False,error=str(exc) if isinstance(exc,ValueError) else type(exc).__name__))
    store.DATA=original_data
    report['production_settings_unchanged']=research.digest(store.get_settings())==baseline
    dest=store.ROOT/'output/diagnostics/live-v14.json';dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps({'checks':[{k:r[k] for k in ('kind','passed')} for r in report['checks']],
                      'production_settings_unchanged':report['production_settings_unchanged']},ensure_ascii=True),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--image',action='store_true')
    asyncio.run(main(parser.parse_args().image))
