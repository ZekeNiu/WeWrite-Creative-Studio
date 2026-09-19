"""Isolated, offline fixtures for the five editorial improvements."""
import asyncio
import io
import json
import os
from pathlib import Path

os.environ['WEWRITE_STUDIO_DATA']=str(Path('output/test-workspaces/qa-optimizations').resolve())
from backend.app import app
from backend import store, providers, materials, workflow
from backend.models import Settings
from PIL import Image

store.init()
providers.save_settings(Settings.model_validate(dict(services=[dict(id='offline',name='离线验收',model='fixture',key='offline-fixture')],
    default_service='offline',search={'enabled':False})))


async def generate(s,system,prompt,emit=None):
    await asyncio.sleep(3)
    value=json.loads(prompt)
    if value.get('schema',{}).get('title')=='ReviewResult':
        content=value['资料与当前内容']['article']
        rows=[dict(id='i1',quote='原文甲。',suggestion='修改甲。',reason='建议明确表达',severity='major'),
              dict(id='i2',quote='原文乙。',suggestion='修改乙。',reason='可调整措辞',severity='minor')]
        raw=json.dumps(dict(decision='revise',summary='请逐项核对建议。',issues=[x for x in rows if x['quote'] in content],dimensions={'准确':4,'深度':3,'naturalness':4}),ensure_ascii=False)
    else: raw='建议保留小标题，缩短过长段落，并将配图放在对应章节。'
    if emit: await emit(raw)
    return raw,dict(status='completed',model=s['model'],input_tokens=100,output_tokens=80)


async def image(*args):
    blob=io.BytesIO();Image.new('RGB',(256,256),'#426b59').save(blob,'PNG');return blob.getvalue()


providers.generate=generate
providers.image_generate=image
fixtures={}
for case in ('review','editor','empty'):
    a=store.create_article({'topic':'五项优化验收 · '+case})
    book=materials.source('训练科学','研究仅适用于成年受试者。')
    book['bibliography']=dict(title='训练科学',document_type='M',authors=['张三'],year='2024',publisher='科学出版社',publication_place='北京',version='第2版')
    book['evidence_spans']=[dict(source_id=book['id'],quote=book['text'],claim='仅限成人',boundary='不能外推至儿童',location='第 30 页',source_type='专业书籍',adoption_reason='本章对应实验',use_scope='成人',quality='limited')]
    a=store.save_article(a['id'],a['revision'],lambda v:v.update(content='原文甲。\n\n原文乙。\n\n独立段落。',sources=[book],visual={'enabled':True,'count':1,'size':'1024x1024'},
        image_plans=[dict(id='cover',role='cover',prompt='测试配图',caption='示意图')]),'fixture')
    j=store.create_job(a['id'],{'stage':'review','revision':a['revision'],'chain':False})
    result=dict(decision='revise',summary='请逐项核对建议。',issues=[dict(id='i1',quote='原文甲。',suggestion='修改甲。',reason='建议明确表达',severity='major',status='pending'),
        dict(id='i2',quote='原文乙。',suggestion='修改乙。',reason='可调整措辞',severity='minor',status='pending')],dimensions={'准确':4,'深度':3,'naturalness':4})
    a=workflow.apply_result(a,'review',result,{'_job_id':j['id']})
    store.update_job(j['id'],status='needs_input',current_step='generation',generation_revision=a['review']['content_revision'],review_round_id=a['review']['round_id'],message='需要你确认当前结果')
    if case=='empty':
        a=store.save_article(a['id'],a['revision'],lambda v:v['review'].update(dimensions={},tool_hints={}), 'fixture')
    store.add_usage(a['id'],stage='review',model='fixture',input_tokens=100,output_tokens=80,status='completed',estimated_cost=5,currency='CNY')
    fixtures[case]=a['id']
(store.DATA/'fixtures.json').write_text(json.dumps(fixtures),encoding='utf-8')
