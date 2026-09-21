"""Counterexamples from the read-only audit; no network or personal data."""
import asyncio
import copy
import pytest
from backend import research,materials,source_reader,evidence_state,store
from backend import research_contract


def evidence(s,**changes):
    return dict(source_id=s['id'],quote='The experiment lacks a control group.',claim='随机对照试验证明因果效果',
                source_type='original study',adoption_reason='Primary source',use_scope='Adults',quality='suitable',
                core_claim=True,**changes)


def test_missing_core_quote_is_not_an_ordinary_limitation():
    s=materials.source('Study','Background only.')
    result=research.validate_spans(dict(evidence=[evidence(s)],gaps=[],issues=[]),[s])
    assert result['issues'][0]['kind']=='blocking'


def test_quote_location_alone_cannot_establish_support():
    s=materials.source('Study','The experiment lacks a control group.')
    result=research.validate_spans(dict(evidence=[evidence(s)],gaps=[],issues=[]),[s])
    assert result['evidence'][0]['verification']=='quote_matched'
    assert not evidence_state.assessed(result['evidence'][0])


def test_exact_bibliographic_title_can_identify_a_work_without_rewriting_original():
    title='Synthetic Review of Training Programmes'
    s=materials.source(title,'Research question: a synthetic abstract.')
    s.update(status='abstract_only',bibliography=dict(title=title,doi='10.1234/synthetic'))
    raw=dict(evidence(s),quote=title,claim='论文题名为 Synthetic Review of Training Programmes。')
    result=research.validate_spans(dict(evidence=[raw],gaps=[],issues=[]),[s])
    e=result['evidence'][0]
    assert e['quote_origin']=='bibliography' and e['offset'] is None and '书目' in e['location']
    assert s['text']=='Research question: a synthetic abstract.'
    assert not evidence_state.assessed(e)
    verdict=dict(evidence_id=e['evidence_id'],support='supported',basis='not_applicable',identity_only=True,source_origin='primary',
        reason='The title matches the supplied bibliographic record',checks=dict.fromkeys(research_contract.CHECKS,'not_applicable'),question_ids=[])
    research_contract.apply_judgements([e],[verdict])
    assert evidence_state.assessed(e)


def test_bibliographic_quote_cannot_establish_an_experimental_result():
    title='A Programme Prevents All Injuries'
    s=materials.source(title,'The actual study only describes a protocol.')
    s.update(status='abstract_only',bibliography=dict(title=title))
    raw=dict(evidence(s),quote=title,claim='实验证明能预防所有损伤')
    result=research.validate_spans(dict(evidence=[raw],gaps=[],issues=[]),[s]);e=result['evidence'][0]
    verdict=dict(evidence_id=e['evidence_id'],support='supported',basis='observed',identity_only=False,source_origin='primary',
        reason='A heading is not an experimental result',checks=dict.fromkeys(research_contract.CHECKS,'matched'),question_ids=[])
    research_contract.apply_judgements([e],[verdict])
    assert not evidence_state.assessed(e)
    assert evidence_state.evaluated(e)


def test_identity_only_evidence_cannot_complete_a_content_question():
    span=dict(evidence_id='E1',source_id='S1',quote_origin='bibliography')
    row=dict(question_id='Q1',required=True,status='unresolved',reason='',evidence_ids=[],candidate_evidence_ids=['E1'],source_ids=[])
    verdict=dict(question_id='Q1',status='supported',reason='Bibliographic identity found',evidence_ids=['E1'])
    assert not research_contract.sufficient(research_contract.audit_coverage([row],[verdict],[span]))
    accepted=research_contract.audit_coverage([row],[dict(verdict,requires_source_content=False)],[span])
    assert research_contract.sufficient(accepted)


def test_unmatched_bibliographic_title_remains_a_core_gap():
    s=materials.source('Actual title','Original abstract.')
    s.update(status='abstract_only',bibliography=dict(title='Actual title'))
    result=research.validate_spans(dict(evidence=[dict(evidence(s),quote='Invented title')],gaps=[],issues=[]),[s])
    assert not result['evidence'] and result['issues'][0]['kind']=='blocking'


def test_system_core_gap_survives_model_issue_list():
    a=store.create_article({'topic':'核心疗效'})
    notes=dict(evidence=[],issues=[dict(id='L1',text='小样本',kind='limitation',source_ids=[],status='open')],
               gaps=['核心依据尚未找到'],conflicts=[])
    assert any(i['kind']=='blocking' and i['text']=='核心依据尚未找到' for i in evidence_state.merge_issues(a,notes))


def test_scholarly_dynamic_abstract_never_becomes_fulltext():
    from backend.materials import from_dynamic
    s=from_dynamic(dict(title='A scientific abstract',url='https://pubmed.ncbi.nlm.nih.gov/123/',text='Abstract\n'+('Results summary. '*700)))
    assert s['status']=='abstract_only'


def test_verified_copy_cannot_be_relabelled_as_another_work(monkeypatch):
    a=store.create_article({'topic':'Study A'})
    j=store.create_job(a['id'],dict(stage='research',revision=0))
    w=research.Research(a,j['id'],'research')
    arow=dict(title='Study A',doi='10.1234/a',url='https://example.org/a',academic=True,provider='test',
              bibliography={'title':'Study A','doi':'10.1234/a'},fulltext_urls=['https://example.org/b'])
    b=materials.source('Study B','Methods\n'+('Results of B. '*600),'https://example.org/b','web')
    b.update(doi='10.1234/b',bibliography={'title':'Study B','doi':'10.1234/b'},identity_verified=True)
    async def yes(*args):return True
    async def fetch(*args):return copy.deepcopy(b)
    async def missing(*args):raise ValueError('metadata unavailable')
    monkeypatch.setattr(research.browser_search,'public_url',yes)
    monkeypatch.setattr(w,'fetch',fetch)
    monkeypatch.setattr(research.academic,'lookup_doi',missing)
    result=asyncio.run(w.read(arow))
    assert result['status']!='retrieved'
    assert 'Results of B.' not in result['text']
    assert not result.get('identity_verified')


def test_contract_retains_user_question_when_planner_only_offers_background():
    a=store.create_article({'topic':'某种干预能否降低损伤','purpose':'需要随机试验核实疗效'})
    c=research_contract.ensure(a,['什么是损伤'])
    assert '随机试验' in c['questions'][0]['text']
    assert research_contract.ensure(a,['另一个简单问题'])==c


def test_background_and_manual_exclusion_do_not_establish_full_coverage():
    a=store.create_article({'topic':'干预是否有效'})
    c=research_contract.ensure(a,['有何反证'])
    q=c['questions'][0]['id'];a['research_decisions']={q:{'handling':'excluded'}}
    rows=research_contract.coverage(a,dict(evidence=[],coverage=[dict(question_id=q,status='supported',reason='想继续写')]))
    assert not research_contract.sufficient(rows)
    assert rows[0]['status']=='unresolved'


@pytest.mark.parametrize('field',research_contract.CHECKS)
def test_mismatched_population_design_denominator_outcome_causality_or_scope_cannot_pass(field):
    s=materials.source('Study','The experiment lacks a control group.')
    e=research.validate_spans(dict(evidence=[evidence(s)],gaps=[],issues=[]),[s])['evidence'][0]
    checks=dict.fromkeys(research_contract.CHECKS,'matched');checks[field]='mismatch'
    research_contract.apply_judgements([e],[dict(evidence_id=e['evidence_id'],support='supported',reason='冲突应拒绝',checks=checks,question_ids=[])])
    assert not evidence_state.assessed(e)


def test_complete_independent_support_and_coverage_are_required():
    a=store.create_article({'topic':'这个实验有对照组吗'})
    q=research_contract.ensure(a)['questions'][0]['id']
    s=materials.source('Study','The experiment lacks a control group.')
    raw=evidence(s);raw['claim']='该实验没有对照组'
    notes=research.validate_spans(dict(evidence=[raw],gaps=[],issues=[]),[s]);e=notes['evidence'][0]
    research_contract.apply_judgements([e],[dict(evidence_id=e['evidence_id'],support='supported',basis='observed',reason='原文明确无对照组',checks=dict.fromkeys(research_contract.CHECKS,'matched'),question_ids=[q])])
    assert evidence_state.assessed(e)
    notes['coverage']=[dict(question_id=q,status='supported',reason='确认研究设计')]
    assert research_contract.sufficient(research_contract.coverage(a,notes))


def test_analysis_cache_changes_when_research_model_changes(monkeypatch):
    monkeypatch.setattr(research.providers,'service_for',lambda stage:dict(id='one',model='first',base_url='https://example.org',protocol='chat',secret=''))
    first=research.analysis_signature()
    monkeypatch.setattr(research.providers,'service_for',lambda stage:dict(id='one',model='second',base_url='https://example.org',protocol='chat',secret=''))
    assert research.analysis_signature()!=first


def test_long_structured_abstract_is_not_fulltext(monkeypatch):
    html=('<html><head><meta name="citation_doi" content="10.1234/a"><meta name="citation_journal_title" content="Journal"></head>'
          '<body><article><section id="Abstract"><h2>Methods</h2><p>'+('Summary only. '*500)+'</p><h2>Results</h2></section></article></body></html>')
    async def fetch(url):return html.encode(),'https://example.org/a'
    monkeypatch.setattr(materials,'fetch_bytes',fetch)
    assert asyncio.run(materials.read_url('https://example.org/a'))['status']=='abstract_only'


def test_coverage_resolves_only_its_system_issue_and_preserves_manual_decision():
    rows=[dict(id='Q1',question_id='Q1',system_kind='coverage',status='open'),
          dict(id='Q2',question_id='Q2',system_kind='coverage',status='bounded')]
    covered=[dict(question_id=q,status='supported',evidence_ids=['E1'],reason='Read original',source_ids=['S1']) for q in ('Q1','Q2')]
    result=research_contract.resolve_issues(rows,covered)
    assert result[0]['status']=='resolved' and result[1]['status']=='bounded'


def test_planner_curiosity_does_not_expand_mandatory_user_goal():
    a=store.create_article({'topic':'核实研究对象'})
    c=research_contract.ensure(a,['还可以查每个作者的机构'])
    assert c['questions'][0]['required'] and not c['questions'][1]['required']


def test_authors_explanation_is_not_reported_as_measured_mechanism():
    s=materials.source('Study','The experiment lacks a control group.')
    e=research.validate_spans(dict(evidence=[evidence(s)],gaps=[],issues=[]),[s])['evidence'][0]
    research_contract.apply_judgements([e],[dict(evidence_id=e['evidence_id'],support='supported',basis='author_interpretation',reason='作者解释',checks=dict.fromkeys(research_contract.CHECKS,'matched'))])
    assert e['support']=='limited' and e['type']=='inference' and '不能当作本研究直接验证' in e['boundary']
