"""Isolated regression cases for intent, scoped verification, and public full text."""
import asyncio
import copy
import json
import pytest
from backend import store,creative,evidence_state,research,materials,source_reader,academic,prompts,issue_actions
from tests.test_studio import client,model,new,patch,run,H
from tests.quality_fixtures import assessment,judgements,notes as quality_notes


def seeded(client):
    a=new(client)
    def fill(v):
        v['sources']=[dict(materials.source('原文 '+str(i),'Original evidence '+str(i)),id='S'+str(i)) for i in (1,2)]
        v['evidence']=dict(summary='已有结论',claims=[dict(id='C'+str(i),text='主张'+str(i),source_ids=['S'+str(i)],status='supported',type='inference',evidence=[dict(claim_id='C'+str(i),source_id='S'+str(i),quote='Original evidence '+str(i),claim='主张'+str(i),quality='suitable',verification='quote_matched',source_type='original',adoption_reason='direct',use_scope='study')]) for i in (1,2)])
        v['research']=dict(policy_version=3,summary='当前结论',pending=False,stale=False,evidence=[],issues=[dict(id='Q'+str(i),text='问题'+str(i),claim='主张'+str(i),claim_id='C'+str(i),kind='blocking',source_ids=['S'+str(i)],status='resolved',resolution='已核实') for i in (1,2)])
        for c in v['evidence']['claims']:
            for e in c['evidence']:e.update(assessment())
        v['stages']['sources']='done'
    return store.save_article(a['id'],a['revision'],fill,'fixture')


@pytest.mark.parametrize('field,value',[('words',4000),('persona','cold-analyst'),('tone','简洁')])
def test_expression_does_not_reopen_evidence(client,field,value):
    a=seeded(client)
    a=patch(client,a,{'brief':dict(a['brief'],**{field:value})},'setup')
    assert a['materials_state']['ready'] and not a['research']['stale']
    assert all(q['status']=='resolved' for q in a['research']['issues'])


def test_unselected_new_material_and_related_source_deletion(client):
    a=seeded(client)
    a=store.save_article(a['id'],a['revision'],lambda v:v['sources'].append(dict(materials.source('无关','旁支'),selected=False)),'fixture')
    assert a['materials_state']['ready']
    a=patch(client,a,{'sources':[s for s in a['sources'] if s['id']!='S1']},'sources')
    q={q['id']:q for q in a['research']['issues']}
    assert q['Q1']['status']=='stale' and q['Q2']['status']=='resolved'
    assert a['evidence']['claims'][0]['stale'] and not a['evidence']['claims'][1].get('stale')


def test_targeted_merge_keeps_other_results_and_question_identity(client):
    a=seeded(client);q=copy.deepcopy(a['research']['issues'][0]);q.update(text='问题一重新表述',status='resolved')
    notes=dict(issues=[q],gaps=[],conflicts=[],evidence=[dict(claim_id='C1',source_id='S1',claim='主张1',quality='suitable')])
    rows=evidence_state.merge_issues(a,notes,['Q1'])
    assert [x['id'] for x in rows]==['Q1','Q2'] and rows[1]==a['research']['issues'][1]
    q['id']='invented';rows=evidence_state.merge_issues(a,notes,['Q1'])
    assert [x['id'] for x in rows]==['Q1','Q2']
    # Merely citing the same source cannot establish a different claim.
    notes['evidence'][0].update(claim_id='C2',claim='其他主张')
    assert evidence_state.merge_issues(a,notes,['Q1'])[0]['status']=='open'


def test_cancel_supplement_leaves_no_sticky_attachment(client):
    a=seeded(client)
    r=client.post('/api/articles/'+a['id']+'/research/issues/actions',headers=H,json=dict(revision=a['revision'],action='attach',action_id='cancelled',issue_ids=['Q1']))
    assert r.json()['article']['revision']==a['revision']
    a=client.post('/api/articles/'+a['id']+'/sources/text',headers=H,json=dict(revision=a['revision'],text='无关的下一次上传')).json()
    assert a['sources'][-1]['issue_ids']==[]
    a=client.post('/api/articles/'+a['id']+'/sources/text',headers=H,json=dict(revision=a['revision'],text='明确补给问题2',issue_ids=['Q2'])).json()
    assert a['sources'][-1]['issue_ids']==['Q2']
    assert a['materials_state']['action']=='verify_new' and a['research']['issues'][1]['status']=='resolved'


def test_bounded_wording_propagates_and_survives_unrelated_material(client):
    a=seeded(client)
    r=client.post('/api/articles/'+a['id']+'/research/issues/actions',headers=H,json=dict(revision=a['revision'],action='bound',action_id='bounded',issue_ids=['Q1'],wording='仅指所研究的成年男性，不能推出因果'))
    a=r.json()['article'];assert a['research']['issues'][0]['status']=='bounded'
    a=store.save_article(a['id'],a['revision'],lambda v:v['sources'].append(materials.source('新材料','新内容')),'new')
    assert a['research']['issues'][0]['status']=='bounded'
    for stage in ('outline','write','review'):
        context=json.loads(prompts.prompt(stage,a,{}))['资料与当前内容']
        assert context['issue_decisions'][0]['wording']=='仅指所研究的成年男性，不能推出因果'


def test_topic_plan_history_adoption_and_feedback_context(client,model):
    a=new(client)
    for n in range(4):
        a=store.save_article(a['id'],a['revision'],lambda v:creative.candidates(v,[dict(title='候选'+str(n),angle='读者痛点',reason='新增价值',reader_question='为什么实验室表现不能外推赛场',takeaway='判断条件',key_claims=['待证实假设'],source_ids=[])],'太普通，深入机制'),'candidate')
    assert len(a['creative_intent']['batches'])==3
    candidate=a['topics'][0]
    a=client.post('/api/articles/'+a['id']+'/topic',headers=H,json=dict(revision=a['revision'],title=candidate['title'],topic_id=candidate['id'])).json()
    assert a['creative_intent']['selected']==candidate and not store.jobs(a['id'])
    for stage in ('topic','outline','write'):
        ctx=json.loads(prompts.prompt(stage,a,{}))['资料与当前内容']
        assert ctx['creative_intent']['selected']['takeaway']=='判断条件'
    assert research.context(a,'topic')['creative_intent']['feedback'][-1]=='太普通，深入机制'
    assert research.context(a,'topic')['current_date']


def test_finished_outline_has_no_old_continuation(client):
    a=seeded(client);j=store.create_job(a['id'],dict(stage='outline',revision=a['revision']))
    store.update_job(j['id'],status='needs_input')
    a=store.save_article(a['id'],a['revision'],lambda v:v['research'].update(resume_job_id=j['id'],resume_stage='outline'),'fixture')
    assert issue_actions.parent(a)
    a=store.save_article(a['id'],a['revision'],lambda v:v['stages'].update(outline='done'),'finish')
    assert not a['research'].get('resume_job_id') and issue_actions.parent(a) is None


def test_existing_upload_checked_before_search_and_single_evidence_model(client,monkeypatch):
    a=seeded(client);j=store.create_job(a['id'],dict(stage='research',revision=a['revision'],issue_ids=['Q1']))
    called=[]
    async def structured(a,stage,instruction,schema,job,candidates=None,questions=()):
        called.append(schema.__name__)
        if schema.__name__=='ResearchPlan': return dict(needed=True,academic=True,queries=['query'],questions=[],reason='Check first')
        if schema.__name__=='CoverageAudit':
            from tests.quality_fixtures import coverage_audit
            return coverage_audit(candidates)
        if schema.__name__=='EvidenceJudgements':return judgements(candidates,a['research_contract'])
        return quality_notes(a,dict(summary='核实完成',evidence=[dict(source_id='S1',quote='Original evidence 1',claim='主张1',claim_id='C1',type='inference',quality='suitable',boundary='',source_type='original',adoption_reason='direct',use_scope='study')],issues=[dict(a['research']['issues'][0],status='resolved')],gaps=[],conflicts=[],followup_queries=[]))
    async def forbid(*args): raise AssertionError('已足够的上传材料不得先联网')
    monkeypatch.setattr(research,'structured',structured);monkeypatch.setattr(research.Research,'discover',forbid)
    saved,pending=asyncio.run(research.gather(a,j['id'],'research','只核实问题一'))
    assert not pending and called==['ResearchPlan','ResearchNotes','EvidenceJudgements','CoverageAudit']
    assert len(saved['evidence']['claims'])==2 and saved['evidence']['claims'][0]['type']=='inference'


def test_fulltext_identity_and_wrong_doi_rejected():
    identity=dict(title='Synthetic study',doi='10.1234/correct',pmcid='PMC1',bibliography={'document_type':'J'})
    blob=('<article><front><article-meta><article-id pub-id-type="doi">10.1234/correct</article-id></article-meta></front><body><sec><title>Results</title><p>'+('Synthetic evidence. '*40)+'</p></sec></body></article>').encode()
    s=source_reader.xml_source(blob,identity,'https://example.org/fullTextXML')
    assert s['status']=='retrieved' and s['identity_verified']
    with pytest.raises(ValueError): source_reader.xml_source(blob.replace(b'correct',b'wrong'),identity,'https://example.org/fullTextXML')


def test_url_only_bmj_uses_verified_public_copy(client,monkeypatch):
    url='https://bmjopensem.bmj.com/content/10/3/e002149'
    row=dict(title='Systematic video analysis of ACL injuries',doi='10.1136/bmjsem-2024-002149',pmcid='PMC11440205',id='39351123',journalInfo={'volume':'10','issue':'3','journal':{'title':'BMJ Open Sport & Exercise Medicine'}})
    async def blocked(url): raise ValueError('HTTP 403')
    async def search(q): return [dict(row,doi='10.1234/unrelated',journalInfo={'volume':'2','issue':'1'}),row]
    async def meta(doi): return dict(doi=doi,bibliography={'volume':'10','issue':'3','pages':'e002149'},canonical_urls=['https://bmjopensem.bmj.com/lookup/doi/'+doi])
    async def fetch(url):
        assert url.endswith('PMC11440205/fullTextXML')
        return ('<article><front><article-meta><article-id pub-id-type="doi">'+row['doi']+'</article-id></article-meta></front><body><p>'+('Synthetic evidence. '*40)+'</p></body></article>').encode(),url
    monkeypatch.setattr(materials,'read_url',blocked);monkeypatch.setattr(source_reader,'search',search);monkeypatch.setattr(academic,'lookup_doi',meta);monkeypatch.setattr(materials,'fetch_bytes',fetch)
    s=asyncio.run(materials.from_url(url))
    assert s['doi']==row['doi'] and s['status']=='retrieved' and s['original_url']==url


def test_no_progress_stops_after_one_attempt(client,monkeypatch):
    a=new(client);j=store.create_job(a['id'],dict(stage='research',revision=a['revision']))
    w=research.Research(a,j['id'],'research');attempts=[]
    async def structured(*args,**kwargs):
        if args[3].__name__=='ResearchPlan': return dict(needed=True,academic=False,queries=['q'],questions=[],reason='missing')
        return dict(summary='未取得',evidence=[],issues=[],gaps=[],conflicts=[],followup_queries=['another'])
    async def empty(queries): attempts.append(queries)
    monkeypatch.setattr(research,'structured',structured);monkeypatch.setattr(w,'discover',empty)
    assert asyncio.run(w.run()) and len(attempts)==1 and w.stop_reason and w.rounds==0
    assert attempts[0][0]['query']==a['brief']['topic']
    assert w.stop_code=='no_progress'


def test_generic_no_material_message_resolves_with_evidence(client):
    a=seeded(client)
    a['research']['issues'].append(dict(id='old-empty',text='未取得可用于当前主题的资料；可补充材料或检查检索渠道后重试。',kind='blocking',source_ids=[],claim='',status='open'))
    rows=evidence_state.merge_issues(a,dict(evidence=[dict(source_id='S1',quote='Original evidence 1',claim='主张1',quality='suitable',verification='quote_matched',source_type='original',adoption_reason='direct',use_scope='study',**assessment())]),['Q1'])
    assert next(x for x in rows if x['id']=='old-empty')['status']=='resolved'


def test_legacy_decision_migrates_only_on_edit_and_keeps_expression_change(client):
    from backend.flow_state import legacy_signature
    a=seeded(client)
    def old(v):v['research_decisions']={'Q1':dict(material_key=legacy_signature(v),handling='bounded')}
    a=store.save_article(a['id'],a['revision'],old,'fixture')
    with store.connection() as db:
        before=db.execute('SELECT data FROM articles WHERE id=?',(a['id'],)).fetchone()[0]
    assert store.get_article(a['id'])['research']['issues'][0]['status']=='bounded'
    with store.connection() as db:assert db.execute('SELECT data FROM articles WHERE id=?',(a['id'],)).fetchone()[0]==before
    a=patch(client,a,{'brief':dict(a['brief'],words=3200)},'setup')
    assert a['research']['issues'][0]['status']=='bounded' and a['research_decisions']['Q1']['dependency_key']


def test_reader_budget_prevents_unbounded_copy_attempts(monkeypatch):
    budget=dict(pages=0,metadata=0,max_pages=1,max_metadata=0)
    token=source_reader.READ_BUDGET.set(budget)
    async def blocked(url): raise ValueError('HTTP 403')
    monkeypatch.setattr(materials,'read_url',blocked)
    try:
        with pytest.raises(ValueError):asyncio.run(materials.from_url('https://doi.org/10.1234/example'))
        assert budget['pages']==1 and budget['metadata']==0
    finally:source_reader.READ_BUDGET.reset(token)


def test_completed_material_attempt_can_resume_only_its_valid_auto_target(client,model,monkeypatch):
    from tests.test_studio import wait
    from backend import workflow
    a=seeded(client)
    a=patch(client,a,{'auto':dict(a['auto'],sources=True)},'preferences')
    parent=store.create_job(a['id'],dict(stage='sources',revision=a['revision'],chain=True))
    store.update_job(parent['id'],status='completed',waiting_for_materials=True)
    a=store.save_article(a['id'],a['revision'],lambda v:v['research'].update(job_id=parent['id'],resume_job_id=parent['id'],resume_stage='sources'),'fixture')
    assert issue_actions.parent(a)['id']==parent['id']
    async def reuse(a,*args):return a,False
    monkeypatch.setattr(research,'gather',reuse)
    job=client.post('/api/articles/'+a['id']+'/jobs',headers=H,json=dict(stage='research',revision=a['revision'],continuation_job_id=parent['id'],chain=False)).json()
    assert wait(client,job)['status']=='completed'
    final=store.get_article(a['id'])
    assert final['outline']['sections'] and not final['content']
    assert issue_actions.parent(final) is None


def test_non_pmc_doi_reads_verified_openalex_copy(client,monkeypatch):
    identity=dict(title='Synthetic physics paper',doi='10.1234/physics',bibliography=dict(document_type='J'),fulltext_urls=[])
    async def empty(query):return []
    async def metadata(doi):return identity
    async def openalex(query):return [dict(identity,fulltext_urls=['https://example.org/wrong','https://example.org/correct'])]
    async def read(url):
        if 'doi.org' in url:raise ValueError('HTTP 403')
        return dict(materials.source('Synthetic physics paper','Synthetic original body',url,'web'),doi='10.1234/physics' if url.endswith('correct') else '10.1234/unrelated',bibliography=dict(document_type='J'))
    monkeypatch.setattr(source_reader,'search',empty);monkeypatch.setattr(academic,'lookup_doi',metadata);monkeypatch.setattr(academic,'openalex',openalex);monkeypatch.setattr(materials,'read_url',read)
    source=asyncio.run(materials.from_url('https://doi.org/10.1234/physics'))
    assert source['read_url']=='https://example.org/correct' and source['identity_verified']
