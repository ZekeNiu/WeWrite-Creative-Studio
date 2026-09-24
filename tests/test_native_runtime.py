import asyncio
import copy
import json
import pytest
from backend import store,models,materials,native_runtime as native,native_projection,native_skills,native_workflow,agent_transport,providers,workflow,account_memory


@pytest.fixture
def anyio_backend():return "asyncio"


def article():
    a=store.create_article(models.Brief(topic='解释方法').model_dump())
    def update(v):
        v['sources']=[materials.source('长原文','开头。'*10000+'操作定义在这里：450–1200ms。','https://example.com/paper','web')]
        v['content']='原始正文。';v['outline']={'sections':[dict(id='one',title='问题',purpose='解释',points=[],claim_ids=[])]};v['stages']['outline']='done'
    return store.save_article(a['id'],a['revision'],update,'test')


def session(a,stage='write'):
    request=models.JobRequest(stage=stage,revision=a['revision'],chain=False).model_dump()
    j=store.create_job(a['id'],request)
    return native.Session(a,j['id'],stage,request)


def test_all_skills_have_complete_required_files():
    assert native_skills.verify().startswith('e8df474')
    for stage in native_skills.MODULES:
        docs=native_skills.documents(stage,'industry-observer')
        assert len(docs)>=3
        assert all(x['content'] and x['sha256'] for x in docs)
    assert any('content-enhance.md' in d['path'] for d in native_skills.documents('write','industry-observer'))


@pytest.mark.anyio
async def test_real_cli_isolation_reread_sources_and_permissions():
    a=article();s=session(a);other=session(article())
    await s.prepare();await other.prepare()
    assert s.state['run_id']!=other.state['run_id']
    sid=a['sources'][0]['id'];path='source-texts/'+sid+'.txt'
    found=await s.execute('Find',dict(path=path,query='操作定义'))
    read=await s.execute('Read',dict(path=path,start=found[0]['match'],length=100))
    assert '450–1200ms' in read['text'] and read['start']>12000
    await s.cli(['sources','add','--url','https://example.com/paper','--title','论文','--claim','操作定义'])
    ledger=json.loads(await s.cli(['sources','list','--json']))
    assert ledger['sources'][0]['id']==sid
    assert len(ledger['sources'])==1
    s.sync_sources()
    assert native_projection.mapping(s.directory/'sources.yaml')['sources'][0]['status']=='verified'
    for args in (['sources','add','--url','https://unknown.test','--title','伪造','--claim','事实'],['score',str(other.home/'secret')],['content-eval','--output=../../bad.json'],['run','show',other.state['run_id']],['exemplar','--list','../../other.md']):
        with pytest.raises(ValueError):await s.cli(args)
    with pytest.raises(ValueError):s.path('../other',True)
    with pytest.raises(ValueError):s.path('skills/wewrite/SKILL.md',True)


@pytest.mark.anyio
async def test_review_uses_real_report_minor_is_pass_and_preserves_original():
    a=article();s=session(a,'review');await s.prepare();d=s.directory.relative_to(s.home).as_posix()
    assessment=dict(decision='pass',pass_number=1,dimensions={k:4 for k in ('accuracy','viewpoint','usefulness','voice','readability')},blockers=[],major_issues=[],minor_issues=['可微调节奏'],notes='表达已改好')
    await s.execute('Write',dict(path=d+'/article.md',content='改好正文。'))
    await s.execute('Write',dict(path=d+'/assessment.yaml',content=json.dumps(assessment)))
    with pytest.raises(ValueError,match='content-eval'):await s.execute('Finish',{})
    await s.cli(['content-eval','--draft',d+'/draft.md','--final',d+'/article.md','--assessment',d+'/assessment.yaml','--output',d+'/review-report.json','--json'])
    await s.execute('Finish',{})
    assert s.result['decision']=='pass'
    packet=dict(result=s.result,sources=s.sources,brief={},native={'id':s.id},account_use=s.used)
    updated=native_workflow.apply(a,'review',packet,{'_job_id':s.job_id})
    assert updated['content']==a['content']
    assert updated['stages']['review']=='needs_input'
    candidate=updated['editorial_candidates'][0]
    from backend import editorial
    adopted=editorial.adopt(updated,candidate['id'])
    assert adopted['content']=='改好正文。' and adopted['review']['decision']=='pass'
    assert adopted['stages']['review']=='done'


@pytest.mark.anyio
async def test_tool_continuation_and_conflict(monkeypatch):
    a=article();s=session(a);turns=[]
    service=dict(protocol='chat',model='offline',name='test',max_tokens=1000)
    monkeypatch.setattr(providers,'service_for',lambda *_:service)
    async def turn(service,system,messages,tools):
        turns.append(copy.deepcopy(messages))
        if len(turns)==1:
            path=json.loads(messages[0]['content'])['run_dir']+'/draft.md'
            calls=[dict(id='w',name='Write',arguments=json.dumps(dict(path=path,content='新稿。')))]
        else:
            assert messages[-1]['role']=='tool'
            calls=[dict(id='f',name='Finish',arguments='{}')]
        return dict(wire=[dict(role='assistant',content=None,tool_calls=[dict(id=c['id'],type='function',function=dict(name=c['name'],arguments=c['arguments'])) for c in calls])],calls=calls,text='',usage=dict(status='completed',estimated_cost=None))
    monkeypatch.setattr(agent_transport,'turn',turn)
    store.update_job(s.job_id,native_tool_count=120)
    packet=await s.run()
    assert packet['result']=='新稿。' and len(turns)==2
    assert store.job(s.job_id)['execution_usage']['requests']==2
    assert store.job(s.job_id)['native_tool_count']==122
    current=store.save_article(a['id'],a['revision'],lambda v:v.update(content='人工修改'),'human')
    with pytest.raises(store.Conflict):native_workflow.apply(a,'write',packet,{})
    assert store.get_article(a['id'])['content']==current['content']


@pytest.mark.anyio
async def test_no_tools_never_falls_back_and_legacy_limits_do_not_block_reservation(monkeypatch):
    a=article();s=session(a)
    monkeypatch.setattr(providers,'service_for',lambda *_:dict(model='test',protocol='chat'))
    async def text_only(*args):return dict(wire=[],calls=[],text='假成稿',usage=dict(estimated_cost=None))
    monkeypatch.setattr(agent_transport,'turn',text_only)
    with pytest.raises(ValueError,match='工具'):await s.run()
    assert store.get_article(a['id'])['content']=='原始正文。'
    s.reserve(dict(model='test'),'x')
    other=session(article());other.reserve(dict(model='test'),'x')
    assert store.job(s.job_id)['execution_usage']['requests']>=2
    assert store.job(other.job_id)['execution_usage']['requests']==1


@pytest.mark.parametrize('protocol',['chat','responses','anthropic'])
def test_protocol_tool_roundtrip(protocol):
    service=dict(model='test',protocol=protocol)
    if protocol=='chat':payload=dict(choices=[dict(finish_reason='tool_calls',message=dict(role='assistant',content=None,tool_calls=[dict(id='1',type='function',function=dict(name='Read',arguments='{"path":"x"}'))]))])
    elif protocol=='responses':payload=dict(status='completed',output=[dict(type='reasoning',id='r',summary=[]),dict(type='function_call',call_id='1',name='Read',arguments='{"path":"x"}')])
    else:payload=dict(stop_reason='tool_use',content=[dict(type='thinking',thinking='step',signature='sig'),dict(type='tool_use',id='1',name='Read',input=dict(path='x'))])
    wire,calls,text=agent_transport.decode(protocol,payload)
    assert calls[0]['name']=='Read'
    messages=[dict(role='user',content='read'),*wire];agent_transport.append_results(protocol,messages,[('1','actual source')])
    path,body=agent_transport.request_body(service,'skills',messages,native.TOOLS)
    assert 'actual source' in json.dumps(body)
    assert wire[0] in (body.get('messages') or body['input'])
