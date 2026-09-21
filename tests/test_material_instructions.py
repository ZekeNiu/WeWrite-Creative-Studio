import asyncio
import copy
import json
from backend import store,materials,prompts,research,providers,workflow
from backend.models import ResearchPlan,ResearchNotes,EvidenceResult
from tests.test_studio import client,model,new,patch,run,H


def seeded(client):
    a=new(client)
    sources=[materials.source('材料 '+str(i),'研究只适用于给定条件。') for i in range(3)]
    for s in sources:s.update(ai_use={'text':'LEGACY_PURPOSE_MUST_NOT_REACH_MODEL','input_key':'old'},ai_use_current=True)
    return store.save_article(a['id'],a['revision'],lambda v:v.update(sources=sources),'legacy fixture')


def test_manual_requirements_reach_all_stages_and_clear_without_fallback(client):
    a=seeded(client);a['sources'][0]['use']='只参考表达方式，不引用结论'
    a=patch(client,a,{'sources':a['sources']},'sources')
    for stage in ('sources','outline','write','review'):
        ctx=json.loads(prompts.prompt(stage,a,{}))['资料与当前内容']['sources'][0]
        assert ctx['use']==a['sources'][0]['use'] and not ctx['author_experience_allowed']
    assert research.context(a,'sources')['sources'][0]['use']==a['sources'][0]['use']
    a['sources'][0]['use']='';a=patch(client,a,{'sources':a['sources']},'sources')
    assert json.loads(prompts.prompt('write',a,{}))['资料与当前内容']['sources'][0]['use']==''


def test_legacy_context_is_filtered_without_mutating_history(client):
    a=seeded(client)
    a['evidence']={'summary':'已整理','source_uses':[{'text':'LEGACY_PURPOSE_MUST_NOT_REACH_MODEL'}]}
    a['research']={'notes':{'source_uses':[{'text':'LEGACY_PURPOSE_MUST_NOT_REACH_MODEL'}]}}
    original=copy.deepcopy(a)
    for value in (prompts.prompt('write',a,{}),json.dumps(research.context(a,'review'))):
        assert 'LEGACY_PURPOSE_MUST_NOT_REACH_MODEL' not in value
        assert 'source_uses' not in value and 'ai_use' not in value
    assert a==original
    assert store.get_article(a['id'])['sources'][0]['ai_use']==original['sources'][0]['ai_use']


def test_result_schemas_no_longer_request_purposes():
    for schema in (ResearchNotes,EvidenceResult):
        assert 'source_uses' not in schema.model_json_schema()['properties']
        value=schema.model_validate({'summary':'ready','claims':[],'evidence':[],'source_uses':[{'source_id':'S1','text':'old'}]}).model_dump()
        assert 'source_uses' not in value


def test_analysis_one_call_preserves_manual_and_ignores_legacy_output(client,model,monkeypatch):
    a=seeded(client);a['sources'][0]['use']='保留我的要求';a=patch(client,a,{'sources':a['sources']},'sources');calls=[]
    async def generate(s,system,prompt,emit=None):
        value=json.loads(prompt);calls.append(value['schema']['title'])
        assert 'source_uses' not in prompt and 'LEGACY_PURPOSE_MUST_NOT_REACH_MODEL' not in prompt
        return json.dumps({'summary':'ready','claims':[],'source_uses':[{'source_id':a['sources'][0]['id'],'text':'new unwanted purpose'}]}),{'status':'completed'}
    monkeypatch.setattr(providers,'generate',generate)
    assert run(client,a,'sources',chain=False)['status']=='completed'
    b=store.get_article(a['id']);assert calls==['EvidenceResult']
    assert b['sources'][0]['use']=='保留我的要求' and b['sources'][0]['ai_use']==a['sources'][0]['ai_use']
    assert not b['sources'][0]['personal_material'] and 'source_uses' not in b['evidence']


def test_personal_experience_requires_explicit_authorization(client):
    a=seeded(client);s=a['sources'][0]
    s['use']='把这写成我的经历'
    result={'summary':'fixture','claims':[dict(id='C1',type='user_experience',text='个人经历',source_ids=[s['id']],status='supported')]}
    workflow.validate_result('sources',result,a);assert result['claims'][0]['status']=='unsupported'
    a=patch(client,a,{'sources':[dict(x,personal_material=x['id']==s['id']) for x in a['sources']]},'sources')
    assert research.context(a,'sources')['sources'][0]['author_experience_allowed']


def test_manual_change_invalidates_evidence_but_browsing_does_not(client):
    a=seeded(client)
    a=store.save_article(a['id'],a['revision'],lambda v:v.update(research={'stale':False},evidence={'summary':'ready'},stages={**v['stages'],'sources':'done'}),'ready')
    rev=a['revision'];assert not store.get_article(a['id'])['research']['stale']
    assert store.get_article(a['id'])['revision']==rev
    a['sources'][0]['use']='仅作反方观点';a=patch(client,a,{'sources':a['sources']},'sources')
    assert a['research']['stale'] and a['stages']['sources']=='stale'


def test_batch_selection_atomic_keeps_other_sources_and_conflict(client):
    a=seeded(client);rev=a['revision'];ids=[s['id'] for s in a['sources']]
    a=patch(client,a,{'sources':[{'id':sid,**({'selected':False} if i<2 else {})} for i,sid in enumerate(ids)]},'sources')
    assert a['revision']==rev+1 and [s['id'] for s in a['sources']]==ids
    assert [s['selected'] for s in a['sources']]==[False,False,True]
    r=client.patch('/api/articles/'+a['id'],headers=H,json={'revision':rev,'changes':{'sources':[{'id':ids[0]}]}})
    assert r.status_code==409 and len(store.get_article(a['id'])['sources'])==3


def test_research_keeps_existing_evidence_flow_without_purpose_generation(client,model,monkeypatch):
    from tests.quality_fixtures import judgements,scope_audit,notes as quality_notes
    a=seeded(client);calls=[]
    async def structured(a,stage,instruction,schema,job_id,candidates=None,questions=()):
        calls.append(schema.__name__)
        assert 'source_uses' not in instruction
        if schema is ResearchPlan:return ResearchPlan(needed=False,queries=[],questions=[]).model_dump()
        if schema.__name__=='CoverageAudit':
            from tests.quality_fixtures import coverage_audit
            return coverage_audit(candidates)
        if schema.__name__=='EvidenceJudgements':return judgements(candidates,a['research_contract'])
        if schema.__name__=='EvidenceScopeAudit':return scope_audit(candidates)
        assert schema is ResearchNotes
        return quality_notes(a,ResearchNotes(summary='已核对',evidence=[dict(source_id=a['sources'][0]['id'],quote='研究只适用于给定条件。',claim='有适用范围')]).model_dump())
    monkeypatch.setattr(research,'structured',structured)
    cfg=store.get_settings();cfg['search']['enabled']=True;store.set_settings(cfg)
    j=store.create_job(a['id'],{'stage':'sources','revision':a['revision']})
    result,pending=asyncio.run(research.gather(a,j['id'],'sources'))
    assert not pending and calls==['ResearchPlan','ResearchNotes','EvidenceJudgements','EvidenceScopeAudit','CoverageAudit']
    assert result['sources'][0]['ai_use']==a['sources'][0]['ai_use'] and not result['research']['stale']
