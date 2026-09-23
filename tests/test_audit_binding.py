import asyncio
import copy
import json
import httpx
import pytest
from backend import materials,models,providers,research,research_contract
from tests.test_quality_discovery import worker
from tests.quality_fixtures import notes,judgements,scope_audit,answer_scope_audit
from tests.test_structured_research import environment


@pytest.mark.parametrize('duplicate_requested',[False,True])
def test_one_audit_group_cannot_vote_on_another_question(monkeypatch,duplicate_requested):
    w=worker();w.a['brief']['topic']='定位 DOI 10.1000/example 并说明条件'
    identity=materials.source('Original publication','Original publication identity.')
    identity['doi']='10.1000/example'
    conditions=materials.source('Protocol','The method applies only to group A.')
    w.a['sources']=[identity,conditions]
    original=research_contract.ensure(w.a)['questions'][0]['id']
    seen=[]
    async def structured(a,stage,instruction,schema,job,candidates=None,questions=()):
        if schema is models.ResearchNotes:
            return schema.model_validate(notes(a,dict(summary='Synthetic report',evidence=[
                dict(source_id=s['id'],quote=s['text'],claim=s['text'],core_claim=True) for s in w.a['sources']]))).model_dump()
        if schema is models.EvidenceJudgements:return judgements(candidates,a['research_contract'])
        if schema is models.EvidenceScopeAudit:return scope_audit(candidates)
        rows=candidates[0]['coverage'];seen.append([r['question_id'] for r in rows])
        if schema is models.CoverageAudit:
            result=dict(coverage=[dict(question_id=r['question_id'],status='supported',reason='Verified answer',evidence_ids=r['candidate_evidence_ids']) for r in rows]);key='coverage'
        else:
            assert schema is models.AnswerScopeAudit
            result=answer_scope_audit(candidates);key='judgements'
        if all(r['question_id']!=original for r in rows):
            # The identity-only call has no authority over the other group's
            # condition question, regardless of its positive/negative verdict.
            extra=copy.deepcopy(result[key][0]);extra['question_id']=original
            result[key].append(extra)
        elif duplicate_requested:
            result[key].append(copy.deepcopy(result[key][0]))
        return result
    monkeypatch.setattr(research,'structured',structured)
    asyncio.run(w.assess())
    assert any(ids==[original] for ids in seen) and any(original not in ids for ids in seen)
    assert w.sufficient() is (not duplicate_requested)
    assert (next(r for r in w.coverage if r['question_id']==original)['answer_scope'] is None)==duplicate_requested


@pytest.mark.parametrize('schema',[models.CoverageAudit,models.AnswerScopeAudit])
@pytest.mark.parametrize('identity_only',[False,True])
def test_group_prompt_retains_original_intent_without_other_question_ids(monkeypatch,schema,identity_only):
    prompts=[]
    def handler(request):
        prompts.append(json.loads(json.loads(request.content)['messages'][-1]['content']))
        value={'coverage':[]} if schema is models.CoverageAudit else {'judgements':[]}
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(value)},'finish_reason':'stop'}]})
    _,article,job=environment(monkeypatch,handler)
    article['brief']['topic']='定位 DOI 10.1000/example 并说明全部条件'
    contract=research_contract.ensure(article)
    contract['questions'].append(dict(id='Q-other',text='Another requirement',required=True))
    before=copy.deepcopy(contract);qid=contract['questions'][0]['id']
    row=dict(question_id=qid,question=contract['questions'][0]['text'],required=True,candidate_evidence_ids=[])
    if identity_only:
        qid=contract['source_targets'][0]['id'];row.update(question_id=qid,question='指定来源：10.1000/example')
    asyncio.run(research.structured(article,'sources','Audit this group',schema,job['id'],[dict(coverage=[row])]))
    supplied=prompts[0]['context']['research_contract']
    assert supplied['original_request']==contract['original_request']
    assert [q['id'] for q in supplied['questions']]==[qid]
    assert supplied['questions'][0]['scope']==('source_identity' if identity_only else 'user_requirement')
    assert contract==before
