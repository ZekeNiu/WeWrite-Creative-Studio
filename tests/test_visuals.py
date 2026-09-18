"""Offline visual workflow regressions. No paid calls or production data."""
import asyncio
import base64
import io
import json
import zipfile
import httpx
import pytest
from PIL import Image
from backend import store,providers,visuals,workflow,rendering,materials,capabilities
from backend.models import Settings,ImagePlan,JobRequest
from tests.test_studio import client,new,patch,wait,H


def picture(color='green'):
    out=io.BytesIO();Image.new('RGB',(800,500),color).save(out,'PNG');return out.getvalue()


@pytest.fixture
def visual(client,monkeypatch):
    providers.save_settings(Settings.model_validate(dict(services=[dict(id='v',name='Fixture',model='vision-fixture',key='offline-key',input_price=.1,output_price=.1,image_price=1,search_price=.1)],default_service='v',search=dict(enabled=False))))
    s=providers.service_for('vision');store.capability(providers.fingerprint(s,'vision'),dict(status='tested',message='offline fixture only'))
    async def generate(s,system,prompt,emit=None,images=None):
        data=json.loads(prompt)
        assert images and len(images)==len(data['images']) and all(Image.open(io.BytesIO(b)).format=='PNG' for b in images)
        return json.dumps(dict(images=[dict(id=i['id'],suitable=True,reason='Offline fixture') for i in data['images']])),dict(status='completed',estimated_cost=.001,model=s['model'],currency='CNY')
    async def image(*args,**kwargs):return picture()
    monkeypatch.setattr(providers,'generate',generate);monkeypatch.setattr(providers,'image_generate',image)
    a=new(client)
    return patch(client,a,dict(content='## 跑步场景\n\n轻松跑的真实场景，不展示错误动作。\n\n## 解剖说明\n\n示意图不能替代临床判断。',visual=dict(enabled=True,count=2,size='1536x1024',budget=5),image_plans=[dict(id='cover',role='cover',prompt='Natural running scene',purpose='展示训练环境'),dict(id='body',role='article',prompt='',method='search',image_type='anatomy',after_heading='解剖说明',query='anatomy diagram')]),'write')


def job(a,stage='image',plan='cover',**extra):
    return store.create_job(a['id'],dict(stage=stage,revision=a['revision'],image_id=plan,chain=False,**extra))


def test_legacy_plan_and_professional_method(visual):
    assert ImagePlan(id='x',role='article',prompt='old').method=='generate'
    rows=visuals.normalize_plans(visual,[dict(id='b',role='article',prompt='',image_type='anatomy',method='generate',after_heading='解剖说明'),dict(id='c',role='cover',prompt='cover')])
    assert rows[0]['role']=='cover' and rows[1]['method']=='search'
    with pytest.raises(ValueError,match='封面'):visuals.normalize_plans(visual,[dict(id='b',role='article',prompt='')])


def test_existing_cover_preserved_in_plan(visual):
    visual['images']=[dict(id='old',role='cover',selected=True)]
    rows=visuals.normalize_plans(visual,[dict(id='c',role='cover',prompt=''),dict(id='b',role='article',prompt='',after_heading='解剖说明')])
    assert len(rows)==1 and rows[0]['id']=='b'


def test_paid_artifact_check_reuse_and_budget(visual):
    j=job(visual)
    a=asyncio.run(visuals.acquire(visual,j['id'],visual['image_plans'][0]))
    assert a['images'][0]['selected'] and a['images'][0]['check']['status']=='passed'
    assert visuals.budget(a)['known']==pytest.approx(1.001)
    before=len(store.usage(a['id']));store.update_job(j['id'],status='completed');j2=job(a)
    assert asyncio.run(visuals.acquire(a,j2['id'],a['image_plans'][0]))['revision']==a['revision']
    assert len(store.usage(a['id']))==before


def test_image_cancel_during_check_keeps_file(visual,monkeypatch):
    async def cancel(*args,**kwargs):raise asyncio.CancelledError()
    monkeypatch.setattr(providers,'generate',cancel)
    with pytest.raises(asyncio.CancelledError):asyncio.run(visuals.acquire(visual,job(visual)['id'],visual['image_plans'][0]))
    a=store.get_article(visual['id']);assert len(a['images'])==1 and not a['images'][0]['selected']
    assert (store.article_dir(a['id'])/'assets'/a['images'][0]['filename']).exists()
    assert any(u['stage']=='vision' and u['status']=='unknown' for u in store.usage(a['id']))


def test_unknown_vision_price_does_not_call_or_adopt(visual,monkeypatch):
    cfg=store.get_settings();cfg['services'][0]['input_price']=None;store.set_settings(cfg)
    calls=[]
    async def forbidden(*args,**kwargs):calls.append(1);raise AssertionError('must not call')
    monkeypatch.setattr(providers,'generate',forbidden)
    a=asyncio.run(visuals.acquire(visual,job(visual)['id'],visual['image_plans'][0]))
    assert not calls and not a['images'][0]['selected']
    assert '未知' in a['images'][0]['check']['reason']


def test_rejected_picture_not_selected(visual,monkeypatch):
    async def reject(s,system,prompt,**kw):
        return json.dumps(dict(images=[dict(id=x['id'],suitable=False,reason='错误动作') for x in json.loads(prompt)['images']])),dict(status='completed',estimated_cost=.001)
    monkeypatch.setattr(providers,'generate',reject)
    a=asyncio.run(visuals.acquire(visual,job(visual)['id'],visual['image_plans'][0]))
    assert not a['images'][0]['selected'] and a['images'][0]['check']['status']=='rejected'


def test_unknown_generation_is_reserved_and_not_replayed(visual,monkeypatch):
    calls=[]
    async def fail(*args):calls.append(1);raise ValueError('unknown paid result')
    monkeypatch.setattr(providers,'image_generate',fail);j=job(visual)
    with pytest.raises(ValueError):asyncio.run(visuals.acquire(visual,j['id'],visual['image_plans'][0]))
    with pytest.raises(ValueError,match='结果未知'):asyncio.run(visuals.acquire(visual,j['id'],visual['image_plans'][0]))
    assert calls==[1] and visuals.budget(visual)['reserved']==1


def test_stale_plan_and_removed_anchor(visual,client):
    a=patch(client,visual,dict(content=visual['content'].replace('解剖说明','新的章节')),'write')
    with pytest.raises(ValueError,match='定位'):asyncio.run(visuals.acquire(a,job(a)['id'],a['image_plans'][1]))
    assert not store.usage(a['id'])


def test_caption_and_context_are_part_of_check_cache(visual,monkeypatch):
    j=job(visual);a=asyncio.run(visuals.acquire(visual,j['id'],visual['image_plans'][0]));item=a['images'][0]
    n=len(store.usage(a['id']));asyncio.run(visuals.check(a,j['id'],[item]));assert len(store.usage(a['id']))==n
    item['caption']='Changed claim';asyncio.run(visuals.check(a,j['id'],[item]));assert len(store.usage(a['id']))==n+1


def test_candidates_bounded_excluded_sources_and_permission(visual,monkeypatch,client):
    cfg=store.get_settings();cfg['search'].update(enabled=True,browser_enabled=True,allow_fallback=True);store.set_settings(cfg)
    a=patch(client,visual,{'image_plans':[visual['image_plans'][1]]})
    pages=[];queries=[]
    async def search(*args):queries.append(1);return [dict(url='https://example.org/'+str(i)) for i in range(8)],'fixture'
    async def page(url):
        pages.append(url)
        return [dict(source_url=url,original_url=url+'/'+str(i)+'.png',rights=dict(status='unknown')) for i in range(8)]
    async def fetch(url,**kw):return picture(['red','green','blue'][int(url.split('/')[-1][0])%3]),url
    monkeypatch.setattr(visuals,'search_pages',search);monkeypatch.setattr(visuals,'page_candidates',page);monkeypatch.setattr(materials,'fetch_bytes',fetch)
    a=asyncio.run(visuals.acquire(a,job(a,plan='body')['id'],a['image_plans'][0]))
    assert len(queries)==1 and len(pages)<=2 and len(a['images'])==3
    assert not any(i['selected'] for i in a['images']) and all(i['check']['status']=='passed' for i in a['images'])
    image=a['images'][0]
    response=client.patch('/api/articles/'+a['id'],headers=H,json=dict(revision=a['revision'],stage='visual',changes=dict(images=[{**i,'selected':i['id']==image['id']} for i in a['images']])))
    assert response.status_code==400
    a=patch(client,a,dict(images=[{**i,'selected':i['id']==image['id'],'rights_basis':'Fixture explicit permission'} for i in a['images']]),'visual')
    assert a['images'][0]['rights']['status']=='confirmed'


def test_extract_real_img_links_not_model_urls():
    rows=visuals.extract_candidates(b'<article><img src="/logo.png" alt="logo"><figure><img src="/motion.jpg"><figcaption>Actual movement</figcaption></figure><img src="data:a"></article>','https://example.org/page')
    assert len(rows)==1 and rows[0]['original_url']=='https://example.org/motion.jpg'
    assert rows[0]['original_caption']=='Actual movement' and rows[0]['rights']['status']=='unknown'


def test_cover_crop_export_and_provenance(visual):
    a=asyncio.run(visuals.acquire(visual,job(visual)['id'],visual['image_plans'][0]))
    z=zipfile.ZipFile(io.BytesIO(rendering.export_zip(a)))
    cover=Image.open(io.BytesIO(z.read('封面.png')))
    assert abs(cover.width/cover.height-2.35)<.02
    im=a['images'][0]
    assert z.read('images/'+im['filename'])==z.read('封面.png')
    assert Image.open(io.BytesIO(z.read('original-images/'+im['filename']))).size==(800,500)
    assert 'AI 生成' in z.read('文章.md').decode() and '图片来源清单.json' in z.namelist()


def test_two_covers_upload_and_history_restore(visual,client):
    a=visual
    for color in ('red','green'):
        r=client.post('/api/articles/'+a['id']+'/images/upload',headers=H,data=dict(revision=a['revision'],role='cover'),files={'file':('x.png',picture(color))});assert r.status_code==200;a=r.json()
    assert sum(i['selected'] for i in a['images'])==1
    assert a['images'][-1]['selected']
    old=store.versions(a['id'])[0];restored=store.restore(a['id'],old['id'],a['revision']);assert len(restored['images'])==1


def test_missing_heading_blocks_export_and_not_appended(visual):
    a=asyncio.run(visuals.acquire(visual,job(visual)['id'],visual['image_plans'][0]))
    a['images'][0].update(role='article',after_heading='不存在')
    assert '/assets/' not in rendering.markdown(a)
    with pytest.raises(ValueError,match='定位'):rendering.export_zip(a)


def test_duplicate_job_key_before_revision_conflict(visual,client,monkeypatch):
    async def acquire(a,*args):return a
    monkeypatch.setattr(visuals,'acquire',acquire)
    payload=dict(stage='image',revision=visual['revision'],image_id='cover',action_id='one-click',chain=False)
    r=client.post('/api/articles/'+visual['id']+'/jobs',headers=H,json=payload);assert r.status_code==200
    j=wait(client,r.json());a=patch(client,visual,dict(title='changed'))
    again=client.post('/api/articles/'+a['id']+'/jobs',headers=H,json=payload)
    assert again.status_code==200 and again.json()['id']==j['id']


@pytest.mark.parametrize('protocol',['chat','responses','anthropic'])
def test_actual_image_bytes_in_protocol(client,monkeypatch,protocol):
    seen=[]
    class Client:
        def __init__(self,*args,**kw):self.inner=httpx.AsyncClient(transport=httpx.MockTransport(self.handle))
        def handle(self,r):
            seen.append(json.loads(r.content));return httpx.Response(200,json={'choices':[{'message':{'content':'ok'}}],'content':[{'type':'text','text':'ok'}],'output_text':'ok','usage':{}})
        async def __aenter__(self):return self.inner
        async def __aexit__(self,*args):await self.inner.aclose()
    original=httpx.AsyncClient
    class SafeClient(Client):
        def __init__(self,*args,**kw):self.inner=original(transport=httpx.MockTransport(self.handle))
    monkeypatch.setattr(providers.httpx,'AsyncClient',SafeClient)
    s=dict(protocol=protocol,model='fixture',name='Fixture',secret='fixture',base_url='https://example.org')
    asyncio.run(providers.generate(s,'system','prompt',images=[picture()]))
    serialized=json.dumps(seen[0]);assert base64.b64encode(picture()).decode() in serialized
    assert {'chat':'image_url','responses':'input_image','anthropic':'media_type'}[protocol] in serialized
