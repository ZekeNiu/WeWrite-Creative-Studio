import copy
from backend import research
from backend import research_contract


def test_independent_audit_preserves_read_material_without_prior_ai_verdicts(monkeypatch):
    shown=dict(current_date='2026-01-01',brief={'topic':'User requirement'},research_contract={'questions':[{'text':'Original requirement'}]},
        sources=[dict(id='S1',text='Complete actually shown passage.',bibliography={'title':'Original'},excerpts=[{'start':20,'end':53}],
                      evidence_spans=[{'support':'supported','claim':'A previous false claim'}],
                      source_notes=[{'quote':'An exact original note.','note':'A previous inference','status':'verified'}]),
                 dict(id='S2',text='An unrelated source.')],
        evidence={'claims':['An old accepted claim']},issue_decisions=['Old automatic conclusion'])
    before=copy.deepcopy(shown)
    monkeypatch.setattr(research,'context',lambda *args:copy.deepcopy(shown))
    value=research.audit_context({},'sources',source_ids={'S1'})
    assert value['brief']==shown['brief'] and value['research_contract']==shown['research_contract']
    assert value['sources']==[dict(id='S1',text='Complete actually shown passage.',bibliography={'title':'Original'},excerpts=[{'start':20,'end':53}],source_notes=[{'quote':'An exact original note.'}])]
    assert 'evidence' not in value and 'issue_decisions' not in value
    assert shown==before
    assert len(research.audit_context({},'sources')['sources'])==2


def test_primary_only_questions_do_not_receive_secondary_selectable_ids():
    rows=[dict(question_id='required',candidate_evidence_ids=['primary']),dict(question_id='also_required',candidate_evidence_ids=['primary']),
          dict(question_id='optional',candidate_evidence_ids=['primary','secondary']),dict(question_id='empty',candidate_evidence_ids=[])]
    value=dict(coverage=rows,evidence=[dict(evidence_id='primary'),dict(evidence_id='secondary')],reported_limits={'gaps':['Keep a real missing requirement.']})
    groups=research_contract.audit_groups(value)
    assert len(groups)==2
    assert [r['question_id'] for r in groups[0]['coverage']]==['required','also_required']
    assert groups[0]['evidence']==[dict(evidence_id='primary')]
    assert groups[1]['evidence']==value['evidence']
    assert all(g['reported_limits']==value['reported_limits'] for g in groups)
    assert len(value['coverage'])==4 and len(value['evidence'])==2
