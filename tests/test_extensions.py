import asyncio
import hashlib
import io
import json
from pathlib import Path
import pytest
from PIL import Image
from backend import extensions,store,account_memory,native_catalog,native_runtime,native_external,providers,rendering,workflow
from tests.test_studio import client,model,new,patch,wait,H


def request(a,action,**extra):
    return dict(action=action,article_id=a['id'],revision=a['revision'],account_revision=account_memory.get()['revision'],client_id=store.uid(),**extra)


def ready(c):
    a=new(c);a=patch(c,a,dict(content='这是一篇用于离线验收的文章，只检验数据流与工具行为。'*15),'write')
    out=io.BytesIO();Image.new('RGB',(40,40),'green').save(out,'PNG')
    response=c.post('/api/articles/'+a['id']+'/images/upload',headers=H,data=dict(revision=a['revision'],role='cover'),files=dict(file=('cover.png',out.getvalue(),'image/png')))
    assert response.status_code==200,response.text
    return response.json()


def connect(c):
    cfg=c.get('/api/extensions').json()
    response=c.put('/api/extensions/wechat',headers=H,json=dict(credential_id=cfg['credential_id'],appid='wx1234567890',secret='synthetic-wechat-secret'))
    assert response.status_code==200,response.text
    return response.json()


def test_custom_persona_full_native_projection_and_conflict(client):
    response=client.post('/api/extensions/personas',headers=H,json=dict(revision=0,id='user-reader',label='读书人',definition=dict(description='从读者问题展开',opening_style='从真实问题开始')))
    assert response.status_code==200,response.text
    assert any(x['id']=='user-reader' for x in client.get('/api/meta').json()['personas'])
    assert client.post('/api/extensions/personas',headers=H,json=dict(revision=0,id='user-reader',label='旧页面')).status_code==409
    with pytest.raises(ValueError):native_catalog.persona('../secrets')
    a=new(client);a['brief']['persona']='user-reader';j=store.create_job(a['id'],dict(stage='write'))
    s=native_runtime.Session(a,j['id'],'write',{});docs=asyncio.run(s.prepare())
    assert any(x['path']=='personas/user-reader.yaml' and '从真实问题开始' in x['content'] for x in docs)
    with pytest.raises(ValueError):s.path('personas/user-reader.yaml',True)


def test_theme_learning_uses_original_styles_no_model_and_adds_option(client,monkeypatch):
    async def fetch(*args):return b'<html><h1 id="activity-name">Example</h1><section id="js_content"><h2 style="color:#445566;font-size:22px">Title</h2><p style="font-size:18px;color:#123456;line-height:1.9">Text</p></section></html>','https://mp.weixin.qq.com/s/example'
    monkeypatch.setattr(extensions.materials,'fetch_bytes',fetch)
    async def no_model(*args):pytest.fail('theme must not call a model')
    monkeypatch.setattr(providers,'generate',no_model)
    value=dict(action='theme',account_revision=0,client_id=store.uid(),name='user-sample',label='学习样式',url='https://mp.weixin.qq.com/s/example')
    j=client.post('/api/extensions/actions',headers=H,json=value);assert j.status_code==200,j.text
    end=wait(client,j.json());assert end['status']=='completed',end
    assert any(x['id']=='user-sample' for x in client.get('/api/meta').json()['themes'])
    assert client.get('/api/themes/user-sample/preview').status_code==200
    value.update(client_id=store.uid(),account_revision=1)
    end=wait(client,client.post('/api/extensions/actions',headers=H,json=value).json())
    assert end['status']=='failed' and len(account_memory.get()['themes'])==1


def test_publish_requires_current_reviewable_preview_and_credentials(client,monkeypatch):
    a=ready(client);preview=extensions.preflight(a,'publish')
    assert not preview['issues'] and preview['cover'] and '/assets/' not in preview['html']
    r=client.post('/api/extensions/actions',headers=H,json=request(a,'publish',preview_hash=preview['preview_hash']))
    assert r.status_code==400 and 'AppID' in r.text
    config=connect(client)
    assert 'synthetic-wechat-secret' not in client.get('/api/extensions').text
    assert b'synthetic-wechat-secret' not in (store.DATA/'studio.sqlite').read_bytes()
    assert client.post('/api/extensions/actions',headers=H,json=request(a,'publish',preview_hash=preview['preview_hash'])).status_code==409
    assert client.put('/api/extensions/wechat',headers=H,json=dict(credential_id='old',remove=True)).status_code==409
    assert config['configured']


@pytest.mark.parametrize('action',['publish','image_post'])
def test_draft_receipt_idempotency_source_unchanged_and_no_model(client,monkeypatch,action):
    a=ready(client);connect(client);calls=[]
    async def fake(session,value,prepared):
        calls.append((value['action'],prepared));assert session.state['permissions']['publish'] is True
        assert session.state['flags']['skip_publish'] is False
        return dict(media_id='synthetic-media')
    monkeypatch.setattr(extensions,'external',fake)
    check=extensions.preflight(a,action);value=request(a,action,preview_hash=check['preview_hash'])
    started=client.post('/api/extensions/actions',headers=H,json=value);assert started.status_code==200,started.text
    end=wait(client,started.json());assert end['status']=='completed',end
    assert end['result']['media_id']=='synthetic-media'
    after=store.get_article(a['id']);assert after['content']==a['content'] and after['extensions'][0]['action']==action
    assert not store.usage(a['id'])
    again=client.post('/api/extensions/actions',headers=H,json=value)
    assert again.status_code==200 and again.json()['id']==started.json()['id'] and len(calls)==1


def test_rewrite_and_effect_review_have_real_artifacts_and_preserve_source(client,model):
    a=new(client);a=patch(client,a,dict(content='现有原稿，任何扩展都不能覆盖它。'),'write')
    for action in ('rewrite','stats_review'):
        start=client.post('/api/extensions/actions',headers=H,json=request(a,action));assert start.status_code==200,start.text
        end=wait(client,start.json());assert end['status'] in ('completed','needs_input'),end
        if action=='rewrite':
            assert len(end['result']['outputs'])==2 and isinstance(end['result']['max_similarity'],float)
            reads=end['native']['reads'];assert sum('/platforms/' in x['path'] for x in reads)==2
            assert client.get('/api/jobs/'+end['id']+'/native-artifacts/source.md').json()['content'].endswith(a['content'])
        else:assert end['result']['content']
        a=store.get_article(a['id']);assert a['content']=='现有原稿，任何扩展都不能覆盖它。'


def test_stats_matches_explicit_msgid_and_keeps_unknown(client):
    a=new(client);b=new(client)
    response=client.post('/api/extensions/bindings',headers=H,json=dict(revision=0,article_id=a['id'],msgid='123_1'))
    assert response.status_code==200,response.text
    assert client.post('/api/extensions/bindings',headers=H,json=dict(revision=1,article_id=b['id'],msgid='123_1')).status_code==400
    rows=[dict(msgid='123_1',title='同名',ref_date='2026-01-01',details=[dict(stat_date='2026-01-02',int_page_read_count=100)]),dict(msgid='999_1',title=a['title'],details=[])]
    result=extensions.project_stats(dict(date='2026-01-01',account_revision=1),rows)
    assert result['matched']==1 and result['unmatched'][0]['msgid']=='999_1'
    record=account_memory.get()['online_metrics'][0]
    assert record['stats']==dict(read_count=100,share_count=None,like_count=None)
    s=native_runtime.Session(a,store.create_job(a['id'],dict(stage='stats'))['id'],'stats',{})
    asyncio.run(s.prepare())
    assert 'read_count: 100' in (s.home/'history.yaml').read_text('utf-8')


def test_external_worker_uses_upstream_functions_and_never_leaks_token(client,monkeypatch,tmp_path):
    import requests
    a=ready(client);cfg=connect(client);home=tmp_path/'external';home.mkdir();(home/'publish.html').write_text('<section>正文</section>','utf-8');(home/'cover.png').write_bytes(b'fake')
    job=store.create_job(a['id'],dict(stage='publish'));store.update_job(job['id'],status='running')
    packet=dict(home=str(home),job_id=job['id'],database=str(store.DATA/'studio.sqlite'),article_id=a['id'],revision=a['revision'],account_revision=0,credential_id=cfg['credential_id'],action='publish',appid='wx1234567890',secret='synthetic-wechat-secret',title=a['title'],digest='',cover='cover.png',image_map={})
    calls=[]
    class Response:
        status_code=200
        def __init__(self,data):self.data=data
        def json(self):return self.data
    def send(url,**kwargs):
        calls.append(url);assert kwargs['allow_redirects'] is False
        if url.endswith('/token'):return Response(dict(access_token='never-log-token',expires_in=7200))
        return Response(dict(media_id='created-id'))
    monkeypatch.setattr(requests,'get',send);monkeypatch.setattr(requests,'post',send)
    result=native_external.execute(packet);assert result['status']=='completed' and result['result']['media_id']=='created-id'
    assert calls[-1].endswith('/draft/add')
    receipt=(home/'external-receipt.json').read_text('utf-8')
    assert 'never-log-token' not in receipt and 'synthetic-wechat-secret' not in receipt
    (home/'cancel-requested').write_text('cancel','utf-8');assert native_external.execute(packet)['status']=='cancelled'


def test_cancel_external_waits_for_receipt_instead_of_killing_task(client,tmp_path):
    a=new(client);job=store.create_job(a['id'],dict(stage='publish'));home=store.DATA/'native'/store.uid();home.mkdir(parents=True)
    store.update_job(job['id'],status='running',external_inflight=True,external_home=str(home))
    result=workflow.cancel(job['id']);assert result['status']=='running' and result['cancel_requested'] and (home/'cancel-requested').exists()


def test_restart_recovers_receipt_that_arrives_after_parent_exit(client):
    a=new(client);job=store.create_job(a['id'],dict(stage='publish'));home=store.DATA/'native'/store.uid();home.mkdir(parents=True)
    store.update_job(job['id'],status='running',external_inflight=True,external_home=str(home))
    (home/'external-receipt.json').write_text(json.dumps(dict(requests=[dict(endpoint='/cgi-bin/draft/add',status='sent')],result=None)),'utf-8')
    store.init();assert store.job(job['id'])['status']=='interrupted'
    (home/'external-receipt.json').write_text(json.dumps(dict(requests=[],result=dict(media_id='late-receipt'))),'utf-8')
    assert store.job(job['id'])['result']['media_id']=='late-receipt'
    assert store.jobs(a['id'])[0]['result']['media_id']=='late-receipt'
    assert store.get_article(a['id'])['content']==a['content']
