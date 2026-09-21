import asyncio
import httpx
from backend import research,store,academic,materials


def worker():
    a=store.create_article({'topic':'Several scientific questions','column':'运动科学'})
    j=store.create_job(a['id'],dict(stage='research'))
    w=research.Research(a,j['id'],'sources')
    w.cfg.update(max_calls=6,max_pages=32,academic_enabled=True,pubmed_enabled=True,arxiv_enabled=False)
    w.unavailable=lambda group:''
    return w


def test_questions_get_turns_before_one_query_exhausts_engines(monkeypatch):
    w=worker();seen=[]
    async def channel(name,query):
        if w.calls>=w.cfg['max_calls']:return []
        w.calls+=1;seen.append((name,query));return []
    monkeypatch.setattr(w,'channel',channel)
    asyncio.run(w.discover(['question one','question two','question three']))
    assert [q for _,q in seen[:3]]==['question one','question two','question three']
    assert any(c=='pubmed' for c,_ in seen)


def test_nonempty_irrelevant_openalex_does_not_suppress_crossref(monkeypatch):
    w=worker();w.cfg['max_calls']=12;seen=[]
    async def channel(name,query):
        w.calls+=1;seen.append(name)
        return [dict(url='https://example.org/unrelated',title='Unrelated')] if name=='openalex' else []
    async def collect(*args,**kw):return 0
    async def assess():pass
    monkeypatch.setattr(w,'channel',channel);monkeypatch.setattr(w,'collect',collect);monkeypatch.setattr(w,'assess',assess)
    asyncio.run(w.discover(['query']))
    assert 'crossref' in seen


def test_candidate_after_first_twelve_is_evaluated(monkeypatch):
    w=worker();w.query_readable=set();seen=[]
    rows=[dict(url=f'https://example.org/{i}',title=f'Study {i}',content='Abstract',provider='test') for i in range(29)]
    async def select(a,stage,instruction,schema,job,candidates=None,questions=()):
        seen.extend(r['url'] for r in candidates)
        return dict(urls=[r['url'] for r in candidates if r['url'].endswith('/28')],reason='Relevant core source')
    read=[]
    async def fetch(row):read.append(row['url']);return None
    monkeypatch.setattr(research,'structured',select);monkeypatch.setattr(w,'read',fetch)
    asyncio.run(w.collect(rows,'query','test'))
    assert rows[28]['url'] in seen and rows[28]['url'] in read


def test_arxiv_keeps_field_and_phrase_syntax(monkeypatch):
    seen=[]
    async def request(channel,url,params):
        seen.append(params['search_query']);return httpx.Response(200,content=b'<feed xmlns="http://www.w3.org/2005/Atom"/>')
    monkeypatch.setattr(academic,'request',request)
    asyncio.run(academic.arxiv('ti:"Lost in the Middle"'))
    assert seen==['ti:"Lost in the Middle"']


def test_cross_language_reader_keeps_long_tail_limitations():
    from backend import source_context
    s=materials.source('Long English study',('Introduction\nGeneral overview. '*250)+'\nMethods\nWe used an observational design.\n'+('Results\nUnrelated detail. '*1200)+'\nLimitations\nTraining injuries were excluded; causality cannot be established.')
    pieces=source_context.excerpts(s,{'韧带','机制'},12000)
    assert any('Training injuries were excluded' in x['text'] for x in pieces)


def test_deferred_candidates_are_read_after_search_budget(monkeypatch):
    w=worker();w.calls=w.cfg['max_calls'];read=[]
    w.deferred=[dict(url='https://example.org/core',title='Core',provider='test',query='q')]
    async def fetch(row):
        read.append(row['url']);w.pages+=1
        return materials.source('Core','Direct result.',row['url'],'web')
    async def assess():pass
    monkeypatch.setattr(w,'read',fetch);monkeypatch.setattr(w,'assess',assess)
    asyncio.run(w.drain_candidates())
    assert read==['https://example.org/core'] and not w.deferred


def test_resume_keeps_deferred_candidates_and_completed_query(monkeypatch):
    w=worker();item=research.search_plan.query('completed query')
    w.query_ledger=[dict(item,status='exhausted',attempts=[]),dict(query='paper',purpose='citation_graph',status='searched',attempts=[])]
    w.deferred=[dict(url='https://example.org/core',title='Core')];w.update('pause')
    store.update_job(w.job_id,status='cancelled')
    j=store.create_job(w.a['id'],dict(stage='research',research_parent_id=w.job_id))
    resumed=research.Research(w.a,j['id'],'sources')
    assert research.digest(item) in resumed.seen_queries and resumed.deferred==w.deferred


def test_notebook_rejects_unlocated_quotes_and_invalidates_old_analysis():
    from backend import source_notebook
    s=materials.source('Study','Methods\nObservational cohort.\nResults\nNo benefit.\nLimitations\nNo causal test.')
    notes=[dict(category='results',note='Negative result',quote='No benefit.'),dict(category='design',note='Invented',quote='Randomized trial.')]
    source_notebook.save(s,notes,'model1')
    assert len(s['notebook']['notes'])==1 and 'design' in s['notebook']['missing_categories']
    source_notebook.save(s,[],'model2')
    assert s['notebook']['notes']==[]


def test_requested_section_reaches_context_without_changing_original():
    from backend import source_notebook,source_context
    text='Introduction\n'+('Background text. '*1600)+'\nResults\n'+('Outcome. '*1000)+'\nLimitations\nNo causal inference.'
    s=materials.source('Study',text);w=worker();w.a['sources']=[s]
    section=next(x for x in source_notebook.sections(s) if x['title']=='Limitations')
    assert source_notebook.request_reads(w.a,[dict(source_id=s['id'],section_id=section['id'],reason='Read caveat')])
    assert 'No causal inference.' in source_context.sources(w.a)[0]['text']
    assert s['text']==text


def test_citation_edges_are_bounded_and_do_not_become_support():
    from backend import citation_graph
    seen=[]
    async def request(channel,url,params):
        seen.append(params)
        if params is None:return httpx.Response(200,json={'id':'https://openalex.org/W1','doi':'https://doi.org/10.1000/seed'})
        return httpx.Response(200,json={'results':[dict(id='https://openalex.org/W2',title='Follow-up',doi='https://doi.org/10.1000/follow',type='article')]})
    seed=dict(id='S1',doi='10.1000/seed',citation_depth=1)
    rows,attempts=asyncio.run(citation_graph.neighbors(seed,request))
    assert len(seen)==3 and rows[0]['citation_depth']==2
    assert rows[0]['status']=='metadata_only' and not rows[0].get('evidence_spans')
    assert asyncio.run(citation_graph.neighbors(dict(seed,citation_depth=2),request))==([],[])
    assert len(seen)==3


def test_identifier_queries_preserve_exact_identity(monkeypatch):
    from backend import search_plan
    seen=[]
    async def lookup(value):seen.append(value);return {'doi':value}
    monkeypatch.setattr(academic,'lookup_doi',lookup)
    assert asyncio.run(academic.crossref('https://doi.org/10.1000/study'))==[{'doi':'10.1000/study'}]
    assert search_plan.compile_query('PMID:12345','pubmed')=='12345[uid]'
    assert search_plan.compile_query('arxiv:2307.03172v2','arxiv')=='id:2307.03172v2'


def test_invalid_check_label_remains_unresolved():
    from backend.models import EvidenceJudgement
    from backend import research_contract
    from tests.quality_fixtures import assessment
    e=assessment();e.update(evidence_id='E1',claim='Causal benefit',quote='Association',boundary='')
    j=EvidenceJudgement.model_validate(dict(evidence_id='E1',support='supported',reason='Association only',basis='observed',checks={**e['support_checks'],'causality':'limited'})).model_dump()
    research_contract.apply_judgements([e],[j])
    assert e['support']=='unsupported' and e['support_checks']['causality']=='unknown'


def test_arxiv_landing_is_upgraded_only_to_matching_version(monkeypatch):
    from backend import source_reader
    landing=materials.source('Study','An abstract.','https://arxiv.org/abs/2307.03172v2','web')
    landing.update(status='abstract_only',bibliography={'title':'Study','document_type':'PP'})
    async def index(q):return [dict(title='Study',arxiv_id='2307.03172v2',bibliography={'title':'Study','document_type':'PP'})]
    async def read(url):
        if '/html/' in url:raise ValueError('HTML unavailable')
        return materials.source('PDF','arXiv:2307.03172v1 Different version.',url,'web',[dict(page=1,text='arXiv:2307.03172v1 Different version.')])
    monkeypatch.setattr(academic,'arxiv',index);monkeypatch.setattr(materials,'read_url',read)
    result=asyncio.run(source_reader.read_arxiv(landing['url'],landing))
    assert result['status']=='abstract_only' and not result.get('identity_verified')


def test_arxiv_verified_pdf_matches_discovery_identity():
    from backend import source_reader
    src=materials.source('PDF','arXiv:2307.03172v3 Correct.', 'https://arxiv.org/pdf/2307.03172v3','web')
    src.update(arxiv_id='2307.03172v3',bibliography={'document_type':'PP'})
    assert source_reader.candidate_matches(src,dict(title='Study',arxiv_id='2307.03172v3',bibliography={'document_type':'PP'}))
    assert not source_reader.candidate_matches(src,dict(title='Study',arxiv_id='2307.03172v2',bibliography={'document_type':'PP'}))
