"""Synthetic regressions for retrieving evidence that fits the article question."""
import asyncio
import pytest

from backend import academic, materials, research, research_contract, search_plan, source_reader
from tests.test_quality_discovery import worker


def test_different_known_papers_are_not_suppressed_by_question_dedup(monkeypatch):
    w=worker();qid=research_contract.ensure(w.a)['questions'][0]['id'];seen=[]
    monkeypatch.setattr(search_plan,'channels',lambda *args:['native'])
    async def channel(name,query):seen.append(query);return []
    monkeypatch.setattr(w,'channel',channel)
    first=dict(query='Find consensus 10.1234/first',question_ids=[qid],purpose='known_source')
    second=dict(query='Find report 10.1234/second',question_ids=[qid],purpose='known_source')
    asyncio.run(w.discover([first,second]))
    assert seen==[first['query'],second['query']]


def test_known_paper_aliases_reuse_same_path_but_distinct_subquestions_do_not():
    w=worker();qid=research_contract.ensure(w.a)['questions'][0]['id']
    item=search_plan.query(dict(query='10.1234/first',purpose='known_source',question_ids=[qid]))
    alias=search_plan.query(dict(item,query='Read the full consensus',channel_queries={'crossref':'https://doi.org/10.1234/FIRST'}))
    assert w.action_key(item,'native')==w.action_key(alias,'native')
    a=search_plan.query(dict(query='training adaptation',question_ids=[qid],target='Compare training response by maturity'))
    b=search_plan.query(dict(query='training safety',question_ids=[qid],target='Compare injury incidence under supervision'))
    assert w.action_key(a,'pubmed')!=w.action_key(b,'pubmed')


def repository_page(pdf='/paper.pdf'):
    return ('''<html><head><title>Repository record</title>
      <meta name="citation_title" content="A synthetic comparative training study">
      <meta name="citation_author" content="Example, Alice">
      <meta name="citation_publication_date" content="2025/01/01">
      <meta name="citation_journal_title" content="Synthetic Journal">
      <meta name="DC.identifier" content="https://doi.org/10.1234/synthetic">
      <meta name="citation_pdf_url" content="'''+pdf+'''"></head>
      <main><h1>A synthetic comparative training study</h1><div class="abstract">'''+
      ('This is the repository abstract. '*30)+'''</div></main></html>''').encode()


def fixture_reader(monkeypatch,doi='10.1234/synthetic'):
    seen=[]
    async def fetch(url,*args,**kwargs):
        seen.append(url)
        if url=='https://repository.example/record':return repository_page(),url
        if url=='https://repository.example/paper.pdf':return b'%PDF-SYNTHETIC',url
        raise ValueError('Synthetic unavailable source')
    def extract(name,blob):
        text='A synthetic comparative training study\nAlice Example\n2025\n'+doi+'\n'+('Methods and results. '*40)
        return text,[dict(page=1,text=text)]
    async def no_identity(*args,**kwargs):return None
    async def no_index(*args,**kwargs):return []
    monkeypatch.setattr(materials,'fetch_bytes',fetch);monkeypatch.setattr(materials,'extract_file',extract)
    monkeypatch.setattr(source_reader,'identify',no_identity);monkeypatch.setattr(academic,'openalex',no_index)
    return seen


def test_repository_metadata_retains_declared_pdf_and_dublin_core_doi(monkeypatch):
    fixture_reader(monkeypatch)
    src=asyncio.run(materials.read_url('https://repository.example/record'))
    assert src['doi']=='10.1234/synthetic'
    assert src['fulltext_urls']==['https://repository.example/paper.pdf']
    assert src['status']=='abstract_only'


def test_reader_follows_declared_pdf_without_repeating_scholarly_discovery(monkeypatch):
    seen=fixture_reader(monkeypatch)
    src=asyncio.run(source_reader.read('https://repository.example/record'))
    assert src['status']=='retrieved' and src['identity_verified']
    assert src['read_url']=='https://repository.example/paper.pdf'
    assert src['original_url']=='https://repository.example/record'
    assert src['doi']=='10.1234/synthetic' and 'Methods and results' in src['text']
    assert seen==['https://repository.example/record','https://repository.example/paper.pdf']


def test_wrong_declared_pdf_does_not_replace_repository_abstract(monkeypatch):
    fixture_reader(monkeypatch,doi='10.1234/different')
    src=asyncio.run(source_reader.read('https://repository.example/record'))
    assert src['status']=='abstract_only' and not src.get('identity_verified')
    assert 'Methods and results' not in src['text']


def test_doi_discovery_also_follows_a_repository_pdf(monkeypatch):
    seen=fixture_reader(monkeypatch)
    identity=dict(title='A synthetic comparative training study',doi='10.1234/synthetic',
        url='https://doi.org/10.1234/synthetic',content='Indexed abstract',status='abstract_only',
        bibliography=dict(title='A synthetic comparative training study',doi='10.1234/synthetic'),
        fulltext_urls=['https://repository.example/record'])
    async def identify(*args,**kwargs):return identity
    monkeypatch.setattr(source_reader,'identify',identify)
    src=asyncio.run(source_reader.read(identity['url']))
    assert src['status']=='retrieved' and src['identity_verified']
    assert src['read_url']=='https://repository.example/paper.pdf'
    assert seen.count('https://repository.example/record')==1 and seen.count(src['read_url'])==1


def test_article_body_is_not_downgraded_by_navigation_and_modal_links(monkeypatch):
    body='A directly readable professional article. '*30
    nav=''.join(f'<a href="/menu/{i}">Menu</a>' for i in range(50))
    html=f'<html><title>Professional article</title><body>{nav}<div class="elementor-widget-theme-post-content"><p>{body}</p></div><div role="dialog">UNRELATED_EVENT</div></body></html>'
    async def fetch(url,*args,**kwargs):return html.encode(),url
    monkeypatch.setattr(materials,'fetch_bytes',fetch)
    src=asyncio.run(materials.read_url('https://professional.example/article'))
    assert src['status']=='retrieved'
    assert 'UNRELATED_EVENT' not in src['text'] and 'Menu' not in src['text']
    assert body.strip() in src['text']


def test_direct_scholarly_candidates_are_enriched_once_and_remain_leads(monkeypatch):
    from backend import discovery_identity
    looked=[]
    async def identify(url,hint=None):
        looked.append(url)
        return academic.row(dict(title='Indexed study',url='https://doi.org/10.1234/study',doi='10.1234/study',
            authors=['Example'],year='2025',document_type='J'),'europepmc','The indexed abstract describes a randomized comparison.')
    monkeypatch.setattr(source_reader,'identify',identify)
    rows=[dict(title='Poor search title',url='https://doi.org/10.1234/study#one',content='',provider='native'),
          dict(title='Another snippet title',url='https://doi.org/10.1234/study#two',content='',provider='native')]
    result=asyncio.run(discovery_identity.normalize_many(rows))
    again=asyncio.run(discovery_identity.normalize_many(rows))
    assert len(result)==1 and len(looked)==1
    assert result[0]['title']=='Indexed study' and 'randomized comparison' in result[0]['content']
    assert result[0]['snippet_kind']=='indexed_abstract'
    assert result[0].get('status')!='retrieved' and not result[0].get('identity_verified')
    assert again==result


def test_metadata_failure_keeps_original_discovery_candidate(monkeypatch):
    from backend import discovery_identity
    async def unavailable(*args,**kwargs):raise ValueError('Synthetic index unavailable')
    monkeypatch.setattr(source_reader,'identify',unavailable)
    row=dict(title='Potential study',url='https://doi.org/10.1234/potential',content='',provider='native')
    result=asyncio.run(discovery_identity.normalize_many([row]))
    assert result[0]['url']==row['url'] and result[0]['title']==row['title']
    assert result[0]['identity_status']=='unresolved'


def test_partial_search_cannot_be_promoted_by_metadata_enrichment(monkeypatch):
    from backend import discovery_identity
    async def identify(url):return dict(url=url,title='Indexed work',doi='10.1234/partial',content='An indexed abstract',status='abstract_only')
    monkeypatch.setattr(source_reader,'identify',identify)
    row=dict(url='https://doi.org/10.1234/partial',title='Partial search',content='',verification_required=True)
    result=asyncio.run(discovery_identity.normalize_many([row]))[0]
    assert result['verification_required'] and result['content']=='' and result['status']=='metadata_only'


def test_reference_text_is_not_used_as_the_repository_doi(monkeypatch):
    html=repository_page().replace(b'https://doi.org/10.1234/synthetic',b'Other Author (2020). A cited work. doi:10.1234/other')
    async def fetch(url):return html,url
    monkeypatch.setattr(materials,'fetch_bytes',fetch)
    assert not asyncio.run(materials.read_url('https://repository.example/record'))['doi']


def test_background_selection_does_not_displace_direct_answer(monkeypatch):
    w=worker();w.query_readable=set();qid=research_contract.ensure(w.a)['questions'][0]['id'];read=[]
    w.current_query=search_plan.query(dict(query='same dose at different maturity stages',question_ids=[qid],
        question='Does maturation alter response to the same training?',target='Compare the same training across maturity stages',
        expected_gain='A comparison of training effects across maturity groups'))
    rows=[dict(url='https://example.org/background',title='Before and after dance training',content='Before-after study'),
          dict(url='https://example.org/direct',title='Comparison by maturity',content='Controlled comparison')]
    async def structured(a,stage,instruction,schema,job,candidates=None,questions=()):
        assert 'same training across maturity' in instruction
        return dict(urls=[r['url'] for r in rows],decisions=[
            dict(url=rows[0]['url'],role='background',question=w.current_query['question'],reason='No comparison across maturity',contribution='Illustrates trainability only'),
            dict(url=rows[1]['url'],role='direct',question=w.current_query['question'],reason='Matches the required comparison',contribution='Compare training responses')])
    async def fetch(row):
        read.append(row['url']);return materials.source(row['title'],'Synthetic results.',row['url'],'web')
    monkeypatch.setattr(research,'structured',structured);monkeypatch.setattr(w,'read',fetch)
    asyncio.run(w.collect(rows,w.current_query['query'],'native'))
    assert read==['https://example.org/direct']
    assert w.candidates[rows[0]['url']]['status']=='background'
    assert w.a['sources'][0]['retrieval_fit']['role']=='direct'


def test_native_search_enriches_candidates_and_keeps_exclusions(monkeypatch):
    from backend import discovery_identity,store
    from tests.test_native_runtime import article,session
    a=article();excluded=materials.source('Excluded work','','https://doi.org/10.1234/excluded','web')
    excluded.update(selected=False,doi='10.1234/excluded');a['sources'].append(excluded)
    s=session(a,'sources');seen=[]
    async def search(**args):return [dict(url=excluded['url'],title='Excluded'),dict(url='https://example.org/candidate',title='Candidate')]
    async def enrich(rows):
        seen.extend(rows);source_reader.take('metadata')
        return [dict(rows[0],doi=excluded['doi'],content='Real indexed abstract')]
    monkeypatch.setattr(s,'search',search);monkeypatch.setattr(discovery_identity,'normalize_many',enrich)
    assert asyncio.run(s.execute('WebSearch',dict(query='Synthetic query')))==[]
    assert len(seen)==1 and seen[0]['title']=='Candidate'
    assert store.job(s.job_id)['native_metadata_count']==1


@pytest.mark.anyio
async def test_native_fetch_records_intended_use_without_promoting_it_to_a_claim(monkeypatch):
    from backend import native_projection
    from tests.test_native_runtime import article,session
    s=session(article(),'sources');await s.prepare()
    async def fetch(url):return materials.source('Background study','Training was feasible.',url,'web')
    monkeypatch.setattr(materials,'from_url',fetch)
    fit=dict(role='background',question='Does age change training response?',reason='No age comparison',contribution='Illustrates feasibility only')
    result=await s.execute('WebFetch',dict(url='https://example.org/background',retrieval_fit=fit))
    ledger=native_projection.mapping(s.directory/'sources.yaml')['sources']
    row=next(x for x in ledger if x['id']==result['source_id'])
    assert row['retrieval_fit']==fit and row['status']=='unverified' and not row['claims']
    changed=dict(fit,reason='Useful as context after reviewing the paper')
    reused=await s.execute('WebFetch',dict(url='https://example.org/background',retrieval_fit=changed))
    assert reused['reused'] and next(x for x in native_projection.mapping(s.directory/'sources.yaml')['sources'] if x['id']==result['source_id'])['retrieval_fit']==changed
