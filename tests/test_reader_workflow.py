"""Reader tasks stay distinct from research hypotheses and internal audit records."""
import copy
import pytest
from backend import creative, materials, models, native_projection, research_contract, research_progress, source_context, store


def test_fresh_native_materials_do_not_inherit_old_audit_backlog():
    from backend import evidence_state
    a=planned_article();s=materials.source('Source','A supported finding.');a['sources']=[s]
    a['evidence']=dict(engine='wewrite-native',claims=[dict(id='C1',text='A supported finding',status='supported',source_ids=[s['id']])])
    a['research']=dict(superseded_by='native-result',policy_version=1,summary='old audit',issues=[dict(id='old',text='Old unresolved suggestion',kind='blocking',status='open',source_ids=[])])
    view=evidence_state.material_view(a)
    assert view['state']=='ready' and not view['pending']
    assert a['research']['issues'][0]['text']=='Old unresolved suggestion'
    a['research']['unassessed_source_ids']=['new']
    assert evidence_state.material_view(a)['state']=='new_materials'


@pytest.mark.anyio
async def test_native_exclusion_blocks_known_doi_alias_before_read(monkeypatch):
    from backend import native_runtime
    a=planned_article();s=materials.source('Excluded','PRIVATE_EXCLUDED_TEXT');s.update(selected=False,doi='10.1234/example',url='https://publisher.example/item')
    a['sources']=[s];j=store.create_job(a['id'],dict(stage='sources'))
    session=native_runtime.Session(a,j['id'],'sources',{})
    async def forbidden(*args,**kwargs):raise AssertionError('Excluded source must not be fetched')
    monkeypatch.setattr(materials,'from_url',forbidden)
    with pytest.raises(ValueError,match='排除'):await session.execute('WebFetch',dict(url='https://doi.org/10.1234/example'))


@pytest.mark.anyio
async def test_native_fulltext_reuse_keeps_explicit_refresh(monkeypatch):
    from backend import native_runtime
    a=planned_article();s=materials.source('Downloaded','Original full text.');s.update(status='retrieved',url='https://example.org/paper');a['sources']=[s]
    j=store.create_job(a['id'],dict(stage='sources'));session=native_runtime.Session(a,j['id'],'sources',{})
    session.state={'run_id':'test'};reads=[]
    async def fetch(url):reads.append(url);return dict(s,text='Updated full text.')
    monkeypatch.setattr(materials,'from_url',fetch)
    reused=await session.execute('WebFetch',dict(url=s['url']))
    assert reused['reused'] and not reads
    assert session.path(reused['path']).read_text('utf-8')==s['text']
    refreshed=await session.execute('WebFetch',dict(url=s['url'],refresh=True))
    assert reads==[s['url']] and session.path(refreshed['path']).read_text('utf-8')=='Updated full text.'


@pytest.mark.anyio
@pytest.mark.parametrize('fault',['','scope','answer'])
async def test_combined_review_retains_both_validators_without_duplicate_calls(monkeypatch,fault):
    from backend import research
    from tests.test_quality_discovery import worker
    from tests.quality_fixtures import notes,judgements,scope_audit,coverage_audit,answer_scope_audit
    w=worker();s=materials.source('Source','Direct observation.');w.a['sources']=[s];called=[]
    async def structured(a,stage,instruction,schema,job,candidates=None,questions=()):
        called.append(schema.__name__)
        if schema is models.ResearchNotes:
            return schema.model_validate(notes(a,dict(summary='Observation',evidence=[dict(source_id=s['id'],quote=s['text'],claim=s['text'])]))).model_dump()
        if schema is models.EvidenceJudgements:
            result=judgements(candidates,research_contract.ensure(a))
            for row,scope in zip(result['judgements'],scope_audit(candidates)['judgements']):row['scope_review']=scope
            if fault=='scope':result['judgements'][0]['scope_review']['scope']='mismatch'
        elif schema is models.CoverageAudit:
            result=coverage_audit(candidates)
            for row,scope in zip(result['coverage'],answer_scope_audit(candidates)['judgements']):row['answer_scope']=scope
            if fault=='answer':result['coverage'][0]['answer_scope']['complete']=False
        else:raise AssertionError('Unexpected duplicate review: '+schema.__name__)
        return schema.model_validate(result).model_dump()
    monkeypatch.setattr(research,'structured',structured)
    await w.assess()
    assert w.sufficient()==(not fault)
    assert called==['ResearchNotes','EvidenceJudgements']+(['CoverageAudit'] if fault!='scope' else [])


@pytest.mark.anyio
async def test_repeated_leads_stop_only_that_search_path(monkeypatch):
    from backend import research
    from tests.test_quality_discovery import worker
    w=worker();seen=[]
    research_contract.anchor_requirements(w.a,[dict(request_quote='scientific questions',question='Scientific questions')])
    first,second=[q['id'] for q in w.a['research_contract']['questions']]
    monkeypatch.setattr(research.search_plan,'channels',lambda *args:['native','pubmed','tavily','bing'])
    async def channel(name,query):
        seen.append((name,query))
        return [dict(url='https://example.org/already-checked')] if query=='duplicate' else []
    async def collect(*args,**kwargs):return 0
    async def assess():pass
    async def trace():pass
    monkeypatch.setattr(w,'channel',channel);monkeypatch.setattr(w,'collect',collect)
    monkeypatch.setattr(w,'assess',assess);monkeypatch.setattr(w,'trace_citations',trace)
    await w.discover([dict(query='duplicate',question_ids=[first]),dict(query='other question',question_ids=[second])])
    assert [name for name,q in seen if q=='duplicate']==['native','pubmed']
    assert [name for name,q in seen if q=='other question']==['native','pubmed','tavily','bing']
    assert w.query_ledger[0]['status']=='no_new_leads'


def test_question_cache_tracks_relevant_evidence_and_unscoped_warnings():
    from tests.quality_fixtures import assessment
    a=planned_article();contract=research_contract.ensure(a);q1,q2=contract['questions'][:2]
    span=lambda eid,q:dict(assessment(),evidence_id=eid,source_id='S'+eid,question_ids=[q['id']],quality='suitable',
        verification='quote_matched',source_type='original',adoption_reason='Direct evidence',use_scope='Study')
    old=span('E1',q1);unrelated=span('E2',q2);counter=span('E3',q1)
    row=dict(question_id=q1['id'],question=q1['text'],required=True,evidence_ids=['E1'],source_ids=['SE1'])
    rows=research_contract.audit_candidates(a,[row],[old,unrelated])
    assert rows[0]['candidate_evidence_ids']==['E1']
    value=dict(evidence=[old],rejected_evidence=[],reported_limits=dict(summary='stable',issues=[],gaps=[],conflicts=[]))
    key=research_contract.audit_key(contract,rows[0],value,{'SE1':'v1'})
    value['evidence'].append(unrelated)
    assert research_contract.audit_key(contract,rows[0],value,{'SE1':'v1','SE2':'v2'})==key
    value['reported_limits']['summary']='New unscoped warning'
    assert research_contract.audit_key(contract,rows[0],value,{'SE1':'v1'})!=key
    assert research_contract.audit_candidates(a,[row],[old,unrelated,counter])[0]['candidate_evidence_ids']==['E1','E3']


def test_current_task_hides_other_topics_and_excluded_proposals():
    a=planned_article();s=materials.source('Excluded study','EXCLUDED_TEXT');s['selected']=False;a['sources']=[s]
    a['creative_intent']['selected']['source_ids']=[s['id']]
    a['creative_intent']['adopted_plan']['source_ids']=[s['id']]
    a['creative_intent']['batches']=[dict(topics=[dict(title='UNRELATED_TOPIC')])]
    context=creative.task_context(a)
    assert 'UNRELATED_TOPIC' not in str(context) and '36 participants' not in str(context)
    assert context['selected']['reader_question']
    contract=research_contract.ensure(a)
    assert not contract['research_clues'] and '36 participants' not in contract['reader_value']


def test_prepared_materials_reuse_is_bound_to_content_and_reader_task():
    from backend import evidence_state
    a=planned_article();a['sources']=[materials.source('Current','Original text.')]
    a['evidence']=dict(engine='wewrite-native',claims=[dict(id='C1',text='Original finding')],gaps=[],
        prepared_sources=evidence_state.selected(a),prepared_objective=evidence_state.digest(evidence_state.objective(a)))
    assert native_projection.materials_prepared(a)
    same=copy.deepcopy(a);same['brief']['words']=1700
    assert native_projection.materials_prepared(same)
    changed=copy.deepcopy(a);changed['sources'][0]['text']='Changed text.'
    assert not native_projection.materials_prepared(changed)
    changed=copy.deepcopy(a);changed['brief']['topic']='Another reader question'
    assert not native_projection.materials_prepared(changed)
    changed=copy.deepcopy(a);changed['sources'].append(materials.source('New','New text.'))
    assert not native_projection.materials_prepared(changed)
    assert evidence_state.material_view(changed)['state']=='new_materials'


@pytest.mark.anyio
async def test_material_handoff_survives_save_and_reaches_outline_request():
    import json
    from backend import account_memory,native_runtime,native_workflow
    a=planned_article();source=materials.source('Original','A supported observation.')
    a=store.save_article(a['id'],a['revision'],lambda v:v.update(sources=[source]),'Fixture')
    j=store.create_job(a['id'],dict(stage='sources'))
    result=models.EvidenceResult(summary='An observation',claims=[dict(id='C1',text=source['text'],status='supported',type='fact',source_ids=[source['id']],boundary='')],gaps=[]).model_dump()
    packet=dict(result=result,claims=result,sources=[source],brief=native_projection.brief_from_article(a),native=dict(id='native-fixture'),account_use=account_memory.capture(a,j['id'],'sources'))
    a=native_workflow.apply(a,'sources',packet,dict(_job_id=j['id']))
    assert native_projection.materials_prepared(store.get_article(a['id']))
    store.update_job(j['id'],status='completed')
    next_job=store.create_job(a['id'],dict(stage='outline'))
    session=native_runtime.Session(a,next_job['id'],'outline',{})
    await session.prepare()
    request=json.loads((session.home/'request.json').read_text('utf-8'))
    assert request['completed_work']['materials']
    assert native_projection.mapping(session.directory/'claims.yaml')['claims'][0]['text']==source['text']


def planned_article():
    a=store.create_article(dict(topic='Compare two training exercises'))
    plan=models.Topic(id='T1',title=a['title'],angle='Compare the original two-group study',reason='A practical comparison',
        reader_question='How should a reader choose between the exercises?',
        takeaway='The preliminary report describes 36 participants',
        questions=['Does the finding apply to a different sport?']).model_dump()
    a['topics']=[plan];creative.adopt(a,plan['title'],'T1')
    research_contract.ensure(a)
    return a


def test_adopted_research_clue_binds_without_becoming_a_mandatory_fact():
    a=planned_article();before=copy.deepcopy(a['research_contract'])
    item=models.ResearchQuery(query='original exercise comparison',purpose='known_source',
        request_quote='The preliminary report describes 36 participants').model_dump()
    result=research_progress.bind_query(a,item,[])
    assert result is not None and result['question_ids']
    assert a['research_contract']==before
    assert not any(q['required'] and 'different sport' in q['text'] for q in before['questions'])


def test_valid_question_id_is_authoritative_over_a_paraphrased_quote():
    a=planned_article();qid=a['research_contract']['questions'][0]['id']
    item=models.ResearchQuery(query='direct comparison',question_ids=[qid],request_quote='A shorter paraphrase').model_dump()
    assert research_progress.bind_query(a,item,[])['question_ids']==[qid]


def test_unknown_query_cannot_expand_reader_requirements():
    a=planned_article();before=copy.deepcopy(a['research_contract'])
    assert research_progress.bind_query(a,models.ResearchQuery(query='unrelated',request_quote='Invented extra requirement').model_dump(),[]) is None
    assert a['research_contract']==before


def test_relevant_passage_is_not_displaced_by_generic_limitations():
    text='Introduction\n'+'background text. '*150+'\nLimitations\n'+'unrelated qualification. '*90
    text+='\nInstructions\n'+'TOMATO_RELEVANT cooking steps. '*75+'\nEnd\n'+'footnotes. '*210
    chunks=source_context.excerpts({'text':text},{'tomato_relevant'},limit=1800)
    assert any('TOMATO_RELEVANT' in c['text'] for c in chunks)
    assert sum(len(c['text']) for c in chunks)<=1800
    assert all(text[c['start']:c['end']]==c['text'] for c in chunks)


def test_native_claim_projection_keeps_scope_but_omits_audit_chatter():
    a=planned_article();s=materials.source('Study','Only adults were studied.');a['sources']=[s]
    a['evidence']=dict(summary='INTERNAL_AUDIT',claims=[dict(id='C1',text='Observed in adults',type='fact',source_ids=[s['id']],
        status='bounded',boundary='Adults',evidence=[dict(scope_alignment={'reason':'INTERNAL_AUDIT'})])])
    packet=native_projection.claims_from_article(a)
    assert packet['claims'][0]['boundary']=='Adults'
    assert set(packet['claims'][0])=={'id','text','type','source_ids','status','boundary'}
    assert 'INTERNAL_AUDIT' not in str(packet)
    s['selected']=False
    assert native_projection.claims_from_article(a)['claims']==[]


def test_proposed_takeaway_is_not_installed_as_a_verified_reader_conclusion():
    a=planned_article()
    brief=native_projection.brief_from_article(a)
    assert '36 participants' not in brief['goal']['takeaway']
    assert brief['audience']['question']==a['creative_intent']['selected']['reader_question']


@pytest.mark.anyio
async def test_native_preparation_separates_research_from_manuscript(tmp_path):
    from tests.test_native_runtime import session
    a=planned_article();s=materials.source('Study','An original observation.');a['sources']=[s]
    a['evidence']=dict(summary='AUDIT_SUMMARY',claims=[dict(id='C1',text='Observation',type='fact',source_ids=[s['id']],
        status='supported',boundary='Study population',evidence=[dict(reason='AUDIT_DETAILS')])])
    runner=session(a,'outline');await runner.prepare()
    manuscript=native_projection.mapping(runner.directory/'claims.yaml')
    assert manuscript['claims']==[]
    reference=native_projection.mapping(runner.home/'research-evidence.yaml')
    assert reference['claims'][0]['text']=='Observation'
    assert 'AUDIT_DETAILS' not in str(reference)
    request=native_projection.mapping(runner.home/'request.json')
    assert 'batches' not in request['creative_intent']


@pytest.fixture
def anyio_backend():return 'asyncio'
