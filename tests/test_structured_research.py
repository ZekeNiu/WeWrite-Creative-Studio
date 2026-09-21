import asyncio
import json
import httpx
import pytest
from backend import models,providers,research,store
from backend.structured_output import parse
from tools.benchmark_support import Capture


@pytest.mark.parametrize('schema,key',[(models.CoverageAudit,'coverage'),(models.EvidenceJudgements,'judgements')])
def test_intermediate_fragments_are_not_complete_results(schema,key):
    fragment=json.dumps(dict(question_id='Q1',reason='intermediate fragment'))
    final=json.dumps({key:[]})
    assert parse(fragment+'\n'+final,schema)=={key:[]}
    with pytest.raises(ValueError):parse(fragment,schema)
    with pytest.raises(ValueError):parse(final+'\n'+final,schema)


def environment(monkeypatch,handler):
    service=dict(model='unchanged-model',protocol='chat',secret='private-test-key',name='test',base_url='https://api.example',max_tokens=8000)
    real=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    monkeypatch.setattr(providers,'service_for',lambda stage:service)
    article=store.create_article(dict(topic='合成格式验收'))
    job=store.create_job(article['id'],dict(stage='sources',revision=0))
    return service,article,job


def completed():
    return httpx.Response(200,json=dict(choices=[dict(message=dict(content='{"judgements":[]}'),finish_reason='stop')],usage=dict(prompt_tokens=2,completion_tokens=3)))


def invoke(article,job):
    return asyncio.run(research.structured(article,'sources','核查给定证据',models.EvidenceJudgements,job['id']))


def test_native_schema_is_requested_without_changing_user_service(monkeypatch):
    requests=[]
    def handler(request):
        requests.append(json.loads(request.content));return completed()
    service,article,job=environment(monkeypatch,handler)
    before=dict(service)
    assert invoke(article,job)==dict(judgements=[])
    assert service==before and len(requests)==1
    body=requests[0]
    assert body['model']=='unchanged-model' and body['max_tokens']==8000
    assert body['stream'] is False and 'stream_options' not in body
    assert body['response_format']['type']=='json_schema'
    assert 'judgements' in body['response_format']['json_schema']['schema']['required']


def test_explicit_unsupported_format_keeps_same_model_and_both_attempts(monkeypatch,tmp_path):
    requests=[]
    def handler(request):
        body=json.loads(request.content);requests.append(body)
        if 'response_format' in body:return httpx.Response(400,json={'error':{'message':'response_format json_schema is not supported'}})
        return completed()
    service,article,job=environment(monkeypatch,handler)
    monkeypatch.setattr(providers,'generate',providers.generate)
    monkeypatch.setattr(providers,'frames',providers.frames)
    monkeypatch.setattr(providers,'response_body',providers.response_body)
    capture=Capture(providers,tmp_path/'capture');capture.case.set('case')
    assert invoke(article,job)==dict(judgements=[])
    assert len(requests)==2
    assert {k:v for k,v in requests[0].items() if k!='response_format'}==requests[1]
    assert len(store.usage(article['id']))==2
    assert any(e.get('structured_output')=='explicitly_unsupported' for e in store.events(job['id'],0))
    first=json.loads((tmp_path/'capture/raw/case/0001.json').read_text())
    second=json.loads((tmp_path/'capture/raw/case/0002.json').read_text())
    assert first['status']=='incomplete' and first['structured_output']['mode']=='json_schema'
    assert second['status']=='completed' and second['structured_output']['mode']=='text'
    first_wire=json.loads((tmp_path/'capture/raw/case/0001.response.txt').read_text())
    second_wire=json.loads((tmp_path/'capture/raw/case/0002.response.txt').read_text())
    assert 'not supported' in first_wire['error']['message']
    assert second_wire['choices'][0]['message']['content']=='{"judgements":[]}'
    assert 'private-test-key' not in json.dumps([first,second])


@pytest.mark.parametrize('status,message',[(400,'Invalid schema definition'),(401,'response_format unsupported'),(429,'response_format unsupported'),(500,'temporary upstream error')])
def test_other_provider_errors_never_trigger_automatic_retry(monkeypatch,status,message):
    calls=[]
    def handler(request):calls.append(request);return httpx.Response(status,json={'error':{'message':message}})
    _,article,job=environment(monkeypatch,handler)
    with pytest.raises(ValueError):invoke(article,job)
    assert len(calls)==1


def test_interrupted_stream_never_triggers_format_fallback(monkeypatch):
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200,headers={'content-type':'text/event-stream'},text='data: {"choices":[{"delta":{"content":"partial"}}]}\n\n')
    _,article,job=environment(monkeypatch,handler)
    with pytest.raises(ValueError,match='提前结束'):invoke(article,job)
    assert len(calls)==1


@pytest.mark.parametrize('fenced_valid',[False,True])
def test_full_response_is_checked_including_outside_a_code_fence(monkeypatch,fenced_valid):
    first={'judgements':[]} if fenced_valid else {'intermediate':'not a report'}
    raw='```json\n'+json.dumps(first)+'\n```\n'+json.dumps({'judgements':[]})
    def handler(request):
        return httpx.Response(200,json={'choices':[{'message':{'content':raw},'finish_reason':'stop'}]})
    _,article,job=environment(monkeypatch,handler)
    if fenced_valid:
        with pytest.raises(ValueError,match='格式无效'):invoke(article,job)
    else:assert invoke(article,job)=={'judgements':[]}


@pytest.mark.parametrize('kind',['missing_finish','truncated','multiple_choices'])
def test_single_response_research_requires_unique_completed_output(monkeypatch,kind):
    choice={'message':{'content':'{"judgements":[]}'},'finish_reason':'stop'}
    if kind=='missing_finish':choice.pop('finish_reason')
    if kind=='truncated':choice['finish_reason']='length'
    choices=[choice,choice] if kind=='multiple_choices' else [choice]
    calls=[]
    def handler(request):calls.append(request);return httpx.Response(200,json={'choices':choices})
    _,article,job=environment(monkeypatch,handler)
    with pytest.raises(ValueError):invoke(article,job)
    assert len(calls)==1 and len(store.usage(article['id']))==1
    assert store.usage(article['id'])[0]['status']=='unknown'


def test_single_response_research_remains_cancellable_without_retry(monkeypatch):
    calls=[]
    async def scenario():
        started=asyncio.Event()
        async def handler(request):
            calls.append(request);started.set();await asyncio.Event().wait()
        _,article,job=environment(monkeypatch,handler)
        task=asyncio.create_task(research.structured(article,'sources','核查给定证据',models.EvidenceJudgements,job['id']))
        await asyncio.wait_for(started.wait(),1);task.cancel()
        with pytest.raises(asyncio.CancelledError):await task
        assert len(calls)==1 and store.usage(article['id'])[0]['status']=='unknown'
    asyncio.run(scenario())


def test_other_generation_keeps_default_streaming(monkeypatch):
    requests=[]
    def handler(request):requests.append(json.loads(request.content));return completed()
    service,_,_=environment(monkeypatch,handler)
    asyncio.run(providers.generate(service,'system','prompt'))
    assert requests[0]['stream'] is True and requests[0]['stream_options']=={'include_usage':True}
