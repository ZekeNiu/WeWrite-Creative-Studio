import asyncio
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
