import asyncio
import json
from pathlib import Path
import pytest
from backend import agent_transport,editorial,native_projection,native_skills,prompts,providers,store,writing_guidance
from tests.test_native_runtime import article,session


@pytest.mark.parametrize('purpose',['sources','outline','write','review','edit','revise','rewrite'])
def test_native_and_compatibility_receive_same_stage_policy(monkeypatch,purpose):
    a=article();runner=session(a,purpose);seen=[]
    async def capture(service,system,messages,tools):
        seen.append(system)
        raise ValueError('captured request')
    monkeypatch.setattr(agent_transport,'turn',capture)
    monkeypatch.setattr(providers,'service_for',lambda *_:dict(protocol='chat',model='mock',name='mock'))
    with pytest.raises(ValueError,match='captured request'):asyncio.run(runner.run())
    rules=writing_guidance.instructions(purpose)
    assert rules and seen[0].count(rules)==1
    assert rules in prompts.system(purpose,a['brief'])
    assert store.job(runner.job_id)['writing_guidance']==writing_guidance.metadata(purpose)
    assert all(doc['content'] in seen[0] for doc in native_skills.documents(purpose,a['brief']['persona']))
    assert store.get_article(a['id'])['content']==a['content']


@pytest.mark.parametrize('purpose',['research','fact_audit','topic','visual','stats','learn','layout_advice'])
def test_nonwriting_purposes_do_not_receive_manuscript_rules(purpose):
    assert not writing_guidance.instructions(purpose)
    assert writing_guidance.metadata(purpose) is None
    assert writing_guidance.COMMON not in prompts.system(purpose,{'persona':'warm-editor'})


@pytest.mark.parametrize('schema,route,purpose,reply',[
    (editorial.FactAudit,'review','fact_audit',{'segments':[]}),
    (editorial.EditedDraft,'write','edit',{'content':'修订候选。','explanation':'完成','changes':[],'unresolved':[]}),
])
def test_legacy_editor_selects_purpose_without_changing_model_route(monkeypatch,schema,route,purpose,reply):
    a=article();job=store.create_job(a['id'],dict(stage='edit'));routes=[];sent=[]
    def service_for(value):
        routes.append(value);return dict(protocol='chat',model='mock',name='mock')
    async def generate(service,system,prompt,emit):
        sent.append(system);return json.dumps(reply),dict(status='completed')
    monkeypatch.setattr(providers,'service_for',service_for)
    monkeypatch.setattr(providers,'generate',generate)
    asyncio.run(editorial.generate(a,job['id'],route,'Current task',schema))
    assert routes==[route]
    assert sent==[prompts.system(purpose,a['brief'])]
    if purpose=='fact_audit':
        assert 'writing_guidance' not in store.job(job['id'])
        assert writing_guidance.COMMON not in sent[0]
    else:assert store.job(job['id'])['writing_guidance']==writing_guidance.metadata('edit')


CASES=json.loads((Path(__file__).parent/'fixtures/narrative_cases.json').read_text('utf-8'))['cases']


@pytest.mark.parametrize('case',CASES,ids=lambda c:c['id'])
def test_reviewable_prose_is_not_rewritten_by_projection(case):
    # These paired editorial examples are also the live comparison rubric.
    # The adapter must not become a phrase blacklist or silently rewrite prose.
    assert native_projection.body(case['draft'])==case['draft']
    assert native_projection.body(case['revision'])==case['revision']
