"""Synthetic regressions for evidence-led stopping and dependency-bound reuse."""
import asyncio
import copy
import json
import pytest
from backend import research, research_contract, materials, models, source_notebook, store, providers, evidence_state, workflow, flow_state
from tests.test_quality_discovery import worker
from tests.quality_fixtures import notes, judgements, scope_audit, coverage_audit, answer_scope_audit


def model(monkeypatch, drafts, checked):
    async def structured(a,stage,instruction,schema,job,candidates=None,questions=()):
        if schema is models.ResearchNotes:
            drafts.append([s['id'] for s in a['sources'] if s.get('selected')])
            return schema.model_validate(notes(a,dict(summary='Synthetic observations',evidence=[
                dict(source_id=s['id'],quote=s['text'],claim=s['text']) for s in a['sources'] if s.get('selected')]))).model_dump()
        if schema is models.EvidenceJudgements:
            checked.extend(e['source_id'] for e in candidates)
            return judgements(candidates,a['research_contract'])
        if schema is models.EvidenceScopeAudit:return scope_audit(candidates)
        if schema is models.CoverageAudit:return coverage_audit(candidates)
        if schema is models.AnswerScopeAudit:return answer_scope_audit(candidates)
        raise AssertionError(schema.__name__)
    monkeypatch.setattr(research,'structured',structured)


def test_deferred_no_gain_preserves_remaining_candidates(monkeypatch):
    w=worker();research_contract.ensure(w.a);seen=[]
    w.deferred=[dict(url=f'https://example.org/{i}',query='same gap') for i in range(20)]
    async def collect(rows,*args,**kwargs):seen.extend(r['url'] for r in rows);return 0
    async def assess():pass
    monkeypatch.setattr(w,'collect',collect);monkeypatch.setattr(w,'assess',assess)
    asyncio.run(w.drain_candidates())
    assert len(seen)==2 and len(w.deferred)==18
    assert w.convergence['state']=='needs_material'


def test_additional_source_is_not_itself_evidence_progress():
    w=worker();research_contract.ensure(w.a);before=w.progress_key()
    w.a['sources'].append(materials.source('Irrelevant background','Background only.'))
    assert w.progress_key()==before


def test_incremental_notes_keep_old_verified_evidence(monkeypatch):
    w=worker();first=materials.source('First','Observation one.');second=materials.source('Second','Observation two.')
    w.a['sources']=[first];drafts=[];checked=[];model(monkeypatch,drafts,checked)
    asyncio.run(w.assess());old=copy.deepcopy(w.notes['evidence'][0])
    w.a['sources'].append(second);asyncio.run(w.assess())
    assert drafts==[[first['id']],[second['id']]]
    assert checked==[first['id'],second['id']]
    assert next(e for e in w.notes['evidence'] if e['source_id']==first['id'])==old
    assert len(w.notes['evidence'])==2


def test_changed_source_rechecks_only_its_own_evidence(monkeypatch):
    w=worker();a=materials.source('A','Original A.');b=materials.source('B','Original B.');w.a['sources']=[a,b]
    drafts=[];checked=[];model(monkeypatch,drafts,checked)
    asyncio.run(w.assess());a['text']='Corrected A.';asyncio.run(w.assess())
    assert drafts[-1]==[a['id']]
    assert checked==[a['id'],b['id'],a['id']]
    assert {e['claim'] for e in w.notes['evidence']}=={'Corrected A.','Original B.'}


def test_resume_reuses_verified_checkpoint_and_downloaded_material(monkeypatch):
    w=worker();s=materials.source('Downloaded','Direct observation.');w.a['sources']=[s];w.added=[s]
    drafts=[];checked=[];model(monkeypatch,drafts,checked)
    asyncio.run(w.assess());w.update('saved checkpoint');store.update_job(w.job_id,status='cancelled')
    current=store.get_article(w.a['id']);j=store.create_job(current['id'],dict(stage='research',research_parent_id=w.job_id))
    resumed=research.Research(current,j['id'],'sources');asyncio.run(resumed.assess())
    assert [x['id'] for x in resumed.a['sources']]==[s['id']]
    assert checked==[s['id']] and len(drafts)==1
    assert resumed.notes['evidence']==w.notes['evidence']


def test_same_section_request_is_not_new_reading():
    s=materials.source('Study','Methods\nFirst observation.\nResults\nSecond observation.\nLimitations\nThird observation.')
    a=dict(sources=[s]);sections=source_notebook.sections(s)
    req=lambda section:dict(source_id=s['id'],section_id=section['id'],reason='Locate original')
    for section in sections:assert source_notebook.request_reads(a,[req(section)])
    assert not source_notebook.request_reads(a,[req(sections[0])])


def test_reworded_search_does_not_restart_same_exhausted_purpose(monkeypatch):
    w=worker();q=research_contract.ensure(w.a)['questions'][0]['id'];searched=[]
    monkeypatch.setattr(research.search_plan,'channels',lambda *args:['native'])
    async def channel(name,query):searched.append(query);return []
    monkeypatch.setattr(w,'channel',channel)
    first=dict(query='original phrasing',question_ids=[q],expected_gain='Locate direct answer')
    asyncio.run(w.discover([first]));asyncio.run(w.discover([dict(first,query='different phrasing')]))
    assert searched==['original phrasing']


def test_search_selection_does_not_receive_all_source_text(monkeypatch):
    w=worker();research_contract.ensure(w.a);s=materials.source('Existing','UNRELATED_FULL_TEXT '*1000);w.a['sources']=[s]
    seen=[]
    monkeypatch.setattr(providers,'service_for',lambda *a:dict(protocol='responses',model='synthetic'))
    async def generate(service,system,prompt,emit=None):
        seen.append(json.loads(prompt));return '{"urls":[]}',dict(model='synthetic',status='completed')
    monkeypatch.setattr(providers,'generate',generate)
    asyncio.run(research.structured(w.a,'research','Choose candidates',models.SearchSelection,w.job_id,[]))
    assert 'UNRELATED_FULL_TEXT' not in json.dumps(seen)


def test_covered_problem_skips_other_channels(monkeypatch):
    w=worker();q=research_contract.ensure(w.a)['questions'][0]['id'];seen=[]
    monkeypatch.setattr(research.search_plan,'channels',lambda *a:['native','pubmed','tavily'])
    async def channel(name,query):seen.append(name);return [dict(url='https://example.org/proof')]
    async def collect(*args,**kwargs):return 1
    async def assess():w.coverage=[dict(question_id=q,required=True,status='supported',evidence_ids=['E1'])]
    monkeypatch.setattr(w,'channel',channel);monkeypatch.setattr(w,'collect',collect);monkeypatch.setattr(w,'assess',assess)
    asyncio.run(w.discover([dict(query='direct question',question_ids=[q],expected_gain='Answer core')]))
    assert seen==['native']


def test_planned_counterevidence_is_checked_before_ready(monkeypatch):
    w=worker();qid=research_contract.ensure(w.a)['questions'][0]['id'];seen=[]
    monkeypatch.setattr(research.search_plan,'channels',lambda *a:['native','tavily'])
    async def channel(name,query):seen.append(query);return [dict(url='https://example.org/'+query)]
    async def collect(*args,**kwargs):return 1
    async def assess():w.coverage=[dict(question_id=qid,required=True,status='supported',evidence_ids=['E1'])]
    monkeypatch.setattr(w,'channel',channel);monkeypatch.setattr(w,'collect',collect);monkeypatch.setattr(w,'assess',assess)
    asyncio.run(w.discover([dict(query='support',question_ids=[qid]),dict(query='counter',question_ids=[qid],purpose='counterevidence')]))
    assert seen==['support','counter']


def test_no_evidence_handoff_stops_even_with_automatic_continuation(monkeypatch):
    w=worker();request=models.JobRequest(stage='research',revision=w.a['revision'],chain=True)
    store.update_job(w.job_id,status='completed')
    j=store.create_job(w.a['id'],request.model_dump())
    async def gather(*args,**kwargs):return w.a,True
    async def forbidden(*args,**kwargs):raise AssertionError('Unresolved evidence must not advance the chain')
    monkeypatch.setattr(research,'gather',gather);monkeypatch.setattr(workflow.native_runtime,'generate',forbidden)
    asyncio.run(workflow.run(j['id']))
    result=store.job(j['id'])
    assert result['status']=='needs_input' and result['waiting_for_materials']


def test_changed_boundary_in_saved_evidence_cannot_reuse_old_verdict(monkeypatch):
    w=worker();s=materials.source('A','Observation in the original population.');w.a['sources']=[s]
    drafts=[];checked=[];model(monkeypatch,drafts,checked);asyncio.run(w.assess())
    a=copy.deepcopy(w.a);a['research']=dict(job_id=w.job_id,analysis_state=w.analysis_state,coverage=w.coverage)
    a['evidence']=dict(claims=evidence_state.merge_claims(a,w.notes['evidence']))
    a['evidence']['claims'][0]['evidence'][0]['boundary']='A newly changed limitation.'
    store.update_job(w.job_id,status='completed')
    j=store.create_job(a['id'],dict(stage='research'));resumed=research.Research(a,j['id'],'sources')
    asyncio.run(resumed.assess())
    assert checked==[s['id'],s['id']]
    assert resumed.notes['evidence'][0]['evidence_id']!=w.notes['evidence'][0]['evidence_id']


def test_applied_checkpoint_does_not_restore_user_deleted_source(monkeypatch):
    w=worker();s=materials.source('Downloaded','Direct observation.');w.a['sources']=[s];w.added=[s]
    drafts=[];checked=[];model(monkeypatch,drafts,checked);asyncio.run(w.assess());w.update('checkpoint')
    store.update_job(w.job_id,status='completed')
    current=store.get_article(w.a['id']);current['research']=dict(job_id=w.job_id,analysis_state=w.analysis_state)
    j=store.create_job(current['id'],dict(stage='research',research_parent_id=w.job_id))
    resumed=research.Research(current,j['id'],'sources')
    assert not resumed.a['sources'] and not resumed.notes['evidence']


def test_interrupted_batch_retains_last_verified_checkpoint(monkeypatch):
    w=worker();s=materials.source('First','Verified observation.');w.a['sources']=[s]
    drafts=[];checked=[];model(monkeypatch,drafts,checked);asyncio.run(w.assess())
    saved=copy.deepcopy(w.analysis_state)
    w.a['sources'].append(materials.source('New','New unverified observation.'))
    original=research.structured
    async def cancelled(a,stage,instruction,schema,*args,**kwargs):
        if schema is models.EvidenceJudgements:raise asyncio.CancelledError()
        return await original(a,stage,instruction,schema,*args,**kwargs)
    monkeypatch.setattr(research,'structured',cancelled)
    with pytest.raises(asyncio.CancelledError):asyncio.run(w.assess())
    assert w.analysis_state==saved


def test_retry_uses_checkpoint_in_a_new_job_without_cross_article_recovery(monkeypatch):
    w=worker();s=materials.source('A','Observation.');w.a['sources']=[s];w.added=[s]
    drafts=[];checked=[];model(monkeypatch,drafts,checked);asyncio.run(w.assess());w.update('checkpoint')
    store.update_job(w.job_id,status='failed')
    req=flow_state.retry_request(store.job(w.job_id),w.a['revision'])
    assert req['research_parent_id']==w.job_id and not req['chain']
    async def finish(jid):store.update_job(jid,status='completed');workflow.TASKS.pop(jid,None)
    monkeypatch.setattr(workflow,'run',finish)
    async def start():
        result=workflow.start(w.a['id'],models.JobRequest.model_validate(req));await asyncio.sleep(0);return result
    new=asyncio.run(start());assert new['id']!=w.job_id
    other=store.create_article(dict(topic='Other article'))
    with pytest.raises(ValueError):workflow.start(other['id'],models.JobRequest(stage='research',revision=other['revision'],research_parent_id=w.job_id))


def test_unknown_planner_question_never_creates_a_new_requirement(monkeypatch):
    w=worker();before=copy.deepcopy(research_contract.ensure(w.a))
    async def forbidden(*args,**kwargs):raise AssertionError('Unbound planner task must not execute')
    monkeypatch.setattr(w,'channel',forbidden)
    asyncio.run(w.discover([dict(query='invented extra',question_ids=['not-a-user-question'])]))
    assert w.a['research_contract']==before


def test_new_conflicting_source_reopens_coverage_without_reauditing_old_span(monkeypatch):
    w=worker();a=materials.source('A','Positive observation.');b=materials.source('B','Conflicting observation.')
    w.a['sources']=[a];drafts=[];checked=[];model(monkeypatch,drafts,checked)
    original=research.structured
    async def conflicting(article,stage,instruction,schema,*args,**kwargs):
        result=await original(article,stage,instruction,schema,*args,**kwargs)
        if schema is models.CoverageAudit and len(w.a['sources'])==2:
            for row in result['coverage']:row.update(status='unresolved',reason='The directly conflicting studies require interpretation')
        return result
    monkeypatch.setattr(research,'structured',conflicting)
    asyncio.run(w.assess());assert w.sufficient()
    w.a['sources'].append(b);asyncio.run(w.assess())
    assert not w.sufficient() and checked==[a['id'],b['id']]
    assert len(w.notes['evidence'])==2


@pytest.mark.parametrize('expand',[False,True])
def test_saved_contract_and_checkpoint_keep_the_same_requirements(monkeypatch,expand):
    from backend import research_progress
    w=worker()
    async def run(self,query=''):
        research_contract.anchor_requirements(self.a,[dict(request_quote='scientific questions',question='Explain the requested scientific questions')])
        self.notes=models.ResearchNotes(summary='Unresolved',evidence=[]).model_dump()
        if expand:self.notes['intent']=models.Topic(title='Synthetic expansion',angle='Explain the question',reason='Synthetic').model_dump()
        self.analysis_state=dict(signature=research.analysis_signature(),objective=research_contract.objective(self.a),
            demand=research_progress.demand(self.a,query),contract=copy.deepcopy(self.a['research_contract']))
        return True
    monkeypatch.setattr(research.Research,'run',run)
    saved,pending=asyncio.run(research.gather(w.a,w.job_id,'research'))
    expected=copy.deepcopy(saved['research_contract'])
    assert expected['requirements_anchored'] and pending
    assert research_contract.ensure(saved)==expected
    assert saved['research']['analysis_state']['objective']==research_contract.objective(saved)
    assert saved['research']['analysis_state']['demand']==research_progress.demand(saved,'')


def test_targeted_recheck_does_not_reextract_unrelated_sources(monkeypatch):
    w=worker();a=materials.source('A','First observation.');b=materials.source('B','Second observation.');w.a['sources']=[a,b]
    drafts=[];checked=[];model(monkeypatch,drafts,checked);asyncio.run(w.assess())
    current=copy.deepcopy(w.a);current['evidence']=dict(claims=evidence_state.merge_claims(current,w.notes['evidence']))
    current['research']=dict(job_id=w.job_id,analysis_state=w.analysis_state,coverage=w.coverage,issues=[dict(id='I1',text='Check the first observation',
        kind='blocking',claim='First observation.',source_ids=[a['id']],status='open')])
    store.update_job(w.job_id,status='completed')
    j=store.create_job(current['id'],dict(stage='research',issue_ids=['I1']))
    resumed=research.Research(current,j['id'],'research');resumed.requirements='Only verify I1'
    asyncio.run(resumed.assess())
    assert all(ids==[a['id']] for ids in drafts[1:])
    assert checked.count(b['id'])==1


def test_targeted_new_counterevidence_reopens_another_affected_question(monkeypatch):
    w=worker();research_contract.anchor_requirements(w.a,[dict(request_quote='scientific questions',question='The requested science')])
    questions=w.a['research_contract']['questions'];target,affected=[q['id'] for q in questions]
    w.a['sources']=[materials.source('Original','Original observation.')]
    drafts=[];checked=[];model(monkeypatch,drafts,checked);asyncio.run(w.assess())
    w.a['research']=dict(issues=[dict(id='I1',question_id=target,text='Verify the target',kind='blocking',status='open',source_ids=[],claim='')])
    w.requested=['I1'];w.a['sources'].append(materials.source('Counterevidence','A directly conflicting observation.'))
    original=research.structured
    async def conflicting(a,stage,instruction,schema,*args,**kwargs):
        value=await original(a,stage,instruction,schema,*args,**kwargs)
        if schema is models.CoverageAudit:
            for row in value['coverage']:
                if row['question_id']==affected:row.update(status='unresolved',reason='Conflicting direct evidence')
        return value
    monkeypatch.setattr(research,'structured',conflicting);asyncio.run(w.assess())
    assert next(r for r in w.coverage if r['question_id']==affected)['status']=='unresolved'


def test_user_retry_can_repeat_a_search_interrupted_before_a_result(monkeypatch):
    w=worker();qid=research_contract.ensure(w.a)['questions'][0]['id'];seen=[]
    item=dict(query='exact query',question_ids=[qid],purpose='explore')
    w.actions=[dict(key=w.action_key(item,'native'),status='started')]
    monkeypatch.setattr(research.search_plan,'channels',lambda *a:['native'])
    async def channel(name,query):seen.append(query);return []
    monkeypatch.setattr(w,'channel',channel);asyncio.run(w.discover([item]))
    assert seen==['exact query'] and w.actions[-1]['status']=='no_gain'


def test_targeted_save_keeps_related_new_evidence_and_unrelated_claims(monkeypatch):
    w=worker();s=materials.source('Original','Original observation.');other=materials.source('Unrelated','Unrelated observation.');w.a['sources']=[s,other]
    drafts=[];checked=[];model(monkeypatch,drafts,checked);asyncio.run(w.assess())
    original=w.notes['evidence'][0]
    def seed(a):
        a['sources']=[s,other];a['evidence']=dict(claims=evidence_state.merge_claims(a,w.notes['evidence']))
        a['research']=dict(issues=[dict(id='I1',text='Verify original',claim=original['claim'],kind='blocking',status='open',source_ids=[s['id']])])
    a=store.save_article(w.a['id'],w.a['revision'],seed,'Synthetic fixture')
    store.update_job(w.job_id,status='completed')
    j=store.create_job(a['id'],dict(stage='research',issue_ids=['I1']))
    async def run(self,query=''):
        counter=materials.source('Counterevidence','A contrary observation.')
        self.a['sources'].append(counter);self.added.append(counter)
        self.notes=models.ResearchNotes(summary='Counterevidence',evidence=[dict(source_id=counter['id'],quote=counter['text'],claim=counter['text'])]).model_dump()
        self.notes=research.validate_spans(self.notes,self.a['sources'])
        return True
    monkeypatch.setattr(research.Research,'run',run)
    saved,_=asyncio.run(research.gather(a,j['id'],'research'))
    assert 'A contrary observation.' in {e['claim'] for e in saved['research']['evidence']}
    assert len(saved['evidence']['claims'])==3
    assert saved['evidence']['claims'][1]==a['evidence']['claims'][1]
