"""Live public API acceptance. Never emits credentials or changes settings."""
import asyncio,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import academic,search_tools,store,materials

QUERIES=[('运动科学','resistance training muscle hypertrophy systematic review'),('运动健康','physical activity sedentary cardiovascular mortality'),('AI','retrieval augmented generation large language models'),('跨学科','urban green space mental health')]

async def main():
    results=[]
    for domain,query in QUERIES:
        for channel in ['openalex']+(['arxiv'] if domain=='AI' else ['pubmed'] if domain in ('运动科学','运动健康') else ['crossref']):
            start=time.monotonic()
            try:
                rows=await (search_tools.pubmed(query) if channel=='pubmed' else getattr(academic,channel)(query))
                result=dict(domain=domain,channel=channel,query=query,count=len(rows),rows=rows,seconds=round(time.monotonic()-start,1))
                print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False),flush=True)
            except Exception as e:
                result=dict(domain=domain,channel=channel,query=query,error=str(e),seconds=round(time.monotonic()-start,1));print(json.dumps(result,ensure_ascii=False),flush=True)
            results.append(result)
            Path('output/academic-real.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')

asyncio.run(main())
