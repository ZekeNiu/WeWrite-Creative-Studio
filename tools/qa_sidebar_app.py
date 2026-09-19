"""Offline sidebar fixtures. Only writes into output/test-workspaces/qa-sidebar."""
import json
import os
from pathlib import Path

os.environ['WEWRITE_STUDIO_DATA']=str(Path('output/test-workspaces/qa-sidebar').resolve())
from tools.qa_research_app import app  # Installs simulated generation, search and image providers.
from backend import store,providers,materials,workflow
from backend.models import Settings
from fastapi.staticfiles import StaticFiles
from PIL import Image

store.init()
providers.save_settings(Settings.model_validate(dict(services=[dict(id='offline',name='离线验收',model='fixture',key='offline-fixture')],default_service='offline',search={'enabled':False})))
for route in app.routes:
    if getattr(route,'name','')=='frontend':
        route.app=StaticFiles(directory=store.ROOT/'output/sidebar-dist',html=True)

fixtures={}
for case in ('full','other','empty','review','flows','long'):
    a=store.create_article({'topic':'侧栏隔离验收 · '+case})
    if case!='empty':
        sources=[]
        for i in range(12):
            s=materials.source('模拟素材 '+str(i+1),'模拟证据仅适用于测试条件。')
            s.update(id='S'+str(i+1),selected=i!=1,summary='资料摘要 '+str(i+1))
            s['bibliography']=dict(title=s['title'],document_type='M',authors=['测试作者'],year='2025',publisher='测试出版社',publication_place='北京')
            sources.append(s)
        claims=[dict(id='C1',text='仅在测试条件下得到支持',type='fact',status='bounded',boundary='不外推到其他条件',source_ids=['S1','S2','Sdeleted']),dict(id='C2',text='尚缺少支持的判断',type='fact',status='unsupported',boundary='',source_ids=['S12'])]
        if case=='long': claims[0]['text']='长主张的依据与适用范围需要完整保留。'*50
        sections=[dict(id='section'+str(i),title='章节 '+str(i),purpose='解释证据',points=['观点与范围'],claim_ids=['C1'] if i==1 else ['C2'] if i==2 else []) for i in range(1,4)]
        issues=[dict(id='issue'+str(i),text='核实问题 '+str(i),kind='blocking',status='open',source_ids=['S1'],claim='模拟问题') for i in range(1,13)]
        issues.append(dict(id='limit1',text='需要保留的边界',kind='limitation',status='open',source_ids=[],claim=''))
        content='## 章节 1\n\n研究只适用于给定条件。 [S1]\n\n## 章节 2\n\n待改写的段落。\n\n## 章节 3\n\n结尾。'
        def fill(v):
            v.update(sources=sources,evidence={'summary':'离线模拟整理结果','claims':claims,'gaps':[]},outline=dict(thesis='依据与边界',reader_question='结论适用吗',takeaway='学会对照依据',counterpoint='可能有替代解释',boundary='仅作界面测试',sections=sections),content=content,research=dict(issues=issues,pending=True,summary='测试核实问题',gaps=[],conflicts=[],stale=False),visual=dict(enabled=True,count=1,size='1024x1024'),image_plans=[dict(id='plan1',role='cover',prompt='本地模拟图片',caption='模拟封面')],images=[dict(id='image1',filename='sample.png',role='article',after_heading='已删除章节',caption='模拟插图',selected=True)],current_stage='sources')
            v['stages'].update(sources='done',outline='done',write='done',visual='done')
            v['auto']={key:False for key in v['auto']}
        a=store.save_article(a['id'],a['revision'],fill,'fixture')
        if case=='flows':
            a=store.save_article(a['id'],a['revision'],lambda v:v['research'].update(pending=False,issues=[]),'fixture')
        assets=store.article_dir(a['id'])/'assets';assets.mkdir(parents=True,exist_ok=True)
        Image.new('RGB',(300,180),'#729656').save(assets/'sample.png')
        if case=='review':
            a=workflow.apply_result(a,'review',dict(decision='revise',summary='模拟审核意见',issues=[dict(id='review1',quote='待改写的段落。',suggestion='修改后的段落。',reason='使表达更清楚',severity='major',status='pending'),dict(id='review2',quote='结尾。',suggestion='完整结尾。',reason='补充表达',severity='minor',status='pending')],dimensions={}),{})
    fixtures[case]=a['id']
(store.DATA/'fixtures.json').write_text(json.dumps(fixtures),encoding='utf-8')
