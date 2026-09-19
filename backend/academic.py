"""Public scholarly discovery, provenance and conservative record merging."""
import asyncio
import re
import time
import unicodedata
import xml.etree.ElementTree as ET
from urllib.parse import quote, urlsplit
import httpx
from bs4 import BeautifulSoup
from . import store, security

UA='WeWriteStudio/1.3 (local scholarly reference manager)'
_last={}


async def request(channel,url,params=None):
    now=time.monotonic();slot=max(now,_last.get(channel,0)+(3.1 if channel=='arxiv' else 1.0));_last[channel]=slot
    await asyncio.sleep(max(0,slot-now))
    headers={'User-Agent':UA}
    if channel=='openalex':
        key=security.key('openalex')
        if key: headers['Authorization']='Bearer '+key
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            r=await client.get(url,params=params,headers=headers)
            if r.status_code==429: raise ValueError(channel+' 额度或速率受限，已切换渠道，不自动开通付费服务')
            r.raise_for_status();return r
    except httpx.HTTPError: raise ValueError(channel+' 暂时不可用，正在切换学术来源') from None


def normalized_doi(value):
    return re.sub(r'^https?://(?:dx\.)?doi.org/', '', value or '',flags=re.I).lower().strip().rstrip('.,;')


def identifiers(s):
    b=s.get('bibliography') or {};result=set()
    for key in ('doi','pmid','pmcid','arxiv_id'):
        v=s.get(key) or b.get(key)
        if v: result.add((key,normalized_doi(v) if key=='doi' else re.sub(r'v\d+$','',str(v))))
    for value in (s.get('url',''),s.get('doi',''),b.get('doi','')):
        match=re.search(r'(?:arxiv\.|arxiv\.org/(?:abs|pdf|html)/)(\d{4}\.\d{4,5})(?:v\d+)?',value,re.I)
        if match: result.add(('arxiv_id',match[1]))
    return result


def distinct_versions(a,b):
    am=a.get('bibliography') or {};bm=b.get('bibliography') or {}
    if am.get('document_type') and bm.get('document_type') and ('PP'==am['document_type']) != ('PP'==bm['document_type']): return True
    def version(s,m):
        match=re.search(r'\d{4}\.\d{4,5}(v\d+)',s.get('arxiv_id','')+' '+s.get('url',''),re.I)
        return str(m.get('version') or (match[1] if match else '')).lower().strip()
    av,bv=version(a,am),version(b,bm)
    return bool(av and bv and av!=bv)


def same(a,b):
    if distinct_versions(a,b): return False
    ai,bi=identifiers(a),identifiers(b)
    if ai & bi: return True
    # Do not merge a preprint and a journal version based on title similarity alone.
    am=a.get('bibliography') or {};bm=b.get('bibliography') or {}
    if ('PP'==am.get('document_type')) != ('PP'==bm.get('document_type')): return False
    if a.get('url') and a['url'].rstrip('/')==b.get('url','').rstrip('/'): return True
    if {x[0] for x in ai}&{x[0] for x in bi}: return False
    title=lambda x:re.sub(r'[^\w]','',unicodedata.normalize('NFKC',x.get('title','')).lower())
    t=title(a)
    # Title alone cannot establish that two independent sources are the same work.
    return (len(t)>20 and t==title(b) and bool(am.get('authors')) and am.get('authors')==bm.get('authors')
            and bool(am.get('year')) and am.get('year')==bm.get('year') and am.get('venue')==bm.get('venue'))


def combine(old,new):
    rank={'retrieved':4,'user_provided':4,'abstract_only':3,'excerpt_only':2,'metadata_only':1,'unreadable':0}
    upgrade=rank.get(new.get('status'),0)>rank.get(old.get('status'),0)
    merged={**old,**({k:v for k,v in new.items() if v} if upgrade else {k:v for k,v in new.items() if not old.get(k)})}
    for k in ('id','selected','personal_material','use','issue_ids'):
        if k in old: merged[k]=old[k]
    merged['bibliography']={**(new.get('bibliography') or {}),**{k:v for k,v in (old.get('bibliography') or {}).items() if v}}
    new_authors=(new.get('bibliography') or {}).get('authors',[])
    if new_authors and all(isinstance(a,dict) for a in new_authors) and any(isinstance(a,str) for a in merged['bibliography'].get('authors',[])):
        merged['bibliography']['authors']=new_authors
    for field in ('discovery_channels','fulltext_urls','metadata_provenance'):
        values=old.get(field,[])+new.get(field,[])
        if field=='discovery_channels': values += [x for x in (old.get('provider'),new.get('provider')) if x]
        merged[field]=[]
        for v in values:
            if v not in merged[field]: merged[field].append(v)
    return merged


def merge_records(rows):
    result=[]
    for row in rows:
        i=next((i for i,x in enumerate(result) if same(x,row)),None)
        if i is None: result.append(row)
        else: result[i]=combine(result[i],row)
    return result


def row(m,channel,abstract='',fulltext=None,**ids):
    m['access_date']=store.now()[:10]
    return dict(title=m['title'],url=m['url'],doi=m.get('doi',''),bibliography=m,content=abstract,
        status='abstract_only' if abstract else 'metadata_only',provider=channel,academic=True,
        fulltext_urls=list(dict.fromkeys(u for u in (fulltext or []) if u)),discovery_channels=[channel],
        metadata_provenance=[{'provider':channel,'url':m['url'],'retrieved_at':store.now()}],**ids)


def crossref_record(w):
    date=(w.get('published') or w.get('issued') or {}).get('date-parts',[[]])[0]
    title=(w.get('title') or [''])[0];doi=w.get('DOI','')
    m=dict(title=title,authors=[{k:a.get(k,'') for k in ('family','given')} for a in w.get('author',[])],
        document_type={'journal-article':'J','proceedings-article':'C','posted-content':'PP','book':'M','book-chapter':'M','dissertation':'D','report':'R'}.get(w.get('type'),''),
        venue=(w.get('container-title') or [''])[0],year=str(date[0]) if date else '',volume=w.get('volume',''),issue=w.get('issue',''),
        pages=w.get('page',''),article_number=w.get('article-number',''),doi=doi,url=w.get('URL') or 'https://doi.org/'+doi,
        published_date='-'.join(str(n).zfill(2) for n in date))
    abstract=BeautifulSoup(w.get('abstract',''),'html.parser').get_text(' ',strip=True)
    links=[l['URL'] for l in w.get('link',[]) if l.get('URL') and l.get('content-type') in ('application/pdf','text/html')]
    result=row(m,'crossref',abstract,links)
    result['canonical_urls']=[u for u in [w.get('resource',{}).get('primary',{}).get('URL'),w.get('URL')] if u]
    return result


async def crossref(query):
    r=await request('crossref','https://api.crossref.org/works',{'query.bibliographic':query,'rows':6})
    return [crossref_record(w) for w in r.json().get('message',{}).get('items',[])]


async def lookup_doi(doi):
    doi=normalized_doi(doi)
    if not re.fullmatch(r'10\.\d{4,9}/\S+',doi): raise ValueError('请输入有效 DOI，例如 10.1234/example')
    cache=store.cache_get('doi:'+doi)
    if cache: return cache
    r=await request('crossref','https://api.crossref.org/works/'+quote(doi,safe=''))
    result=crossref_record(r.json()['message']);store.cache_put('doi:'+doi,result,30*86400);return result


async def openalex(query):
    r=await request('openalex','https://api.openalex.org/works',{'search':query,'per_page':6})
    result=[]
    for w in r.json().get('results',[]):
        inv=w.get('abstract_inverted_index') or {}; words={p:t for t,ps in inv.items() for p in ps};abstract=' '.join(words[p] for p in sorted(words))
        loc=w.get('primary_location') or {};journal=loc.get('source') or {};b=w.get('biblio') or {};doi=normalized_doi(w.get('doi'))
        urls=[]
        for location in [w.get('best_oa_location') or {},*w.get('locations',[])]:
            if location.get('is_oa'):
                urls.extend([location.get('pdf_url'),location.get('landing_page_url')])
        preprint=w.get('type')=='preprint' or doi.startswith('10.48550/arxiv.')
        m=dict(title=w.get('title') or w.get('display_name',''),authors=[a['author']['display_name'] for a in w.get('authorships',[]) if a.get('author',{}).get('display_name')],
            document_type='PP' if preprint else 'C' if w.get('type')=='proceedings-article' or journal.get('type')=='conference' else {'article':'J','review':'J','book':'M','book-chapter':'M','dissertation':'D','report':'R'}.get(w.get('type'),''),
            venue=journal.get('display_name',''),year=str(w.get('publication_year') or ''),volume=b.get('volume') or '',issue=b.get('issue') or '',
            pages=(b.get('first_page') or '')+('-'+b['last_page'] if b.get('last_page') and b.get('last_page')!=b.get('first_page') else ''),
            doi=doi,url=('https://doi.org/'+doi if doi else loc.get('landing_page_url') or w['id']),published_date=w.get('publication_date',''))
        ids=w.get('ids') or {};pmid=urlsplit(ids.get('pmid') or '').path.strip('/')
        result.append(row(m,'openalex',abstract,urls,pmid=pmid,openalex_id=w['id']))
    return result


async def arxiv(query):
    # Free text -> all-field search; retain the user's AND/OR only through explicit terms.
    terms=re.findall(r'[\w-]+',query)[:14]
    r=await request('arxiv','https://export.arxiv.org/api/query',{'search_query':' AND '.join('all:'+t for t in terms),'start':0,'max_results':6})
    ns={'a':'http://www.w3.org/2005/Atom','x':'http://arxiv.org/schemas/atom'};root=ET.fromstring(r.content);result=[]
    for e in root.findall('a:entry',ns):
        get=lambda p:e.findtext(p,'',ns)
        url=get('a:id').replace('http://','https://');identifier=url.split('/abs/')[-1]
        if '/abs/' not in url: continue
        m=dict(title=' '.join(get('a:title').split()),authors=[x.findtext('a:name','',ns) for x in e.findall('a:author',ns)],
            document_type='PP',platform='arXiv',year=get('a:published')[:4],published_date=get('a:updated')[:10],url=url,
            version=re.search(r'v\d+$',identifier)[0] if re.search(r'v\d+$',identifier) else '')
        # Journal DOI is a relation, not the DOI of the preprint version.
        item=row(m,'arxiv',' '.join(get('a:summary').split()),['https://arxiv.org/html/'+identifier,'https://arxiv.org/pdf/'+identifier],arxiv_id=identifier)
        if get('x:doi'): item['related_publication_doi']=get('x:doi')
        result.append(item)
    return result
