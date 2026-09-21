"""Explicit synthetic independent-verification replies for workflow tests."""
from backend.research_contract import CHECKS,ensure


def assessment():
    return dict(assessment_version=1,support='supported',support_basis='observed',support_reason='Synthetic direct support',support_checks=dict.fromkeys(CHECKS,'matched'))


def judgements(candidates,contract):
    return dict(judgements=[dict(evidence_id=e['evidence_id'],support='supported',basis='observed',reason='Synthetic direct support',
                    checks=dict.fromkeys(CHECKS,'matched'),question_ids=[q['id'] for q in contract['questions']]) for e in candidates])


def notes(a,result):
    contract=ensure(a)
    result['coverage']=[dict(question_id=q['id'],status='supported',reason='Synthetic covered question') for q in contract['questions']]
    for e in result.get('evidence',[]):
        for key,value in dict(source_type='original',adoption_reason='Synthetic evidence',use_scope='Study',quality='suitable').items():
            if not e.get(key):e[key]=value
        if e.get('quality')=='unassessed':e['quality']='suitable'
    return result
