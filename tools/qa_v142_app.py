"""Synthetic materials browser fixtures; no real model calls or production data."""
import os
import json
from pathlib import Path
os.environ['WEWRITE_STUDIO_DATA']=str(Path('output/test-workspaces/qa-v142').resolve())
from backend import store,providers,materials
from backend.models import Settings
from tools.qa_research_app import app,generate as normal_generate
store.init()
providers.save_settings(Settings.model_validate(dict(services=[dict(id='fixture',name='模拟服务',model='fixture',key='offline-fixture-key',image_price=1)],default_service='fixture',search={'enabled':False})))


async def generate(s,system,prompt,emit=None):
    raw,usage=await normal_generate(s,system,prompt,None)
    v=json.loads(prompt)
    if v.get('schema',{}).get('title') in ('ResearchNotes','EvidenceResult'):
        result=json.loads(raw);ctx=v.get('context') or v.get('资料与当前内容',{})
        raw=json.dumps(result,ensure_ascii=False)
    if emit:await emit(raw)
    return raw,usage
providers.generate=generate
fixtures={}
for n in (0,1,30,100):
    a=store.create_article({'topic':'素材交互验收 '+str(n)},diagnostic=True)
    sources=[materials.source(('匹配材料 ' if i<30 else '其他素材 ')+str(i+1),'研究只适用于给定条件。'*35) for i in range(n)]
    for i,s in enumerate(sources):s['selected']=i%3!=0
    issues=[dict(id='I'+str(i),text='需要核对第 '+str(i+1)+' 项适用范围。'*8,kind='blocking',source_ids=[sources[0]['id']] if sources else [],claim='',status='open') for i in range(25)] if n==100 else []
    if n==100:issues.extend([dict(id='L1',text='样本范围有限，写作时保留边界',kind='limitation',source_ids=[],claim='',status='open'),dict(id='D1',text='已经完成的问题',kind='blocking',source_ids=[],claim='',status='resolved')])
    j=store.create_job(a['id'],{'stage':'outline','revision':a['revision'],'chain':False}) if issues else None
    if j:store.update_job(j['id'],status='needs_input',stage='outline',message='资料核对暂停，请处理待核实问题')
    def seed(v):
        v['sources']=sources
        for s in sources:s['ai_use']={'text':'旧版用途，不应展示或传入模型','input_key':'legacy'}
        if sources:
            v['evidence']={'summary':'模拟整理结果','claims':[dict(id='C1',text='材料有适用条件',source_ids=[sources[1 if n>1 else 0]['id']],status='bounded',boundary='仅限案例')]}
            v['outline']={'sections':[dict(id='sec1',title='证据的适用条件',claim_ids=['C1'])]}
        if issues:v['research']=dict(stage='outline',job_id=j['id'],summary='整理结果摘要。'*80,pending=True,stale=False,issues=issues,gaps=[],conflicts=[],log=[])
    a=store.save_article(a['id'],a['revision'],seed,'Synthetic UI fixture');fixtures[str(n)]=a['id']
(store.DATA/'materials-fixtures.json').write_text(json.dumps(fixtures),'utf-8')
