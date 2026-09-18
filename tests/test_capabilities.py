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
