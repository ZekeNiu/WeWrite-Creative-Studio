"""Identify a work before reading a public copy; metadata never becomes full text."""
import re
import xml.etree.ElementTree as ET
from contextvars import ContextVar
from urllib.parse import urlsplit,unquote
from . import academic,materials

API='https://www.ebi.ac.uk/europepmc/webservices/rest/'
READ_BUDGET=ContextVar('source_read_budget',default=None)


def take(kind):
    budget=READ_BUDGET.get()
    if budget is None: return
    if budget[kind]>=budget['max_'+kind]: raise ValueError('已达到本次读取或文献信息查询上限')
    budget[kind]+=1


async def search(query):
    take('metadata')
    response=await academic.request('europepmc',API+'search',dict(query=query,format='json',resultType='core',pageSize=12))
    return response.json().get('resultList',{}).get('result',[])


def record(row):
    journal=row.get('journalInfo') or {};pub=journal.get('journal') or {}
    doi=academic.normalized_doi(row.get('doi',''));pmcid=row.get('pmcid','')
    b=dict(title=row.get('title',''),doi=doi,pmid=row.get('id',''),pmcid=pmcid,year=str(row.get('pubYear','')),
        document_type='J',authors=[x.get('fullName','') for x in row.get('authorList',{}).get('author',[])],
        venue=pub.get('title',''),volume=journal.get('volume',''),issue=journal.get('issue',''),
        url='https://doi.org/'+doi if doi else 'https://europepmc.org/article/MED/'+row.get('id',''))
    result=academic.row(b,'europepmc',row.get('abstractText',''),pmid=row.get('id',''),pmcid=pmcid)
    return result


async def identify(url,hint=None):
    hint=hint or {};p=urlsplit(url);doi=hint.get('doi') or hint.get('bibliography',{}).get('doi','')
    match=re.search(r'10\.\d{4,9}/[^\s?#]+',unquote(url))
    if not doi and match: doi=match[0]
    pmc=re.search(r'PMC\d+',url,re.I)
    pmid=re.search(r'pubmed\.ncbi\.nlm\.nih\.gov/(\d+)',url)
    if doi or pmc or pmid:
        query='DOI:"'+doi+'"' if doi else 'EXT_ID:'+pmc[0].upper() if pmc else 'EXT_ID:'+pmid[1]+' AND SRC:MED'
        rows=await search(query)
        for row in rows:
            if doi and academic.normalized_doi(row.get('doi',''))!=academic.normalized_doi(doi): continue
            if pmc and row.get('pmcid','').upper()!=pmc[0].upper(): continue
            if pmid and row.get('id')!=pmid[1]: continue
            return record(row)
        if doi:
            take('metadata')
            candidate=await academic.lookup_doi(doi)
            if academic.normalized_doi(candidate.get('doi',''))==academic.normalized_doi(doi): return candidate
    # A publisher article number is only a discovery clue, never a stable identity.
    parts=p.path.strip('/').split('/')
    title=hint.get('title','')
    token=parts[-1] if parts else ''
    if not title and not re.fullmatch(r'e?\d{4,}',token): return None
    query='TITLE:"'+title.replace('"','')+'"' if title else '"'+token+'"'
    for row in await search(query):
        candidate=record(row)
        if hint and academic.same(hint,candidate): return candidate
        b=candidate['bibliography']
        if len(parts)>=4 and parts[-4]=='content' and (str(b.get('volume'))!=parts[-3] or str(b.get('issue'))!=parts[-2]): continue
        if not candidate.get('doi'): continue
        take('metadata')
        meta=await academic.lookup_doi(candidate['doi'])
        urls=meta.get('canonical_urls',[])+meta.get('fulltext_urls',[])
        mb=meta['bibliography']
        same_location=(len(parts)>=4 and parts[-4]=='content' and str(mb.get('volume'))==parts[-3]
            and str(mb.get('issue'))==parts[-2] and token in (mb.get('article_number'),mb.get('pages')))
        if any(urlsplit(u).hostname==p.hostname and (urlsplit(u).path.rstrip('/')==p.path.rstrip('/') or same_location) for u in urls):
            return academic.combine(candidate,meta)
    return None


def matches_copy(src,identity):
    expected=academic.normalized_doi(identity.get('doi',''))
    actual=academic.normalized_doi(src.get('doi') or src.get('bibliography',{}).get('doi',''))
    if actual: return bool(expected and expected==actual) and not academic.distinct_versions(src,identity)
    if src.get('pages') and expected:
        front=src['text'][:4000]
        found={academic.normalized_doi(x) for x in re.findall(r'10\.\d{4,9}/[^\s<>]+',front)}
        return expected in found
    return False


def xml_source(blob,identity,url):
    # ElementTree does not resolve external entities. Reject documents with entity declarations.
    if b'<!ENTITY' in blob: raise ValueError('全文 XML 包含不支持的实体声明')
    root=ET.fromstring(blob);meta=root.find('./front/article-meta');body=root.find('body')
    if meta is None or body is None: raise ValueError('公开载体未提供论文正文')
    ids={x.get('pub-id-type'):''.join(x.itertext()).strip() for x in meta.findall('article-id')}
    expected=academic.normalized_doi(identity.get('doi',''))
    if expected and academic.normalized_doi(ids.get('doi',''))!=expected: raise ValueError('公开副本 DOI 不一致，未采用')
    pmcid=identity.get('pmcid','')
    if not expected and pmcid and 'PMC'+ids.get('pmc','').removeprefix('PMC')!=pmcid: raise ValueError('公开副本编号不一致，未采用')
    blocks=[]
    for node in [meta.find('abstract'),body]:
        if node is not None:
            for el in node.iter():
                if el.tag in ('title','p','table','caption'): blocks.append(' '.join(''.join(el.itertext()).split()))
    text='\n\n'.join(blocks)
    if len(text)<500: raise ValueError('公开副本正文不足，未标记为全文')
    src=materials.source(identity['title'],text,url,'web')
    src.update(doi=expected,pmcid=pmcid,bibliography=identity['bibliography'],status='retrieved',
        access_scope='fulltext',read_url=url,provider='europepmc',identity_verified=True)
    return academic.combine(src,identity)


async def read(url,hint=None):
    direct=None;failure=''
    try:
        take('pages')
        direct=await materials.read_url(url)
    except ValueError as exc: failure=str(exc)
    if direct and direct['status']=='retrieved':
        direct.update(original_url=url,read_url=direct['url'],access_scope='fulltext' if direct.get('bibliography',{}).get('document_type') in ('J','C','PP') else 'page')
        return direct
    try:
        identity=await identify(url,direct or hint)
        if identity and not direct:
            direct=materials.source(identity['title'],identity.get('content',''),url,'web')
            direct['status']='abstract_only' if identity.get('content') else 'metadata_only'
            direct=academic.combine(direct,identity)
        if identity and identity.get('pmcid'):
            fullurl=API+identity['pmcid']+'/fullTextXML'
            take('pages')
            blob,_=await materials.fetch_bytes(fullurl)
            src=xml_source(blob,identity,fullurl)
            src.update(original_url=url,access_attempts=[dict(url=url,result=failure or 'abstract'),dict(url=fullurl,result='fulltext')])
            return src
        if identity and identity.get('doi') and not identity.get('pmcid'):
            copies=list(identity.get('fulltext_urls',[]))
            try:
                take('metadata')
                for row in await academic.openalex(identity['doi']):
                    if academic.same(row,identity) and not academic.distinct_versions(row,identity): copies.extend(row.get('fulltext_urls',[]))
            except ValueError:
                pass
            for address in list(dict.fromkeys(copies))[:3]:
                if address.rstrip('/')==url.rstrip('/'): continue
                try:
                    take('pages')
                    full=await materials.read_url(address)
                    if full['status']=='retrieved' and matches_copy(full,identity):
                        full=academic.combine(full,identity)
                        full.update(original_url=url,read_url=address,access_scope='fulltext',identity_verified=True)
                        return full
                except ValueError:
                    continue
    except (ValueError,ET.ParseError):
        pass
    if direct:
        direct.update(original_url=url,access_scope='abstract' if direct['status']=='abstract_only' else 'metadata',access_error=failure)
        return direct
    raise ValueError((failure or '尚未取得正文')+'；未能确认同一文献的公开副本，可补充 DOI 或上传原文')
