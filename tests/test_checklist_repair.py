import asyncio
import copy
import pytest
from backend import materials,models,research,research_contract
from tests.test_quality_discovery import worker
from tests.quality_fixtures import notes,judgements,scope_audit


def test_missing_list_targets_keep_actual_page_header_and_never_read_hidden_text():
    text='1. The applicant must have a documented response\n[第 2 页]\nProtocol revision A\non two separate visits.\n2. Hidden condition.'
    source=materials.source('Synthetic protocol',text)
    source.update(pages=[dict(page=1,text=text)],notebook=dict(read_ranges=[dict(start=0,end=text.index('2. Hidden'))]))
    attempted='1. The applicant must have a documented response\non two separate visits.'
    listing=dict(source_id=source['id'],complete_read=True,items=[dict(source_quote=attempted,covered=False),dict(source_quote='2. Hidden condition.',covered=False)])
    row=dict(question_id='Q1',question='Explain the conditions',required=True,status='unresolved',answer_scope=dict(source_lists=[listing]))
    a=dict(sources=[source]);targets=research.repair_targets(a,[row])
    assert len(targets)==1 and targets[0]['unverified_item_quote']==attempted
    passage=targets[0]['original_passages'][0]
    assert passage['text']==text[passage['start']:passage['end']]
    assert '[第 2 页]\nProtocol revision A' in passage['text'] and 'Hidden' not in passage['text']
    assert research.repair_targets(a,[dict(row,required=False)])==[]
    incomplete=copy.deepcopy(row);incomplete['answer_scope']['source_lists'][0]['complete_read']=False
    assert research.repair_targets(a,[incomplete])==[]
    assert source['text']==text


def test_identity_repair_only_targets_accessed_matching_source():
    first=materials.source('Original abstract','Original abstract text.');second=materials.source('Unread','')
    second['status']='metadata_only'
    a=dict(sources=[first,second],research_contract=dict(source_targets=[dict(id='K1')]))
    row=dict(question_id='K1',question='Specified source',required=True,status='unresolved',source_ids=[first['id'],second['id']])
    assert research.repair_targets(a,[row])==[dict(question_id='K1',question='Specified source',source_id=first['id'],scope='source_identity')]


@pytest.mark.parametrize('rejected',[False,True])
def test_one_repair_batches_missing_items_and_still_requires_independent_support(monkeypatch,rejected):
    w=worker();w.a['brief']['topic']='Explain all eligibility conditions'
    lines=[f'{i}. Synthetic condition {i} is required.' for i in range(1,10)]
    source=materials.source('Synthetic protocol','\n'.join(lines));w.a['sources']=[source]
    calls=[];patch_batches=[];audited=[]
    def evidence(quote,qid):
        return dict(source_id=source['id'],quote=quote,claim=quote,question_ids=[qid],quality='suitable',core_claim=True,
                    source_type='original',adoption_reason='Synthetic original rule',use_scope='Eligibility')
    async def structured(a,stage,instruction,schema,job,candidates=None,questions=()):
        if schema is models.ResearchNotes:
            calls.append(schema)
            # Simulate the real failure: the overview still omits eight items.
            return schema.model_validate(notes(a,dict(summary='Synthetic',evidence=[evidence(lines[0],a['research_contract']['questions'][0]['id'])]))).model_dump()
        if schema is models.EvidenceAdditions:
            patch_batches.append(copy.deepcopy(candidates))
            return schema.model_validate(dict(evidence=[evidence(t['original_passages'][0]['text'],t['question_id']) for t in candidates])).model_dump()
        if schema is models.EvidenceJudgements:
            audited.extend(e['quote'] for e in candidates)
            result=judgements(candidates,a['research_contract'])
            if rejected:
                for e,v in zip(candidates,result['judgements']):
                    if e['quote']==lines[-1]:v.update(support='unsupported',reason='Synthetic unsupported last item')
            return result
        if schema is models.EvidenceScopeAudit:return scope_audit(candidates)
        if schema is models.CoverageAudit:
            return dict(coverage=[dict(question_id=r['question_id'],status='supported',reason='Claims checked',evidence_ids=r['candidate_evidence_ids']) for r in candidates[0]['coverage']])
        if schema is models.AnswerScopeAudit:
            group=candidates[0];found={e['quote']:e for e in group['evidence']};complete=all(q in found for q in lines)
            return dict(judgements=[dict(question_id=r['question_id'],parts=[dict(request_quote=r['question'],evidence_ids=r['candidate_evidence_ids'],status='answered' if complete else 'missing',reason='Check all conditions')],
                enumeration_requested=True,source_lists=[dict(source_id=source['id'],complete_read=True,items=[dict(source_quote=q,answer_quote=q if q in found else '',evidence_ids=[found[q]['evidence_id']] if q in found else [],covered=q in found,reason='Check item') for q in lines],reason='Read list')],complete=complete,reason='All required items' if complete else 'Missing items') for r in group['coverage']],read_requests=[])
        raise AssertionError(schema)
    monkeypatch.setattr(research,'structured',structured)
    asyncio.run(w.assess())
    assert len(calls)==2 and [len(batch) for batch in patch_batches]==[4,4]
    assert set(audited)==set(lines)
    assert w.sufficient() is not rejected,(w.coverage,w.issues())
    assert w.calls==0 and w.pages==0 and w.rounds==0
    assert source['text']=='\n'.join(lines)


def test_wrong_supplement_source_is_rejected_before_merge(monkeypatch):
    w=worker();s=materials.source('Synthetic source','A read requirement.');w.a['sources']=[s]
    research_contract.ensure(w.a)
    qid=w.a['research_contract']['questions'][0]['id']
    w.coverage=[dict(question_id=qid,question='Read requirement',required=True,status='unresolved',reason='Missing item',source_ids=[s['id']],answer_scope=dict(source_lists=[dict(source_id=s['id'],complete_read=True,items=[dict(source_quote=s['text'],covered=False)])]))]
    # Avoid a stale notebook by using the current analysis signature.
    import hashlib
    s['notebook']=dict(analysis_signature=research.analysis_signature(),text_key=hashlib.sha256(s['text'].encode()).hexdigest(),read_ranges=[dict(start=0,end=len(s['text']))])
    async def structured(a,stage,instruction,schema,job,candidates=None,questions=()):
        assert schema is models.EvidenceAdditions
        return dict(evidence=[dict(source_id='another-source',question_ids=[qid],quote=s['text'],claim='Unsupported replacement')])
    monkeypatch.setattr(research,'structured',structured)
    with pytest.raises(ValueError,match='本组问题与来源'):asyncio.run(w.assess(repair_round=1))
    assert not w.notes.get('evidence') and w.calls==0
