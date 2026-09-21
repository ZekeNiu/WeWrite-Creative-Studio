import asyncio
import io
import json
import zipfile
import httpx
import pytest
from bs4 import BeautifulSoup
from backend import bibliography as bib, academic, materials, rendering, store, search_tools, providers, research
from tests.test_research import client, network, H, wait


def source(sid,typ='J'):
    return {'id':sid,'title':'Evidence and exercise','url':'https://example.org/'+sid,'selected':True,'text':'Verified study findings. '*30,'status':'retrieved',
        'bibliography':{'authors':[{'family':'Smith','given':'Alex James'},{'family':'Wang','given':'Li'}],'title':'Evidence and exercise','document_type':typ,'venue':'Journal of Evidence','year':'2025','volume':'10','issue':'2','pages':'12-19','url':'https://example.org/'+sid,'access_date':'2026-09-18'}}


def test_first_appearance_group_repeat_and_delete():
    sources=[source('Sa'),source('Sb'),source('Sc')]
    text,refs,_=bib.citations('B[Sb] A[Sa] B[Sb] group[Sc,Sa] old[8]',sources)
    assert [r['id'] for r in refs]==['Sb','Sa','Sc']
    assert BeautifulSoup(text,'html.parser').get_text()=='B[1] A[2] B[1] group[3,2] old[8]'
    assert [r['id'] for r in bib.citations('A[Sa] B[Sb]',sources)[1]]==['Sa','Sb']
    assert bib.citations('[Sunknown]',sources)[2]==['Sunknown']


@pytest.mark.parametrize('typ',['J','C','PP','EB'])
def test_2025_formats(typ):
    s=source('Sa',typ);m=s['bibliography'];m.update(platform='arXiv',published_date='2025-03-02',version='v2')
    r=bib.format_reference(s)
    assert r['complete'] and 'Smith A J, Wang L.' in r['text']
    assert '['+typ+'/OL]' in r['text']
    if typ in ('J','C'): assert '[2026-09-18]' not in r['text'] and '2025, 10(2): 12-19' in r['text']
    else: assert '(2025-03-02)[2026-09-18]' in r['text']
    if typ=='C': assert '[C/OL]//Journal' in r['text']
    if typ=='PP': assert '[PP/OL]. v2. arXiv' in r['text']


def test_missing_metadata_not_invented():
    s=source('Sa');s['bibliography'].pop('year');s['bibliography'].pop('authors')
    r=bib.format_reference(s)
    assert not r['complete'] and r['missing']==['作者','年份'] and '2026' not in r['text']


def test_all_exports_use_same_numbering_and_final_references(client):
    a=store.create_article();a.update(sources=[source('Sa'),source('Sb')],content='甲[Sb] 乙[Sa] 再次[Sb]',images=[])
    a['layout']['author']='作者署名'
    result=rendering.render(a,True)
    soup=BeautifulSoup(result['html'],'html.parser')
    assert [n.get_text() for n in soup.select('sup')]==['[1]','[2]','[1]']
    assert all('vertical-align:super' in n.get('style','').replace(' ','') for n in soup.select('sup'))
    assert result['markdown'].index('作者署名')<result['markdown'].index('参考文献')
    assert result['plaintext'].index('Sb')<result['plaintext'].index('Sa')
    assert '[Sb]' not in result['plaintext'] and '<sup' in result['markdown']
    with zipfile.ZipFile(io.BytesIO(rendering.export_zip(a))) as z:
        assert z.read('文章.md').decode()==result['markdown']
        assert z.read('排版.html').decode()==result['html']


def test_bibtex_ris_import_are_metadata_only():
    a=bib.import_records('x.bib',b'@article{x,title={A {Nested} Title}, author={Smith, John and Wang, Li}, journal={Nature},year={2025},doi={10.1000/test},pages={1--9}}')[0]
    b=bib.import_records('x.ris',b'TY  - JOUR\nTI  - A Nested Title\nDO  - 10.1000/test\nUR  - https://doi.org/10.1000/test\nER  - \n')[0]
    assert a['status']=='metadata_only' and not a['text'] and a['bibliography']['pages']=='1-9'
    assert len(academic.merge_records([a,b]))==1


def test_merge_abstract_fulltext_keeps_identity_and_exclusion():
    a=source('Sa');a.update(status='abstract_only',doi='10.1000/TEST',selected=False,discovery_channels=['pubmed'])
    b=source('Sb');b.update(doi='https://doi.org/10.1000/test',text='Full text',discovery_channels=['openalex'],fulltext_urls=['https://example.org/full'])
    merged=academic.merge_records([a,b]);assert len(merged)==1
    assert merged[0]['id']=='Sa' and merged[0]['text']=='Full text' and not merged[0]['selected']
    assert merged[0]['discovery_channels']==['pubmed','openalex']
    assert bib.citations('[Sa]',merged)[1][0]['id']=='Sa'


def test_preprint_publication_not_title_merged():
    a=source('Sa','PP');b=source('Sb','J')
    assert len(academic.merge_records([a,b]))==2


def test_gemini_tools_required_and_text_protocol_preserved(client,network,monkeypatch):
    old=providers.settings();s=providers.effective_service('search');s['protocol']='gemini'
    real=httpx.AsyncClient;seen=[]
    def response(req):
        seen.append(req);return httpx.Response(200,json={'candidates':[{'groundingMetadata':{'webSearchQueries':['exercise'],'groundingChunks':[{'web':{'uri':'https://who.int','title':'WHO'}}]}}]})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(response),**kw))
    result=client.post('/api/search/native/test',headers=H,json={'service_id':'s','model':'gemini-test','protocol':'gemini'})
    assert result.status_code==200,result.text
    assert '/v1beta/models/gemini-test:generateContent' in str(seen[0].url)
    assert providers.settings()['services']==old['services']
    assert providers.settings()['search']==old['search']
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'candidates':[{'content':{'parts':[{'text':'已经搜索'}]}}]})),**kw))
    with pytest.raises(ValueError,match='真实搜索工具'): asyncio.run(search_tools.native(s,'x'))


def test_academic_attempts_crossdiscipline_and_specialist_before_reading(client,network,monkeypatch):
    calls=[]
    async def channel(name,query):
        calls.append(name)
        s=source('Sa');s.update(content=s['text'],provider=name,academic=True,doi='10.1000/test')
        return [s]
    monkeypatch.setattr(academic,'openalex',lambda q:channel('openalex',q))
    monkeypatch.setattr(search_tools,'pubmed',lambda q:channel('pubmed',q))
    a=store.create_article({'column':'运动科学'});j=store.create_job(a['id'],{'stage':'research'})
    w=research.Research(a,j['id'],'sources');w.cfg.update(academic_enabled=True,pubmed_enabled=True,browser_enabled=False);w.search_model=None
    asyncio.run(w.discover(['exercise']))
    assert calls==['openalex','pubmed'] and len(w.a['sources'])==1
    assert w.a['sources'][0]['discovery_channels']==['openalex','pubmed']


def test_openalex_rate_limit_crossref_fallback(client,network,monkeypatch):
    called=[]
    async def fail(q):called.append('openalex');raise ValueError('额度不足')
    async def backup(q):called.append('crossref');return []
    monkeypatch.setattr(academic,'openalex',fail);monkeypatch.setattr(academic,'crossref',backup)
    a=store.create_article({'column':'历史'});j=store.create_job(a['id'],{'stage':'research'})
    w=research.Research(a,j['id'],'sources');w.cfg.update(academic_enabled=True,browser_enabled=False);w.search_model=None
    asyncio.run(w.discover(['history']))
    assert called==['openalex','crossref'] and not network and not w.added


def test_article_metadata_patch_and_version_restore(client):
    a=client.post('/api/articles',headers=H,json={}).json()
    a=client.post('/api/articles/'+a['id']+'/sources/text',headers=H,json={'revision':a['revision'],'title':'A','text':'Evidence'}).json()
    s=a['sources'][0];s['bibliography']={'title':'Article','document_type':'J','year':'2024'}
    r=client.patch('/api/articles/'+a['id'],headers=H,json={'revision':a['revision'],'stage':'sources','changes':{'sources':[s]}})
    assert r.status_code==200 and r.json()['sources'][0]['bibliography']['year']=='2024'


def test_source_upgrade_and_excluded_doi_are_safe(client,network,monkeypatch):
    a=store.create_article();old=source('Sold');old.update(status='abstract_only',doi='10.1000/paper',text='摘要')
    a['sources']=[old];a['content']='引用[Sold]';j=store.create_job(a['id'],{'stage':'research'})
    w=research.Research(a,j['id'],'sources')
    r=source('Snew');r.update(doi='10.1000/paper',url='https://example.org/full',provider='openalex',academic=True,content='摘要',fulltext_urls=['https://example.org/full'])
    async def verified_copy(url):
        return dict(materials.source('Verified study','Verified study findings.',url,'web'),doi='10.1000/paper')
    monkeypatch.setattr(materials,'from_url',verified_copy)
    out=asyncio.run(w.read(r))
    assert out['id']=='Sold' and a['sources'][0]['status']=='retrieved'
    assert bib.citations(a['content'],a['sources'])[1][0]['id']=='Sold'
    a['sources'][0]['selected']=False
    async def forbidden(url): pytest.fail('excluded DOI was downloaded')
    monkeypatch.setattr(materials,'from_url',forbidden)
    assert asyncio.run(w.read({**r,'url':'https://example.org/other'})) is None


def test_citation_version_restore(client):
    a=store.create_article()
    a=store.save_article(a['id'],0,lambda v:v.update(content='B[Sb] A[Sa]',sources=[source('Sa'),source('Sb')]),'引用初稿')
    a=store.save_article(a['id'],a['revision'],lambda v:v.update(content='A[Sa]'), '删除与重排')
    versions=store.versions(a['id'])
    restored=store.restore(a['id'],versions[0]['id'],a['revision'])
    assert [r['id'] for r in bib.citations(restored['content'],restored['sources'])[1]]==['Sb','Sa']


def test_metadata_cannot_be_evidence():
    s=source('Sa');s['status']='metadata_only'
    n=research.validate_spans({'evidence':[{'source_id':'Sa','quote':'Verified study findings.','claim':'a claim'}],'gaps':[]},[s])
    assert not n['evidence'] and n['issues']


def test_model_preface_single_valid_json(client,network,monkeypatch):
    original=providers.generate
    async def wrapped(*args,**kwargs):
        raw,usage=await original(*args,**kwargs);return 'Additional gateway text\n```json\n'+raw+'\n```',usage
    monkeypatch.setattr(providers,'generate',wrapped)
    a=store.create_article();j=store.create_job(a['id'],{'stage':'research'})
    from backend.models import ResearchPlan
    p=asyncio.run(research.structured(a,'sources','query',ResearchPlan,j['id']))
    assert p['needed'] and p['academic']


def test_arxiv_openalex_same_preprint_id():
    a=source('Sa','PP');a['doi']='10.48550/arXiv.2312.10997'
    b=source('Sb','PP');b['url']='https://arxiv.org/abs/2312.10997v2'
    assert len(academic.merge_records([a,b]))==1


def test_pdf_ligatures_and_linebreaks_recover_original_quote():
    text='We explore a ﬁne-tuning method with mem-\nory and evidence.'
    s=source('Sa');s.update(text=text,pages=[{'page':1,'text':text}])
    n=research.validate_spans({'evidence':[{'source_id':'Sa','quote':'We explore a fine-tuning method with memory and evidence.','claim':'method'}],'gaps':[]},[s])
    assert n['evidence'][0]['quote']==text and n['evidence'][0]['page']==1
    n=research.validate_spans({'evidence':[{'source_id':'Sa','quote':'We explore a wrong method with memory and evidence.','claim':'wrong'}],'gaps':[]},[s])
    assert not n['evidence'] and n['issues']
