import asyncio
import json
import httpx
import pytest
from backend import models,providers,research,store
from backend.structured_output import parse
from tools.benchmark_support import Capture


@pytest.mark.parametrize('schema,fragment,final',[
    (models.CoverageAudit,dict(question_id='Q1',reason='fragment'),dict(coverage=[])),
    (models.EvidenceJudgements,dict(evidence_id='E1',reason='fragment'),dict(judgements=[])),
    (models.EvidenceScopeAudit,dict(evidence_id='E1',reason='fragment'),dict(judgements=[])),
    (models.AnswerScopeAudit,dict(question_id='Q1',reason='fragment'),dict(judgements=[])),
    (models.SearchSelection,dict(url='https://example.org/source',reason='fragment'),dict(urls=[])),
    (models.IssueScope,dict(id='I1',kind='limitation',reason='fragment'),dict(decisions=[])),
    (models.ResearchNotes,dict(summary='source summary fragment'),dict(summary='report',evidence=[])),
    (models.EvidenceAdditions,dict(source_id='S1',quote='original',claim='intermediate'),dict(evidence=[])),
])
def test_intermediate_fragments_are_not_complete_results(schema,fragment,final):
    fragment=json.dumps(fragment);expected=schema.model_validate(final).model_dump();final=json.dumps(final)
    assert parse(fragment+'\n'+final,schema)==expected
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
    first=json.loads((tmp_path/'capture/raw/case/0001.json').read_text('utf8'))
    second=json.loads((tmp_path/'capture/raw/case/0002.json').read_text('utf8'))
    assert first['status']=='incomplete' and first['structured_output']['mode']=='json_schema'
    assert second['status']=='completed' and second['structured_output']['mode']=='text'
    first_wire=json.loads((tmp_path/'capture/raw/case/0001.response.txt').read_text('utf8'))
    second_wire=json.loads((tmp_path/'capture/raw/case/0002.response.txt').read_text('utf8'))
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


@pytest.mark.parametrize('body,expected',[
    ({'code':'INSUFFICIENT_BALANCE','message':'Insufficient account balance'},'余额不足'),
    ({'error':{'message':'insufficient balance','type':'billing_error'}},'余额不足'),
    ({'error':{'code':'insufficient_balance','message':'private-test-key'}},'余额不足'),
    ({'error':{'message':'private-test-key','type':'permission_error'}},'分组或模型权限'),
    ({'error':{'message':'billing request was denied','type':'billing_error'}},'分组或模型权限'),
    ({'error':'private-test-key'},'分组或模型权限'),
    (['INSUFFICIENT_BALANCE'],'分组或模型权限'),
    ('insufficient balance private-test-key','分组或模型权限'),
])
def test_research_billing_errors_keep_raw_response_and_unknown_usage(monkeypatch,tmp_path,body,expected):
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(403,json=body)
    service,article,job=environment(monkeypatch,handler)
    before=dict(service)
    monkeypatch.setattr(providers,'generate',providers.generate)
    monkeypatch.setattr(providers,'frames',providers.frames)
    monkeypatch.setattr(providers,'response_body',providers.response_body)
    capture=Capture(providers,tmp_path/'capture');capture.case.set('case')
    with pytest.raises(ValueError,match=expected) as exc:invoke(article,job)
    assert 'private-test-key' not in str(exc.value)
    assert len(calls)==1 and service==before
    usage=store.usage(article['id'])
    assert len(usage)==1 and usage[0]['status']=='unknown' and usage[0]['estimated_cost'] is None
    assert json.loads((tmp_path/'capture/raw/case/0001.response.txt').read_text('utf8'))==body


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


@pytest.mark.parametrize('invalid',[
    '{"judgements":[]}\n{"judgements":[]}',
    '{"judgements": "invalid schema"}',
])
def test_invalid_format_reissues_identical_request_and_retains_each_attempt(monkeypatch,tmp_path,invalid):
    requests=[]
    def handler(request):
        requests.append(json.loads(request.content))
        if len(requests)<3:
            return httpx.Response(200,json=dict(choices=[dict(message=dict(content=invalid),finish_reason='stop')],usage=dict(prompt_tokens=2,completion_tokens=3)))
        return completed()
    service,article,job=environment(monkeypatch,handler);before=dict(service)
    monkeypatch.setattr(providers,'generate',providers.generate)
    monkeypatch.setattr(providers,'frames',providers.frames)
    monkeypatch.setattr(providers,'response_body',providers.response_body)
    capture=Capture(providers,tmp_path/'capture');capture.case.set('case')
    assert invoke(article,job)==dict(judgements=[])
    assert service==before and len(requests)==3 and requests[0]==requests[1]==requests[2]
    usage=store.usage(article['id']);assert len(usage)==3
    assert all(row['status']=='completed' and row['estimated_cost'] is None for row in usage)
    failures=[e for e in store.events(job['id'],0) if e.get('structured_output')=='invalid']
    assert [e['attempt'] for e in failures]==[1,2]
    assert all(e['raw']==invalid and e['attempt_limit']==3 for e in failures)
    assert {e['usage_id'] for e in failures}<={row['id'] for row in usage}
    assert all(e['request']['prompt']==requests[0]['messages'][1]['content'] for e in failures)
    assert 'private-test-key' not in json.dumps(failures)
    records=[json.loads((tmp_path/f'capture/raw/case/{i:04}.json').read_text('utf8')) for i in range(1,4)]
    assert [r['raw'] for r in records]==[invalid,invalid,'{"judgements":[]}']
    assert store.job(job['id'])['partial']=='{"judgements":[]}'


def test_invalid_format_stops_at_limit_without_adopting_any_answer(monkeypatch):
    requests=[];invalid='{"judgements":[]}\n{"judgements":[]}'
    def handler(request):
        requests.append(request)
        return httpx.Response(200,json=dict(choices=[dict(message=dict(content=invalid),finish_reason='stop')]))
    _,article,job=environment(monkeypatch,handler)
    with pytest.raises(ValueError,match='格式无效'):invoke(article,job)
    assert len(requests)==3 and len(store.usage(article['id']))==3
    assert all(row['status']=='completed' for row in store.usage(article['id']))
    failures=[e for e in store.events(job['id'],0) if e.get('structured_output')=='invalid']
    assert [e['attempt'] for e in failures]==[1,2,3]
    assert store.job(job['id'])['partial']==invalid


def test_retry_resets_partial_and_does_not_retry_transport_or_cancellation(monkeypatch):
    async def scenario(error):
        _,article,job=environment(monkeypatch,lambda request:completed())
        calls=[]
        async def generate(service,system,prompt,emit):
            calls.append(prompt)
            if len(calls)==1:
                await emit('first invalid')
                return 'first invalid',dict(status='completed',estimated_cost=None)
            await emit('second partial')
            raise error
        monkeypatch.setattr(providers,'generate',generate)
        with pytest.raises(type(error)):
            await research.structured(article,'sources','核查给定证据',models.EvidenceJudgements,job['id'])
        assert len(calls)==2 and calls[0]==calls[1]
        assert store.job(job['id'])['partial']=='second partial'
        assert len(store.usage(article['id']))==2
        assert sum(row['status']=='unknown' for row in store.usage(article['id']))==1
    asyncio.run(scenario(ValueError('connection failed')))
    asyncio.run(scenario(asyncio.CancelledError()))


def test_retry_never_trims_schema_overflow_to_obtain_a_result(monkeypatch):
    value=dict(summary='report',evidence=[],intent=dict(title='Synthetic',angle='Synthetic',reason='Synthetic',questions=[f'question {i}' for i in range(9)]))
    assert models.ResearchNotes.model_validate(dict(value,intent=dict(value['intent'],questions=value['intent']['questions'][:8])))
    raw=json.dumps(value)
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(200,json=dict(choices=[dict(message=dict(content=raw),finish_reason='stop')]))
    _,article,job=environment(monkeypatch,handler)
    with pytest.raises(ValueError,match='格式无效'):
        asyncio.run(research.structured(article,'sources','保留全部用户问题',models.ResearchNotes,job['id']))
    assert len(calls)==3
    assert all(e['raw']==raw for e in store.events(job['id'],0) if e.get('structured_output')=='invalid')


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
