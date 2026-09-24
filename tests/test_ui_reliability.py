import json
import httpx
import pytest
from fastapi.testclient import TestClient
from backend import store, models, workflow, providers, agent_transport
from backend.app import app


def test_service_errors_are_actionable_without_echoing_secrets():
    from backend.service_errors import http_failure
    rate=http_failure(429,json.dumps({'error':{'code':'rate_limit_exceeded','message':'secret-body'}}),{'Retry-After':'30','x-request-id':'req-123'})
    quota=http_failure(429,json.dumps({'error':{'code':'insufficient_quota'}}))
    assert rate.details['category']=='rate_limit' and rate.details['retry_after_seconds']==30
    assert quota.details['category']=='quota' and '稍后' not in str(quota)
    assert 'secret-body' not in json.dumps(rate.details)
    assert rate.details['request_id']=='req-123'
    assert http_failure(401).details['category']=='authentication'
    assert http_failure(403).details['category']=='permission'
    assert http_failure(429).details['category']=='rate_limit_or_quota'


def test_input_drafts_do_not_adopt_or_invalidate_content():
    a=store.create_article(models.Brief(topic='已采用主题').model_dump())
    a=store.save_article(a['id'],a['revision'],lambda v:v.update(content='已有正文',stages={s:'done' for s in models.STAGES}),'fixture')
    client=TestClient(app)
    r=client.patch('/api/articles/'+a['id'],json=dict(revision=a['revision'],stage='preferences',changes={'input_drafts':{'topic':'未采用主题','topic_feedback':'新要求','source_query':'新检索'}}),headers={'X-Studio-Request':'1'})
    assert r.status_code==200
    saved=store.get_article(a['id'])
    assert saved['input_drafts']['topic']=='未采用主题'
    assert saved['brief']['topic']=='已采用主题' and saved['content']=='已有正文'
    assert saved['stages']['write']=='done'
    bad=client.patch('/api/articles/'+a['id'],json=dict(revision=saved['revision'],stage='preferences',changes={'input_drafts':{'unexpected':'x'}}),headers={'X-Studio-Request':'1'})
    assert bad.status_code==400


def test_old_article_feedback_does_not_create_a_blank_topic_draft():
    a=store.create_article(models.Brief(topic='原有主题').model_dump())
    r=TestClient(app).patch('/api/articles/'+a['id'],headers={'X-Studio-Request':'1'},json=dict(revision=a['revision'],stage='preferences',changes={'input_drafts':{'topic_feedback':'补充要求'}}))
    assert r.status_code==200
    assert r.json()['input_drafts']=={'topic_feedback':'补充要求'}
    assert r.json()['brief']['topic']=='原有主题'


def test_retry_uses_failed_stage_and_only_relevant_parameters():
    from backend.flow_state import retry_request
    job=dict(stage='outline',request=dict(stage='topic',instruction='仅用于选题',selected_text='旧选段',image_id='old',chain=True,execution_limits={'max_requests':10}))
    request=retry_request(job,8)
    assert request['stage']=='outline' and request['revision']==8 and request['chain']
    assert not request.get('instruction') and not request.get('selected_text') and not request.get('image_id')
    assert 'execution_limits' not in request


def test_library_reports_actual_words_and_latest_task():
    a=store.create_article(models.Brief().model_dump())
    store.save_article(a['id'],a['revision'],lambda v:v.update(content='真实 字数'),'fixture')
    j=store.create_job(a['id'],dict(stage='topic'))
    store.update_job(j['id'],status='failed',message='模型超时')
    item=store.list_articles(page=1)['items'][0]
    assert item['word_count']==4
    assert item['latest_job']['status']=='failed'


@pytest.fixture
def anyio_backend():return 'asyncio'


@pytest.mark.anyio
async def test_transport_preserves_timeout_category(monkeypatch):
    from backend.service_errors import ServiceFailure
    original=httpx.AsyncClient
    def timeout(request):raise httpx.ReadTimeout('sensitive detail',request=request)
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(timeout),**kw))
    with pytest.raises(ServiceFailure) as info:
        await agent_transport.turn(dict(protocol='chat',base_url='https://example.com',model='fake',secret='not-for-logs'),'system',[],[])
    assert info.value.details['category']=='timeout'
    assert 'sensitive' not in str(info.value)


@pytest.mark.anyio
async def test_workflow_saves_failure_and_stage_identity(monkeypatch):
    from backend.service_errors import http_failure
    a=store.create_article(models.Brief().model_dump())
    request=models.JobRequest(stage='topic',revision=a['revision'],chain=False)
    j=store.create_job(a['id'],request.model_dump())
    async def fail(*args):raise http_failure(429,'{"error":{"code":"insufficient_quota"}}')
    monkeypatch.setattr(workflow.native_runtime,'generate',fail)
    await workflow.run(j['id'])
    saved=store.job(j['id'])
    assert saved['failure']['category']=='quota' and saved['failure']['stage']=='topic'
    assert saved['status']=='failed' and store.get_article(a['id'])['stages']['topic']=='idle'


@pytest.mark.anyio
@pytest.mark.parametrize('adapter',['native','text','image','search','gemini'])
async def test_all_paid_adapters_preserve_safe_provider_diagnostics(monkeypatch,adapter):
    from backend import search_tools
    from backend.service_errors import ServiceFailure
    service=dict(id='fixture',name='Fixture',model='fake',protocol='responses',base_url='https://example.com',secret='PRIVATE_VALUE')
    original=httpx.AsyncClient
    calls=[]
    def denied(request):
        calls.append(request)
        return httpx.Response(429,json={'error':{'code':'insufficient_quota','message':'PRIVATE_VALUE'}},headers={'x-request-id':'PRIVATE_VALUE','retry-after':'30'})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(denied),**kw))
    with pytest.raises(ServiceFailure) as caught:
        if adapter=='native':await agent_transport.turn(service,'system',[],[])
        elif adapter=='text':await providers.generate(service,'system','prompt')
        elif adapter=='image':await providers.image_generate(service,'prompt','1024x1024')
        else:await (search_tools.native(service,'query') if adapter=='search' else search_tools.gemini(service,'query'))
    assert len(calls)==1
    assert caught.value.details['category']=='quota' and caught.value.details['service']['model']=='fake'
    assert 'PRIVATE_VALUE' not in json.dumps(caught.value.details)
    assert 'retry_at' not in caught.value.details


@pytest.mark.anyio
async def test_image_failure_in_chain_retries_actual_image_and_success_links_plan(monkeypatch):
    from backend.service_errors import http_failure
    from backend.flow_state import job_view
    from PIL import Image
    import io
    a=store.create_article(models.Brief(topic='模拟图片').model_dump())
    plan=dict(id='cover-qa',role='cover',prompt='green',caption='模拟封面')
    a=store.save_article(a['id'],a['revision'],lambda v:v.update(content='正文',image_plans=[plan],visual={**v['visual'],'enabled':True},auto={**v['auto'],'visual':True}),'fixture')
    j=store.create_job(a['id'],models.JobRequest(stage='visual',revision=a['revision'],chain=True).model_dump())
    monkeypatch.setattr(providers,'service_for',lambda stage:dict(id='image-fixture',name='图片服务',model='fake',image_price=None))
    async def packet(*args):return {}
    monkeypatch.setattr(workflow.native_runtime,'generate',packet)
    monkeypatch.setattr(workflow.native_workflow,'apply',lambda a,*args:a)
    async def denied(*args):raise http_failure(403)
    monkeypatch.setattr(providers,'image_generate',denied)
    await workflow.run(j['id'])
    failed=job_view(store.job(j['id']))
    assert failed['stage']=='image' and failed['failure']['stage']=='image'
    assert failed['retry_request']['image_id']==plan['id'] and not failed['retry_request']['chain']
    async def picture(*args):
        buffer=io.BytesIO();Image.new('RGB',(8,8),'green').save(buffer,'PNG');return buffer.getvalue()
    monkeypatch.setattr(providers,'image_generate',picture)
    retry=store.create_job(a['id'],models.JobRequest(stage='image',image_id=plan['id'],revision=a['revision'],chain=False).model_dump())
    await workflow.run(retry['id'])
    image=store.get_article(a['id'])['images'][0]
    assert image['plan_id']==plan['id'] and image['id']!=plan['id']
