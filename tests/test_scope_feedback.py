import asyncio
import copy
import pytest
from backend import research,materials,models
from tests.test_quality_discovery import worker
from tests.quality_fixtures import notes,judgements,answer_scope_audit


def test_failed_condition_quote_returns_original_and_comparison_for_one_repair(monkeypatch):
    w=worker();s=materials.source('Synthetic protocol','Group (A) with a confirmed response is eligible.');w.a['sources']=[s]
    drafts=[]
    async def structured(a,stage,instruction,schema,job,candidates=None,questions=()):
        if schema is models.ResearchNotes:
            drafts.append(candidates)
            if len(drafts)==2:
                rejected=candidates[0]
                assert rejected['original_quote']==s['text']
                assert rejected['scope_alignment']['conditions'][0]['source_condition']=='A with a confirmed response'
            return schema.model_validate(notes(a,dict(summary='Synthetic',evidence=[dict(source_id=s['id'],quote=s['text'],claim='A组且有确认反应者可入选',core_claim=True)]))).model_dump()
        if schema is models.EvidenceJudgements:return judgements(candidates,a['research_contract'])
        if schema is models.EvidenceScopeAudit:
            original='Group (A) with a confirmed response' if len(drafts)==2 else 'A with a confirmed response'
            return dict(judgements=[dict(evidence_id=candidates[0]['evidence_id'],conditions=[dict(source_condition=original,claim_condition='A组且有确认反应',status='matched',reason='同一条件')],scope='matched',reason='模型声称可定位')])
        if schema is models.AnswerScopeAudit:return answer_scope_audit(candidates)
        if schema is models.CoverageAudit:return dict(coverage=[dict(question_id=r['question_id'],status='supported',reason='Complete',evidence_ids=r['candidate_evidence_ids']) for r in candidates[0]['coverage']])
        raise AssertionError(schema)
    monkeypatch.setattr(research,'structured',structured)
    asyncio.run(w.assess())
    assert len(drafts)==2 and w.sufficient() and w.calls==0 and w.pages==0
    assert s['text']=='Group (A) with a confirmed response is eligible.'


@pytest.mark.parametrize('corrected,persisted',[(True,False),(False,False),(True,True)])
def test_unbound_automatic_gap_gets_one_repair_without_relaxing_evidence(monkeypatch,corrected,persisted):
    w=worker();s=materials.source('Synthetic study','The first task improved. The second task did not improve.');w.a['sources']=[s]
    issue=dict(id='old',text='两项任务的完整结果待核实',kind='blocking',claim='两项任务分别改善及未改善',source_ids=[s['id']],status='resolved',resolution='Both checked')
    if persisted:w.a['research']=dict(issues=[dict(issue,status='open')])
    drafts=[]
    async def structured(a,stage,instruction,schema,job,candidates=None,questions=()):
        if schema is models.ResearchNotes:
            drafts.append(copy.deepcopy(candidates))
            if len(drafts)==2:assert any(x.get('unresolved_issues') for x in candidates)
            evidence=[dict(source_id=s['id'],quote=q,claim=c,core_claim=True) for q,c in [
                ('The first task improved.','第一项任务改善'),('The second task did not improve.','第二项任务未改善')]]
            return schema.model_validate(notes(a,dict(summary='Synthetic',evidence=evidence,
                issues=[] if len(drafts)==2 and corrected else [issue]))).model_dump()
        if schema is models.EvidenceJudgements:return judgements(candidates,a['research_contract'])
        if schema is models.EvidenceScopeAudit:return dict(judgements=[dict(evidence_id=e['evidence_id'],conditions=[],scope='matched',reason='Direct observation') for e in candidates])
        if schema is models.AnswerScopeAudit:return answer_scope_audit(candidates)
        if schema is models.CoverageAudit:return dict(coverage=[dict(question_id=r['question_id'],status='supported',reason='Complete',evidence_ids=r['candidate_evidence_ids']) for r in candidates[0]['coverage']])
        raise AssertionError(schema)
    monkeypatch.setattr(research,'structured',structured)
    asyncio.run(w.assess())
    assert len(drafts)==2 and w.calls==0 and w.pages==0
    assert w.sufficient()==(corrected and not persisted)
    if not corrected or persisted:assert w.open_targets()
