import asyncio
import copy
import json
import pytest
from backend import store,materials,source_reader,source_imports,academic,research,workflow,evidence_state,bounded
from backend.models import IssueAction,JobRequest
from tests.test_studio import client,model,new,patch,run,wait,H
from tests.test_creative_flow import seeded


def paper():
    return academic.row(dict(title='A verified study of movement',doi='10.1234/example',authors=[{'family':'Author','given':'A'}],year='2024',venue='Journal',document_type='J',url='https://doi.org/10.1234/example'),'crossref')


@pytest.mark.parametrize('url,query',[
 ('https://pmc.ncbi.nlm.nih.gov/articles/PMC12345/','PMCID:PMC12345'),
 ('https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12345/','PMCID:PMC12345'),
 ('https://pubmed.ncbi.nlm.nih.gov/12345/','EXT_ID:12345 AND SRC:MED'),
 ('https://doi.org/10.1234/example','DOI:"10.1234/example"')])
def test_identifier_route_precedes_challenge(url,query,monkeypatch):
    async def search(q):
        assert q==query
        return [dict(id='12345',pmcid='PMC12345',doi='10.1234/example',title='A verified study of movement')]
    async def fetch(url):return b'<article><front><article-meta><article-id pub-id-type="doi">10.1234/example</article-id></article-meta></front><body><p>'+b'actual evidence '*80+b'</p></body></article>','xml'
    async def unwanted(url):raise AssertionError('Stable identity should avoid challenge page')
    monkeypatch.setattr(source_reader,'search',search);monkeypatch.setattr(materials,'fetch_bytes',fetch);monkeypatch.setattr(materials,'read_url',unwanted)
    src=asyncio.run(materials.from_url(url));assert src['access_scope']=='fulltext' and src['doi']=='10.1234/example'


def test_file_identity_and_failed_metadata_keep_text(monkeypatch):
    src=materials.source('random.pdf','A verified study of movement\nAuthor 2024\ndoi:10.1234/example\nAbstract\nEvidence',pages=[dict(page=1,text='A verified study of movement Author 2024 doi:10.1234/example Abstract Evidence')])
    async def lookup(doi):return paper()
    monkeypatch.setattr(academic,'lookup_doi',lookup)
    result=asyncio.run(source_imports.identify_file(copy.deepcopy(src)))
    assert result['identity_verified'] and result['title']==paper()['title'] and result['text']==src['text']
    async def failure(*args):raise ValueError('unavailable')
    monkeypatch.setattr(academic,'lookup_doi',failure)
    result=asyncio.run(source_imports.identify_file(copy.deepcopy(src)))
    assert result['identity_status']=='pending' and result['text']==src['text']


def test_reference_doi_is_not_uploaded_document_identity(monkeypatch):
    src=materials.source('notes.pdf','Different work\nAbstract\nReferences\nA verified study of movement Author 2024 doi:10.1234/example',pages=[dict(page=1,text='Different work\nAbstract\nReferences\nA verified study of movement Author 2024 doi:10.1234/example')])
    async def search(*args):return [paper()]
    monkeypatch.setattr(academic,'crossref',search)
    result=asyncio.run(source_imports.identify_file(src));assert not result.get('identity_verified')


def test_async_import_cancel_and_retry(client,monkeypatch):
    a=new(client)
    async def slow(*args):await asyncio.sleep(30)
    monkeypatch.setattr(materials,'from_url',slow)
    payload=dict(revision=a['revision'],url='https://example.org/paper',issue_ids=[])
    j=client.post('/api/articles/'+a['id']+'/source-imports',headers=H,json=payload).json()
    assert client.post('/api/articles/'+a['id']+'/source-imports',headers=H,json=payload).json()['id']==j['id']
    client.post('/api/jobs/'+j['id']+'/cancel',headers=H)
    assert wait(client,j)['status']=='cancelled' and not store.get_article(a['id'])['sources']
    async def success(*args):return materials.source('Published paper','Actual text','https://example.org/paper','web')
    monkeypatch.setattr(materials,'from_url',success)
    j=client.post('/api/articles/'+a['id']+'/source-imports',headers=H,json=payload).json()
    assert wait(client,j)['status']=='completed'
    assert len(store.get_article(a['id'])['sources'])==1


def test_file_import_deduplicates_without_losing_use(client):
    a=new(client);path='/api/articles/'+a['id']+'/source-imports/file'
    def upload(a):return wait(client,client.post(path,headers=H,data={'revision':a['revision']},files={'file':('note.txt',b'user material','text/plain')}).json())
    assert upload(a)['status']=='completed'
    a=store.get_article(a['id']);sid=a['sources'][0]['id']
    a=patch(client,a,{'sources':[dict(a['sources'][0],use='my rule',selected=False)]},'sources')
    assert upload(a)['status']=='completed'
    a=store.get_article(a['id']);assert len(a['sources'])==1 and a['sources'][0]['id']==sid
    assert not a['sources'][0]['selected'] and a['sources'][0]['use']=='my rule'
    assert len(list((store.DATA/'articles'/a['id']/'materials').iterdir()))==1


def test_no_blank_delta_and_new_sources_not_global_stale(client):
    a=seeded(client);assert a['materials_state']['delta'] is None
    a=client.post('/api/articles/'+a['id']+'/sources/text',headers=H,json={'revision':a['revision'],'text':'new material'}).json()
    assert a['materials_state']['new_source_ids'] and not a['research']['stale']
    assert all(i['status']=='resolved' for i in a['research']['issues']) and a['workflow']['outline']['allowed']


def test_full_issues_do_not_duplicate_legacy_gaps(client):
    a=seeded(client)
    notes=dict(issues=[dict(a['research']['issues'][0],text='New wording',status='open')],gaps=['New wording'],conflicts=[],evidence=[])
    rows=evidence_state.merge_issues(a,notes)
    assert len(rows)==2 and sum(i['id']=='Q1' for i in rows)==1


def test_explicit_duplicate_mapping_preserves_manual_decision(client):
    a=seeded(client);a['research_decisions']={'Q1':dict(dependency_key=evidence_state.dependency(a,a['research']['issues'][0]),handling='bounded',wording='bounded')}
    notes=dict(issues=[dict(a['research']['issues'][0],merged_ids=['Q2'])],gaps=[],conflicts=[],evidence=[])
    rows=evidence_state.merge_issues(a,notes)
    assert len(rows)==1 and rows[0]['id']=='Q1'


def test_bound_apply_and_undo_preserve_unrelated_edit(client,monkeypatch):
    a=seeded(client);a=patch(client,a,{'content':'Original assertion.\nOther paragraph.'},'write')
    async def result(*args):return dict(decisions=[dict(issue_id='Q1',wording='Limited association.',explanation='No causal evidence',edits=[dict(target='content',section_id='',point_index=0,original='Original assertion.',replacement='Limited association.')])])
    monkeypatch.setattr(research,'structured',result)
    response=client.post('/api/articles/'+a['id']+'/research/issues/actions',headers=H,json=dict(revision=a['revision'],issue_ids=['Q1'],action='bound_auto',action_id='bound1'))
    assert response.status_code==200,response.text
    assert wait(client,response.json()['job'])['status']=='completed'
    a=store.get_article(a['id']);assert a['content'].startswith('Limited association.')
    a=patch(client,a,{'content':a['content']+'\nLater human addition.'},'write')
    response=client.post('/api/articles/'+a['id']+'/research/issues/actions',headers=H,json=dict(revision=a['revision'],issue_ids=['Q1'],action='undo',action_id='undo1'))
    assert response.status_code==200,response.text
    assert response.json()['article']['content']=='Original assertion.\nOther paragraph.\nLater human addition.'


def test_bound_ambiguous_text_remains_unchanged(client,monkeypatch):
    a=seeded(client);a=patch(client,a,{'content':'Repeated. Repeated.'},'write')
    async def result(*args):return dict(decisions=[dict(issue_id='Q1',wording='Limited.',explanation='Ambiguous',edits=[dict(target='content',original='Repeated.',replacement='Limited.')])])
    monkeypatch.setattr(research,'structured',result)
    j=client.post('/api/articles/'+a['id']+'/research/issues/actions',headers=H,json=dict(revision=a['revision'],issue_ids=['Q1'],action='bound_auto',action_id='b')).json()['job']
    assert wait(client,j)['status']=='completed'
    a=store.get_article(a['id']);assert a['content']=='Repeated. Repeated.' and a['research']['issues'][0]['application']['unapplied']


def test_trash_restore_purge_and_active_task_guard(client):
    a=new(client);other=new(client);folder=store.article_dir(a['id'])/'materials';folder.mkdir();(folder/'source.txt').write_text('source')
    j=store.create_job(a['id'],dict(stage='research',revision=a['revision']))
    assert client.post('/api/articles/'+a['id']+'/trash',headers=H,json={'revision':a['revision']}).status_code==409
    store.update_job(j['id'],status='completed')
    a=client.post('/api/articles/'+a['id']+'/trash',headers=H,json={'revision':a['revision']}).json()
    assert len(client.get('/api/articles').json())==1 and len(client.get('/api/articles?state=trash').json())==1
    assert client.get('/api/articles/'+a['id']).status_code==409
    a=client.post('/api/articles/'+a['id']+'/untrash',headers=H,json={'revision':a['revision']}).json()
    assert (folder/'source.txt').exists()
    a=client.post('/api/articles/'+a['id']+'/trash',headers=H,json={'revision':a['revision']}).json()
    assert client.request('DELETE','/api/articles/'+a['id'],headers=H,json={'revision':a['revision']}).status_code==200
    assert not folder.exists() and store.get_article(other['id'])


def test_metadata_queries_are_recorded_independently_of_search(client,monkeypatch):
    a=new(client);j=store.create_job(a['id'],dict(stage='research',revision=a['revision']))
    worker=research.Research(a,j['id'],'research');worker.calls=99
    async def read(url):
        source_reader.take('metadata');source_reader.take('pages');return materials.source('paper','text',url,'web')
    monkeypatch.setattr(materials,'from_url',read)
    asyncio.run(worker.fetch('https://example.org'))
    assert worker.calls==99 and worker.stats['metadata_requests']==1


def test_legacy_limits_are_ignored_but_execution_counters_resume(client):
    a=new(client);prior=store.create_job(a['id'],dict(stage='research',revision=a['revision']))
    store.update_job(prior['id'],status='completed',research=dict(calls=12,pages=8,rounds=1,stats=dict(search_requests=7,metadata_requests=5),log=[dict(query='already searched')]))
    j=store.create_job(a['id'],dict(stage='research',revision=a['revision'],research_parent_id=prior['id'],research_limits=dict(max_calls=20,max_pages=40,max_rounds=5)))
    worker=research.Research(a,j['id'],'research')
    assert worker.calls==7 and worker.pages==8 and worker.rounds==1 and research.digest(research.search_plan.query('already searched')) in worker.seen_queries
    assert not any(k in worker.cfg for k in ('max_calls','max_pages','max_rounds'))
