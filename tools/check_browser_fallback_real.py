import asyncio,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import store,research,providers
from backend.models import ResearchNotes

async def main():
    a=store.create_article({'column':'AI','topic':'retrieval augmented generation original paper'},diagnostic=True)
    j=store.create_job(a['id'],dict(stage='research',revision=0,chain=False,kind='browser_acceptance'))
    w=research.Research(a,j['id'],'sources');w.cfg.update(academic_enabled=False,pubmed_enabled=False,tavily_enabled=False);w.target=1;w.search_model=None
    store.update_job(j['id'],status='running')
    try:
        await w.discover([a['brief']['topic']])
        notes=research.validate_spans(await research.structured(a,'sources','用不超过100字中文回答主题，提供1条逐字原文 evidence.quote（20至150字符）和适用边界。',ResearchNotes,j['id']),a['sources']) if w.added else {}
        result=dict(passed=any(e.get('source_status')=='retrieved' for e in notes.get('evidence',[])),notes=notes,sources=w.added,log=w.log,calls=w.calls,pages=w.pages)
    except Exception as e: result=dict(passed=False,error=str(e) if isinstance(e,ValueError) else type(e).__name__,log=w.log)
    store.update_job(j['id'],status='completed' if result['passed'] else 'failed',ended=store.now())
    Path('output/browser-fallback-real.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('sources','log','notes')},ensure_ascii=False),flush=True)

asyncio.run(main())
