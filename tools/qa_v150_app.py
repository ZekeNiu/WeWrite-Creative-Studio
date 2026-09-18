"""Isolated offline visual UI fixtures. All model outputs here are simulated."""
import os
import io
import json
from pathlib import Path
os.environ['WEWRITE_STUDIO_DATA']=str(Path('output/test-workspaces/qa-v150').resolve())
from PIL import Image
from fastapi.staticfiles import StaticFiles
from backend.app import app
from backend import store,providers,visuals
from backend.models import Settings,ImagePlan
store.init()
providers.save_settings(Settings.model_validate(dict(services=[dict(id='fixture',name='模拟服务',model='fixture',key='offline-fixture-key',input_price=.1,output_price=.1,image_price=1)],default_service='fixture',search={'enabled':False})))
s=providers.service_for('vision');store.capability(providers.fingerprint(s,'vision'),dict(status='tested',message='离线模拟，仅供界面验收'))
app.router.routes=[r for r in app.router.routes if getattr(r,'name','')!='frontend']
app.mount('/',StaticFiles(directory='output/test-workspaces/v150-ui-dist',html=True),name='frontend')


async def generate(s,system,prompt,emit=None,images=None):
    v=json.loads(prompt)
    if images:result=dict(images=[dict(id=x['id'],suitable=True,reason='离线模拟检查') for x in v['images']])
    else:result=dict(images=[dict(id='cover',role='cover',prompt='Natural scene',purpose='表现自然训练环境'),dict(id='action',role='article',prompt='',method='search',image_type='action',purpose='说明正确动作',after_heading='动作说明',query='真实动作')])
    return json.dumps(result,ensure_ascii=False),dict(status='completed',estimated_cost=.001,model=s['model'],currency='CNY')


async def image(*args,**kw):
    b=io.BytesIO();Image.new('RGB',(800,500),'#63846c').save(b,'PNG');return b.getvalue()
providers.generate=generate;providers.image_generate=image
if not (store.DATA/'fixture.json').exists():
    a=store.create_article({'topic':'配图交互验收'},diagnostic=True)
    a=store.save_article(a['id'],0,lambda v:v.update(content='## 训练场景\n\n自然的运动环境。\n\n## 动作说明\n\n示范只适用于对应的动作和人群。',current_stage='visual',visual=dict(enabled=True,count=2,size='1536x1024',budget=5)),'Offline fixture')
    plans=[ImagePlan(id='cover',role='cover',prompt='Natural scene',purpose='表现自然训练环境').model_dump(),ImagePlan(id='action',role='article',prompt='',method='search',image_type='action',purpose='说明正确动作',after_heading='动作说明',query='真实动作').model_dump()]
    plans=visuals.normalize_plans(a,plans)
    items=[]
    for i,color in enumerate(('#63846c','#9c8061','#517283')):
        b=io.BytesIO();Image.new('RGB',(800,500),color).save(b,'PNG');filename,hashvalue=visuals.save_blob(a,b.getvalue());plan=plans[0 if i==0 else 1]
        items.append(dict(plan,id=store.uid(),plan_id=plan['id'],filename=filename,file_hash=hashvalue,selected=i==0,origin='generated' if i==0 else 'web',
            check=dict(status='passed',reason='离线模拟图，只用于检查页面交互'),source_url='https://example.org/fixture',original_caption='模拟来源图注',rights=dict(status='unknown'),crop_x=.5,crop_y=.5))
    a=store.save_article(a['id'],a['revision'],lambda v:v.update(image_plans=plans,images=items),'Offline pictures')
    (store.DATA/'fixture.json').write_text(json.dumps({'article_id':a['id']}),'utf-8')
