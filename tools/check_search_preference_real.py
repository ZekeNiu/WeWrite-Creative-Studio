"""One live preferred-model check; production service settings are read-only."""
import asyncio,json,sys
from pathlib import Path
Path('output/diagnostics').mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import store,providers,research
from backend.models import ResearchNotes

async def main():
    cfg=providers.settings();before=research.digest(store.get_settings())
    service=next(s for s in cfg['services'] if 'gemini' in s['model'].lower())
    native=providers.effective_service('search',{**cfg,'search':{**cfg['search'],'native_service_id':service['id'],'native_model':service['model'],'native_protocol':'gemini'}})
    if store.capability(providers.fingerprint(native,'search'))['status']!='tested': raise ValueError('Selected Gemini adapter must already be verified')
    a=store.create_article({'column':'运动健康','topic':'WHO physical activity adults 150 300 minutes original guideline'},diagnostic=True)
    j=store.create_job(a['id'],dict(stage='research',revision=0,chain=False,kind='preference_acceptance'))
    w=research.Research(a,j['id'],'sources');w.target=1;w.search_model=native
    w.cfg.update(preference='native',allow_fallback=True,max_calls=min(8,w.cfg['max_calls']),max_pages=min(16,w.cfg['max_pages']))
    store.update_job(j['id'],status='running');print('Live preferred-model check started: '+j['id'],flush=True)
    try:
        await w.discover([a['brief']['topic']])
        notes=research.validate_spans(await research.structured(a,'sources','用100字以内中文回答一个主题问题，提供1条逐字原文证据（20–150字符）；优先已读全文，明确适用边界。',ResearchNotes,j['id']),a['sources']) if w.added else {}
        result=dict(passed=bool(w.attempted and w.attempted[0]=='native' and any(e['source_status']=='retrieved' for e in notes.get('evidence',[]))),strategy=w.strategy(),log=w.log,notes=notes,sources=w.added,usage=store.usage(a['id']))
    except Exception as exc: result=dict(passed=False,error=str(exc) if isinstance(exc,ValueError) else type(exc).__name__,strategy=w.strategy(),log=w.log)
    result['settings_unchanged']=before==research.digest(store.get_settings())
    store.update_job(j['id'],status='completed' if result['passed'] else 'failed',ended=store.now())
    Path('output/diagnostics/search-preference-real.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k in ('passed','error','strategy','settings_unchanged')},ensure_ascii=False),flush=True)

asyncio.run(main())
