import pytest
from backend import evidence_scope, research, materials, research_contract


def span():
    return dict(evidence_id='E1',quote='Use B only if A is unavailable.',claim='A或B均可',boundary='',support='supported',
                quality='suitable',support_reason='主检查通过',support_checks=dict.fromkeys(research_contract.CHECKS,'matched'))


def verdict(**changes):
    row=dict(evidence_id='E1',scope='matched',reason='总体声称匹配',conditions=[dict(source_condition='only if A is unavailable',claim_condition='',status='missing',reason='缺少候补前提')])
    row.update(changes);return row


def test_aggregate_pass_cannot_hide_an_omitted_condition():
    e=span();evidence_scope.apply([e],[verdict()])
    assert e['support']=='unsupported' and e['quality']=='insufficient'
    assert e['support_checks']['scope']=='unknown' and '候补前提' in e['support_reason']


@pytest.mark.parametrize('change',[
    dict(source_condition='Invented condition',claim_condition='A',status='matched'),
    dict(source_condition='only if A is unavailable',claim_condition='只有A不可用',status='matched'),
    dict(source_condition='',claim_condition='A',status='matched'),
])
def test_alignment_must_quote_both_actual_sides(change):
    e=span();condition=dict(reason='声称支持',**change)
    evidence_scope.apply([e],[verdict(conditions=[condition])])
    assert e['support']=='unsupported'


def test_complete_condition_can_be_preserved_in_the_boundary():
    e=span();e['claim']='可采用B';e['boundary']='仅在A不可用时采用B'
    condition=dict(source_condition='only if A is unavailable',claim_condition='仅在A不可用时',status='matched',reason='候补前提一致')
    evidence_scope.apply([e],[verdict(conditions=[condition])])
    assert e['support']=='supported'


@pytest.mark.parametrize('rows',[[],[verdict(),verdict()],[dict(verdict(),evidence_id='unknown')]])
def test_missing_duplicate_or_unknown_verdict_never_passes(rows):
    e=span();evidence_scope.apply([e],rows)
    assert e['support']=='unsupported'


def test_changed_boundary_invalidates_the_claim_verdict_cache_key():
    s=materials.source('Synthetic study','A controlled experiment.')
    e=dict(source_id=s['id'],quote=s['text'],claim='这是实验',boundary='在实验室开展')
    first=research.validate_spans(dict(evidence=[e],gaps=[],issues=[]),[s])['evidence'][0]
    second=research.validate_spans(dict(evidence=[dict(e,boundary='在人群中开展')],gaps=[],issues=[]),[s])['evidence'][0]
    assert first['evidence_id']!=second['evidence_id']


def test_coverage_reason_cannot_add_a_mechanism_to_verified_observation():
    row=dict(question_id='Q1',status='supported',evidence_ids=['E1'],candidate_evidence_ids=['E1'],source_ids=['S1'])
    e=dict(span(),source_id='S1',claim='观察到行为差异',boundary='未测量生理机制')
    v=dict(question_id='Q1',status='supported',reason='已经证明是脑损伤引起',evidence_ids=['E1'])
    result=research_contract.audit_coverage([row],[v],[e])[0]
    assert '观察到行为差异' in result['reason'] and '未测量生理机制' in result['reason']
    assert '脑损伤' not in result['reason']
