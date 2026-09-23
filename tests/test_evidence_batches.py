import asyncio
import pytest
from backend import materials,models,research,evidence_state
from tests.test_quality_discovery import worker
from tests.quality_fixtures import notes,judgements,scope_audit,coverage_audit,answer_scope_audit


@pytest.mark.parametrize('omit_last',[False,True])
def test_batched_audits_keep_every_span_and_reject_a_missing_individual_verdict(monkeypatch,omit_last):
    w=worker();calls={'support':[],'scope':[]}
    first=materials.source('Synthetic A','\n'.join(f'Observation A{i}.' for i in range(9)))
    second=materials.source('Synthetic B','\n'.join(f'Observation B{i}.' for i in range(3)))
    w.a['sources']=[first,second]
    entries=[dict(source_id=s['id'],quote=line,claim=line) for s in w.a['sources'] for line in s['text'].splitlines()]
    async def structured(a,stage,instruction,schema,job,candidates=None,questions=()):
        if schema is models.ResearchNotes:return schema.model_validate(notes(a,dict(summary='',evidence=entries))).model_dump()
        if schema in (models.EvidenceJudgements,models.EvidenceScopeAudit):
            assert len({e['source_id'] for e in candidates})==1
            key='support' if schema is models.EvidenceJudgements else 'scope'
            calls[key].append([e['evidence_id'] for e in candidates])
            result=judgements(candidates,a['research_contract']) if key=='support' else scope_audit(candidates)
            if omit_last and key=='scope' and candidates[-1]['claim']=='Observation B2.':result['judgements'].pop()
            return result
        if schema is models.CoverageAudit:return coverage_audit(candidates)
        if schema is models.AnswerScopeAudit:return answer_scope_audit(candidates)
        raise AssertionError(schema.__name__)
    monkeypatch.setattr(research,'structured',structured)
    asyncio.run(w.assess())
    assert [len(batch) for batch in calls['support']]==[4,4,1,3]
    assert calls['support']==calls['scope']
    spans=w.notes['evidence'];assert len(spans)==12
    assert set(sum(calls['support'],[]))=={e['evidence_id'] for e in spans}
    assert sum(evidence_state.assessed(e) for e in spans)==(11 if omit_last else 12)
    if omit_last:assert not evidence_state.assessed(next(e for e in spans if e['claim']=='Observation B2.'))
    before={k:list(v) for k,v in calls.items()}
    asyncio.run(w.assess())
    assert calls==before
