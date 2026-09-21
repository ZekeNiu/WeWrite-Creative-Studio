import copy
import pytest
from backend import coverage_scope,research_contract


def inputs():
    row=dict(question_id='Q1',question='说明全部条件',required=True,status='supported',reason='核实后的内容',evidence_ids=['E1','E2'],source_ids=['S1'])
    pool=dict(row,candidate_evidence_ids=['E1','E2'])
    spans=[dict(evidence_id='E1',source_id='S1',quote='First condition.'),dict(evidence_id='E2',source_id='S1',quote='Second condition.')]
    texts=[dict(id='S1',text='First condition. Second condition.')]
    items=[dict(source_quote=e['quote'],evidence_ids=[e['evidence_id']],covered=True,reason='该项已回答') for e in spans]
    check=dict(question_id='Q1',parts=[dict(request_quote='说明全部条件',evidence_ids=['E1','E2'],status='answered',reason='全部已回答')],
        enumeration_requested=True,source_lists=[dict(source_id='S1',complete_read=True,items=items,reason='已读完整条件')],complete=True,reason='已完整回答')
    return row,pool,spans,texts,check


def audit(change=None):
    row,pool,spans,texts,check=inputs()
    if change:change(row,pool,spans,texts,check)
    return coverage_scope.apply([row],[check],[pool],spans,texts)[0]


def test_complete_source_list_and_verified_answers_can_pass():
    assert audit()['status']=='supported'


@pytest.mark.parametrize('change',[
    lambda r,p,e,t,c:c['parts'][0].update(status='missing',reason='用户要求未回答'),
    lambda r,p,e,t,c:c['parts'][0].update(request_quote='并比较所有其他方案'),
    lambda r,p,e,t,c:c.update(parts=[]),
    lambda r,p,e,t,c:c.update(source_lists=[]),
    lambda r,p,e,t,c:c['source_lists'][0].update(complete_read=False,reason='完整列表仍在未读附录'),
    lambda r,p,e,t,c:c['source_lists'][0]['items'][1].update(covered=False,reason='第二项没有解释'),
    lambda r,p,e,t,c:c['source_lists'][0]['items'][1].update(evidence_ids=['E1']),
    lambda r,p,e,t,c:c['parts'][0].update(evidence_ids=['invented']),
    lambda r,p,e,t,c:t[0].update(text='First condition. [The rest was not provided.]'),
])
def test_aggregate_complete_cannot_override_missing_or_untraceable_parts(change):
    assert audit(change)['status']=='unresolved'


def test_identity_lookup_does_not_require_a_condition_list():
    def change(r,p,e,t,c):
        r['question']='定位这篇论文';c.update(enumeration_requested=False,source_lists=[])
        c['parts'][0]['request_quote']=r['question']
    assert audit(change)['status']=='supported'


def test_shown_notebook_quote_counts_but_its_unverified_commentary_does_not():
    def change(r,p,e,t,c):
        t[0].update(text='First condition.',source_notes=[dict(quote='Second condition.',note='An unverified explanation')])
    assert audit(change)['status']=='supported'
    def commentary_only(r,p,e,t,c):
        change(r,p,e,t,c);t[0]['source_notes'][0].update(quote='',note='Second condition.')
    assert audit(commentary_only)['status']=='unresolved'


def test_located_quote_in_audit_input_remains_readable_after_context_window_moves():
    def change(r,p,e,t,c):
        t[0]['text']='A different currently selected section.'
        for span in e:span.update(verification='quote_matched',quote_origin='source_text')
    assert audit(change)['status']=='supported'
    def bibliography_only(r,p,e,t,c):
        change(r,p,e,t,c)
        for span in e:span['quote_origin']='bibliography'
    assert audit(bibliography_only)['status']=='unresolved'


@pytest.mark.parametrize('count',[0,2])
def test_missing_or_duplicate_complete_answers_remain_unresolved(count):
    row,pool,spans,texts,check=inputs()
    assert coverage_scope.apply([row],[copy.deepcopy(check) for _ in range(count)],[pool],spans,texts)[0]['status']=='unresolved'


def test_invalid_coverage_ids_cannot_publish_the_unverified_positive_reason():
    row,pool,spans,texts,check=inputs()
    v=dict(question_id='Q1',status='supported',reason='An invented causal mechanism is proven.',evidence_ids=['invented'])
    result=research_contract.audit_coverage([pool],[v],spans)[0]
    assert result['status']=='unresolved' and 'invented causal' not in result['reason']
