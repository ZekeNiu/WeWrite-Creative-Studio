import io
from PIL import Image
from backend import providers,capabilities
from backend.models import Settings
from tests.test_research import client,network,H


def test_each_model_can_test_image_without_changing_routes(client,monkeypatch):
    blob=io.BytesIO();Image.new('RGB',(16,16)).save(blob,'PNG');seen=[]
    async def image(s,*args): seen.append(s['model']);return blob.getvalue()
    monkeypatch.setattr(providers,'image_generate',image)
    before=providers.settings()
    r=client.post('/api/services/s/capability-tests',headers=H,json={'model':'another-image','kind':'image'})
    assert r.status_code==200 and seen==['another-image']
    after=providers.settings()
    assert before['routes']==after['routes'] and before['search']==after['search'] and before['services']==after['services']
    assert client.get(r.json()['image_url']).status_code==200
    assert after['route_capabilities']['image']['status']=='untested'


def test_cards_deduplicate_and_keep_override_models(client):
    cards=providers.settings()['model_capabilities']
    assert {c['model'] for c in cards}=={'text','image','analysis','search'}
    assert len(cards)==4
    assert 'research' in next(c for c in cards if c['model']=='analysis')['roles']


def test_search_profile_separate_from_text_and_failures_persist(client,monkeypatch):
    cfg=Settings.model_validate(providers.settings())
    cfg.model_connections=[dict(service_id='s',model='text',search_protocol='gemini')]
    providers.save_settings(Settings.model_validate(cfg.model_dump()))
    before=providers.settings();seen=[]
    async def fail(s,*args): seen.append((s['model'],s['protocol']));raise ValueError('服务暂时不可用')
    monkeypatch.setattr(capabilities.search_tools,'native',fail)
    r=client.post('/api/services/s/capability-tests',headers=H,json={'model':'text','kind':'search'})
    assert r.status_code==400 and seen==[('text','gemini')]
    after=providers.settings()
    card=next(c for c in after['model_capabilities'] if c['model']=='text')
    assert card['capabilities']['search']['status']=='failed' and card['capabilities']['search']['at']
    assert before['services']==after['services'] and before['search']==after['search']
    cfg=Settings.model_validate(after);cfg.services[0].key='changed-fixture-secret'
    changed=providers.save_settings(cfg)
    assert next(c for c in changed['model_capabilities'] if c['model']=='text')['capabilities']['search']['status']=='untested'


def test_unconfigured_chat_search_does_not_send_request_and_explains(client,monkeypatch):
    cfg=Settings.model_validate(providers.settings());cfg.services[0].protocol='chat'
    cfg.model_connections=[dict(service_id='s',model='text',search_protocol='inherit')]
    providers.save_settings(Settings.model_validate(cfg.model_dump()))
    async def forbidden(*args):raise AssertionError('Must not send a search request')
    monkeypatch.setattr(capabilities.search_tools,'native',forbidden)
    r=client.post('/api/services/s/capability-tests',headers=H,json={'model':'text','kind':'search'})
    assert r.status_code==200
    assert r.json()['request_sent'] is False and '尚未发送' in r.json()['message']


def test_capability_error_retains_http_details_and_routes(client,monkeypatch):
    from backend.service_errors import http_failure,bind
    before=providers.settings()
    async def rejected(s,*args):raise bind(http_failure(400,'{"error":{"code":"unsupported_tool"}}'),s)
    monkeypatch.setattr(capabilities.search_tools,'native',rejected)
    r=client.post('/api/services/s/capability-tests',headers=H,json={'model':'deepseek-flash','kind':'search','protocol':'anthropic'})
    assert r.status_code==400 and r.json()['failure']['http_status']==400
    from backend import store
    service=capabilities.resolve(before,'s','deepseek-flash','search','anthropic')
    saved=store.capability(providers.fingerprint(service,'search'))
    assert saved['failure']['provider_code']=='unsupported_tool' and saved['response_received']
    after=providers.settings()
    assert after['routes']==before['routes'] and after['search']==before['search']


def test_optional_research_propagates_paid_service_failure(client,monkeypatch):
    import asyncio
    import pytest
    from backend import store,research
    from backend.service_errors import http_failure,ServiceFailure
    a=store.create_article({'topic':'模拟研究'});j=store.create_job(a['id'],{'stage':'research'})
    w=research.Research(a,j['id'],'sources');seen=[]
    async def unavailable(*args):seen.append('native');raise http_failure(503)
    monkeypatch.setattr(capabilities.search_tools,'native',unavailable)
    with pytest.raises(ServiceFailure):asyncio.run(w.channel('native','synthetic question'))
    assert seen==['native'] and store.job(j['id'])['execution_usage']['requests']==1
