"""Identify a work before reading a public copy; metadata never becomes full text."""
import re
import asyncio
import httpx
import xml.etree.ElementTree as ET
from contextvars import ContextVar
from urllib.parse import urlsplit,unquote
from . import academic,materials

API='https://www.ebi.ac.uk/europepmc/webservices/rest/'
READ_BUDGET=ContextVar('source_read_budget',default=None)
READ_PROGRESS=ContextVar('source_read_progress',default=None)


def progress(message):
    callback=READ_PROGRESS.get()
    if callback: callback(message)


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
    progress('正在识别文献')
    hint=hint or {};p=urlsplit(url);doi=hint.get('doi') or hint.get('bibliography',{}).get('doi','')
    match=re.search(r'10\.\d{4,9}/[^\s?#]+',unquote(url))
    if not doi and match: doi=match[0]
    pmc=re.search(r'PMC\d+',url,re.I)
    pmid=re.search(r'pubmed\.ncbi\.nlm\.nih\.gov/(\d+)',url)
    if doi or pmc or pmid:
        query='DOI:"'+doi+'"' if doi else 'PMCID:'+pmc[0].upper() if pmc else 'EXT_ID:'+pmid[1]+' AND SRC:MED'
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


def candidate_matches(src,identity):
    """A reader-verified work still has to match the discovery candidate."""
    if academic.distinct_versions(src,identity):return False
    expected=academic.normalized_doi(identity.get('doi') or identity.get('bibliography',{}).get('doi',''))
    if expected and not expected.startswith('10.48550/arxiv.'):return matches_copy(src,dict(identity,doi=expected))
    found=academic.identifiers(src);wanted=academic.identifiers(identity)
    if found & wanted:return True
    for key in ('arxiv_id','pmid','pmcid'):
        want=identity.get(key) or identity.get('bibliography',{}).get(key)
        got=src.get(key) or src.get('bibliography',{}).get(key)
        if want and got:return str(want).lower()==str(got).lower()
    # Title agreement can link a discovery page, but conflicting stable IDs always win.
    return academic.same(dict(src,url=''),dict(identity,url=''))


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
    def block(el):
        if el.tag=='table':
            blocks.append('\n'.join(' | '.join(' '.join(''.join(cell.itertext()).split()) for cell in tr if cell.tag in ('th','td')) for tr in el.iter('tr')))
        elif el.tag in ('title','p','caption','fn','label'):
            blocks.append(' '.join(''.join(el.itertext()).split()))
        else:
            for child in el:block(child)
    for node in [meta.find('abstract'),body]:
        if node is not None:block(node)
    text='\n\n'.join(blocks)
    if len(text)<500: raise ValueError('公开副本正文不足，未标记为全文')
    src=materials.source(identity['title'],text,url,'web')
    src.update(doi=expected,pmcid=pmcid,bibliography=identity['bibliography'],status='retrieved',
        access_scope='fulltext',read_url=url,provider='europepmc',identity_verified=True)
    src['references']=[]
    for ref in root.findall('./back/ref-list/ref'):
        get=lambda path:' '.join(''.join(ref.find(path).itertext()).split()) if ref.find(path) is not None else ''
        identifier=get('.//pub-id[@pub-id-type="doi"]')
        title=get('.//article-title') or ' '.join(''.join(ref.itertext()).split())
        src['references'].append(dict(doi=academic.normalized_doi(identifier),title=title,year=get('.//year')))
    src['supplementary_material']=[dict(label=' '.join(''.join(el.itertext()).split()),url=el.get('{http://www.w3.org/1999/xlink}href','')) for el in root.iter('supplementary-material')]
    return academic.combine(src,identity)


async def read(url,hint=None):
    try:
        async with asyncio.timeout(90): return await read_work(url,hint)
    except TimeoutError: raise ValueError('读取超过 90 秒，已停止；可以重试或上传原文') from None


async def read_work(url,hint=None):
    direct=None;failure=''
    identity=None
    # A stable identifier does not require first visiting a publisher's challenge page.
    if re.search(r'PMC\d+|pubmed\.ncbi\.nlm\.nih\.gov/\d+|10\.\d{4,9}/',unquote(url),re.I):
        try: identity=await identify(url,hint)
        except ValueError as exc: failure=str(exc)
    if not identity:
        try:
            progress('正在读取网页正文');take('pages')
            direct=await materials.read_url(url)
        except ValueError as exc: failure=str(exc)
    if direct and direct['status']=='retrieved':
        identifier=arxiv_identifier(direct.get('url',''))
        if identifier:
            if direct.get('pages') and not arxiv_front_matches(direct,identifier):raise ValueError('arXiv 副本首页编号与链接不一致或未能确认')
            direct.update(arxiv_id=identifier,identity_verified=True)
        expected=re.search(r'10\.\d{4,9}/[^\s?#]+',unquote(url))
        if expected and not matches_copy(direct,dict(doi=expected[0])):
            raise ValueError('读取内容与指定 DOI 未能核对一致，未采用为该论文全文')
        direct.update(original_url=url,read_url=direct['url'],access_scope='fulltext' if direct.get('bibliography',{}).get('document_type') in ('J','C','PP') else 'page')
        return direct
    arxiv_url=(direct or {}).get('url') or url
    if arxiv_identifier(arxiv_url):
        upgraded=await read_arxiv(arxiv_url,direct)
        if upgraded:return upgraded
    try:
        identity=identity or await identify(url,direct or hint)
        if identity and not direct:
            direct=materials.source(identity['title'],identity.get('content',''),url,'web')
            direct['status']='abstract_only' if identity.get('content') else 'metadata_only'
            direct=academic.combine(direct,identity)
        if identity and identity.get('pmcid'):
            fullurl=API+identity['pmcid']+'/fullTextXML'
            try:
                progress('正在读取 Europe PMC 全文');take('pages')
                blob,_=await materials.fetch_bytes(fullurl)
                src=xml_source(blob,identity,fullurl)
                src.update(original_url=url,access_attempts=[dict(url=url,result=failure or 'identified'),dict(url=fullurl,result='fulltext')])
                return src
            except (ValueError,ET.ParseError,httpx.HTTPError) as exc: failure=str(exc)
        if identity and identity.get('doi'):
            copies=[url]+list(identity.get('fulltext_urls',[]))
            try:
                take('metadata')
                for row in await academic.openalex(identity['doi']):
                    if academic.same(row,identity) and not academic.distinct_versions(row,identity): copies.extend(row.get('fulltext_urls',[]))
            except ValueError:
                pass
            for address in list(dict.fromkeys(copies))[:3]:
                if direct and direct.get('read_url')==address: continue
                try:
                    progress('正在读取公开全文副本');take('pages')
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


def arxiv_identifier(url):
    parsed=urlsplit(url)
    if parsed.hostname not in ('arxiv.org','www.arxiv.org','export.arxiv.org'):return ''
    match=re.match(r'/(?:abs|pdf|html)/(\d{4}\.\d{4,5}(?:v\d+)?)(?:\.pdf)?/?$',parsed.path)
    return match[1] if match else ''


def arxiv_front_matches(source,identifier):
    front=source['pages'][0].get('text','')
    ids=re.findall(r'arXiv\s*:\s*(\d{4}\.\d{4,5}(?:v\d+)?)',front,re.I)
    return any(x==identifier or ('v' not in identifier and re.sub(r'v\d+$','',x)==identifier) for x in ids)


async def read_arxiv(url,direct=None):
    wanted=arxiv_identifier(url)
    if not wanted:return None
    identity=None
    try:
        take('metadata')
        for row in await academic.arxiv('id:'+wanted):
            actual=row.get('arxiv_id','')
            if actual==wanted or ('v' not in wanted and re.sub(r'v\d+$','',actual)==wanted):identity=row;break
    except ValueError:pass
    # Official landing metadata is usable when the index is temporarily unavailable.
    if not identity and direct and direct.get('bibliography',{}).get('title'):
        identity=dict(title=direct['bibliography']['title'],arxiv_id=wanted,bibliography=direct['bibliography'])
    if not identity:return None
    identifier=identity['arxiv_id']
    for target in ('https://arxiv.org/html/'+identifier,'https://arxiv.org/pdf/'+identifier):
        try:
            progress('正在读取 arXiv 论文正文');take('pages')
            full=await materials.read_url(target)
            actual=arxiv_identifier(full.get('url',''))
            if actual!=identifier or full['status']!='retrieved':continue
            if full.get('pages'):
                if not arxiv_front_matches(full,identifier):continue
            full.update(title=identity['title'],arxiv_id=identifier,bibliography=identity['bibliography'],identity_verified=True,
                original_url=url,read_url=target,access_scope='fulltext')
            return full
        except ValueError:continue
    if direct:direct.update(arxiv_id=identifier,access_scope='abstract' if direct.get('status')=='abstract_only' else 'metadata')
    return direct
