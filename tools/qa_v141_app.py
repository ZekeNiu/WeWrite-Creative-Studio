"""Deterministic paused-workflow UI fixture; private workspace only."""
import json
from tools.qa_v14_app import app
from tools.qa_research_app import generate as normal_generate
from backend import store,providers,materials


async def generate(s,system,prompt,emit=None):
    v=json.loads(prompt) if prompt.startswith('{') else {}
    ctx=v.get('context',{})
    if v.get('schema',{}).get('title')=='ResearchNotes' and ctx.get('brief',{}).get('topic')=='核实流程验收':
        sources=ctx['sources'];fixed=any('已补充关键范围' in x['text'] for x in sources)
        result={'summary':'模拟核实结果，范围已补充。' if fixed else '模拟资料仍有一项范围问题。',
                'evidence':[{'source_id':sources[0]['id'],'quote':'研究只适用于给定条件。','claim':'存在适用条件'}],
                'issues':[dict(x,status='resolved',resolution='补充材料给出了适用范围',source_ids=[sources[0]['id']]) for x in ctx.get('issue_decisions',[]) if x['kind']=='blocking'] if fixed else [],
                'gaps':[] if fixed else ['缺少关键适用范围'],'conflicts':['样本有限，保留适用边界'],'followup_queries':[]}
        return json.dumps(result,ensure_ascii=False),{'model':s['model'],'status':'completed','estimated_cost':None}
    return await normal_generate(s,system,prompt,emit)


providers.generate=generate
a=store.create_article({'topic':'核实流程验收'},diagnostic=True)
source=materials.source('模拟资料','研究只适用于给定条件。'*30)
old=store.create_job(a['id'],{'stage':'outline','revision':a['revision'],'chain':False})
store.update_job(old['id'],status='completed',research={'calls':12,'pages':7,'log':[],'notes':{'gaps':['缺少关键适用范围']}})
j=store.create_job(a['id'],{'stage':'outline','revision':a['revision'],'chain':False})
r=dict(stage='outline',job_id=j['id'],stale=False,pending=True,summary='模拟资料仍有一项范围问题。',gaps=['缺少关键适用范围'],
       conflicts=['样本有限，保留适用边界'],calls=0,pages=0,rounds=0,log=[],blocked_urls=[],strategy={'preference':'native','allow_fallback':True,'attempted':[],'used':[]})
store.update_job(j['id'],status='completed',research=dict(r,notes={'gaps':r['gaps'],'conflicts':r['conflicts']}))
store.save_article(a['id'],a['revision'],lambda v:v.update(sources=[source],research=r,stages={**v['stages'],'outline':'needs_input'}),'Paused fixture')
(store.DATA/'workflow-fixture.json').write_text(json.dumps({'article_id':a['id']}),'utf-8')
