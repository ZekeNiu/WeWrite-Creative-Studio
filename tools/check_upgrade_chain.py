import asyncio,json,sys,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import store,search_check,providers,research

async def main():
    results=[];before=research.digest(store.get_settings())
    for column,topic in [('运动科学','resistance training muscle hypertrophy systematic review'),('运动健康','WHO physical activity sedentary behaviour guidelines adults'),('AI','retrieval augmented generation large language models'),('跨学科','urban green space mental health')]:
        a=store.create_article({'column':column,'topic':topic},diagnostic=True)
        j=store.create_job(a['id'],dict(kind='search_check',stage='research',revision=0,chain=False,column=column,topic=topic,without_tavily=True))
        store.update_job(j['id'],config_fingerprint=search_check.fingerprint())
        print(json.dumps(dict(event='start',column=column,job=j['id']),ensure_ascii=False),flush=True)
        await search_check.run(j['id'])
        r=search_check.result(store.job(j['id']));results.append(r)
        Path('output/upgrade-chain-real.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(dict(column=column,passed=r.get('passed'),steps=r.get('steps'),error=r.get('error'),calls=r['research']['calls'],pages=r['research']['pages']),ensure_ascii=False),flush=True)
    assert before==research.digest(store.get_settings()),'Settings changed during validation'
    print('Saved configuration unchanged',flush=True)

asyncio.run(main())
