"""Isolated editorial-theme fixture; all generation is simulated locally."""
import asyncio
import json
import os
from pathlib import Path
os.environ['WEWRITE_STUDIO_DATA']=str(Path('output/test-workspaces/qa-editorial').resolve())
from backend.app import app
from backend import store,providers,materials,editorial_themes,workflow
from backend.models import Settings
from PIL import Image,ImageDraw

store.init()
providers.save_settings(Settings.model_validate(dict(services=[dict(id='offline',name='离线验收',model='fixture',key='offline-fixture')],default_service='offline',search={'enabled':False})))


async def generate(service,system,prompt,emit=None):
    await asyncio.sleep(1)
    value=json.loads(prompt)
    assert set(value['资料与当前内容'])=={'title','article','images'}
    text='1. “为下一段留下空间”一节可以保留现有分段，让表格之前的解释更容易阅读。'
    if emit: await emit(text)
    return text,dict(status='completed',model='fixture',input_tokens=100,output_tokens=40)


providers.generate=generate
fixtures={}
for case in ('layout','editor','plain'):
    a=store.create_article({'topic':'让知识，有一种好读的样子'})
    source=materials.source('阅读设计 · 测试书目','这是用于界面验收的模拟来源，不是事实依据。')
    source['bibliography']=dict(title='阅读设计 · 测试书目',document_type='M',authors=['测试作者'],year='2025',publisher='测试出版社',publication_place='北京')
    content=editorial_themes.SAMPLE+'\n\n## 03 已有编号的章节\n\n这是用于检验引用编号的示例文字 ['+source['id']+']。\n\n```python\nprint("示例代码与原文一起保留")\n```'
    if case=='plain': content='没有小标题的文章也应当保留自然的段落。\n\n'+'很长的中文文字用于检查换行。'*20+'\n\nhttps://example.org/'+('longpath'*30)
    image=Image.new('RGB',(900,480),'#edece4');draw=ImageDraw.Draw(image)
    draw.rectangle((70,70,830,410),fill='#dce4d8');draw.ellipse((310,95,590,375),fill='#668274');draw.line((120,370,780,110),fill='#f8f8ee',width=8)
    assets=store.article_dir(a['id'])/'assets';assets.mkdir(parents=True,exist_ok=True)
    image.save(assets/'sample.png')
    a=store.save_article(a['id'],a['revision'],lambda v:v.update(content=content,sources=[source],
        layout={**v['layout'],'author':'测试署名'},images=[dict(id='sample',filename='sample.png',role='article',after_heading='让观点有清晰的层次',caption='抽象图形 · 仅用于排版验收',selected=True)]),'fixture')
    a=workflow.apply_result(a,'review',dict(decision='pass',summary='模拟通过',issues=[],dimensions={}),{})
    a=store.save_article(a['id'],a['revision'],lambda v:v.update(current_stage='write' if case=='editor' else 'layout'),'fixture')
    fixtures[case]=a['id']
(store.DATA/'fixtures.json').write_text(json.dumps(fixtures),encoding='utf-8')
