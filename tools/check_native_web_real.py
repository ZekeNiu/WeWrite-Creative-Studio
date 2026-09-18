import asyncio,json,sys
from pathlib import Path
Path('output/diagnostics').mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import providers,research,store,browser_search,search_tools
from backend.app import test_native

async def main():
    result={};before=research.digest(store.get_settings());cfg=providers.settings()
    s=next((s for s in cfg['services'] if 'gemini' in s['model'].lower()),None)
    if s:
        try: result['gemini']=await test_native({'service_id':s['id'],'model':s['model'],'protocol':'gemini'})
        except ValueError as e: result['gemini']={'passed':False,'message':str(e)}
        print(json.dumps({'gemini':result['gemini']},ensure_ascii=False),flush=True)
    try:
        rows=await browser_search.search('retrieval augmented generation original paper','google')
        result['google']={'rows':rows,'available':bool(rows)}
    except Exception as e: result['google']={'available':False,'message':str(e) if isinstance(e,ValueError) else type(e).__name__}
    print(json.dumps({'google':result['google']},ensure_ascii=False),flush=True)
    # Exact DOI query proves absence in PubMed, rather than inferring from missing PMID.
    import httpx
    async with httpx.AsyncClient(timeout=30) as client:
        r=await search_tools.ncbi(client,'esearch.fcgi',{'db':'pubmed','term':'10.1609/aaai.v38i16.29728[DOI]','retmode':'json'})
        result['pubmed_noncoverage']={'doi':'10.1609/aaai.v38i16.29728','response':r.json()}
    result['settings_unchanged']=before==research.digest(store.get_settings())
    Path('output/diagnostics/native-web-real.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')

asyncio.run(main())
