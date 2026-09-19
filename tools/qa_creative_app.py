"""Simulated material lifecycle, with no paid requests and isolated articles."""
import json
import os
from pathlib import Path
os.environ['WEWRITE_STUDIO_DATA']=str(Path('output/test-workspaces/qa-creative').resolve())
from tools.qa_research_app import app,generate as base_generate
from backend import store,providers
from backend.models import Settings
from fastapi.staticfiles import StaticFiles

store.init()
providers.save_settings(Settings.model_validate(dict(services=[dict(id='offline',name='离线流程验收',model='fixture',key='offline-fixture')],default_service='offline',search={'enabled':True,'max_rounds':0,'academic_enabled':False})))
for route in app.routes:
    if getattr(route,'name','')=='frontend': route.app=StaticFiles(directory=store.ROOT/'output/sidebar-dist',html=True)


async def generate(s,system,prompt,emit=None):
    v=json.loads(prompt) if prompt.startswith('{') else {};schema=v.get('schema',{}).get('title')
    ctx=v.get('context') or v.get('资料与当前内容') or {};sources=ctx.get('sources',[])
    if schema=='ResearchNotes':
        uploaded=next((x for x in sources if '补充原文' in x.get('text','')),None)
        source=uploaded or (sources[0] if sources else None)
        old=next((x for x in ctx.get('issue_decisions',[]) if x.get('claim')=='核心样本的适用范围'),{})
        r=dict(summary='模拟资料已整理，原文范围需核对。',evidence=[dict(source_id=source['id'],claim='核心样本的适用范围',quote='研究只适用于给定条件。',type='fact',quality='suitable',boundary='不外推人群')] if source else [],
            issues=[dict(id=old.get('id','Qscope'),text='需要补充原文确认核心样本的适用范围',claim='核心样本的适用范围',kind='blocking',source_ids=[source['id']] if source else [],status='resolved' if uploaded else 'open',resolution='补充原文已确认适用范围' if uploaded else ''),
                    dict(id='Qlimit',text='观察性研究不能证明因果',claim='',kind='limitation',source_ids=[],status='open')],gaps=[],conflicts=[],followup_queries=[])
        text=json.dumps(r,ensure_ascii=False)
        if emit: await emit(text)
        return text,dict(model='fixture',service='offline',status='completed',estimated_cost=0)
    raw,usage=await base_generate(s,system,prompt,emit)
    if schema=='OutlineResult':
        r=json.loads(raw)
        for section in r['sections']: section['claim_ids']=[c['id'] for c in ctx.get('evidence',{}).get('claims',[])][:1]
        raw=json.dumps(r,ensure_ascii=False)
    return raw,usage


providers.generate=generate
a=store.create_article({'topic':'模拟完整创作流程','audience':'专业解读'})
(store.DATA/'fixture.json').write_text(json.dumps({'id':a['id']}),encoding='utf-8')
