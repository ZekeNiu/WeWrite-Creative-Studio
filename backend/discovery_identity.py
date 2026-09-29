"""Resolve search links and enrich stable scholarly identities before selection."""
from urllib.parse import urlsplit,urljoin
import asyncio
import hashlib
import httpx
from . import public_network,store,source_reader,academic


async def normalize_many(rows):
    """Independent metadata lookups share the request budget, with bounded concurrency."""
    semaphore=asyncio.Semaphore(4)
    async def resolve(row):
        async with semaphore:
            try:
                async with asyncio.timeout(45):return await normalize(row)
            except TimeoutError:return dict(row,identity_status='timeout',identity_error='文献身份查询超时，保留候选供其他路径读取')
            except Exception:return dict(row,identity_status='unresolved',identity_error='文献身份暂未确认，保留候选供其他路径读取')
    return academic.merge_records(await asyncio.gather(*(resolve(row) for row in academic.merge_records(rows))))


async def normalize(row):
    url=row.get('url','');host=urlsplit(url).hostname
    if host!='vertexaisearch.cloud.google.com' or '/grounding-api-redirect/' not in url:
        return await enrich(row)
    key='discovery-url:v1:'+hashlib.sha256(url.encode()).hexdigest()
    target=store.cache_get(key)
    if not target:
        target=url
        async with httpx.AsyncClient(timeout=15,follow_redirects=False) as client:
            for _ in range(5):
                if not await public_network.public_url(target):raise ValueError('搜索链接重定向至非公开地址')
                source_reader.take('metadata')
                response=await client.head(target,headers={'User-Agent':'Mozilla/5.0 WeWriteStudio/1.0'})
                if not response.is_redirect:break
                target=urljoin(target,response.headers.get('location',''))
        if urlsplit(target).hostname=='vertexaisearch.cloud.google.com':return row
        if not await public_network.public_url(target):raise ValueError('搜索链接重定向至非公开地址')
        store.cache_put(key,target,86400)
    return await enrich(dict(row,url=target,discovery_url=url),resolved=True)


async def enrich(row,resolved=False):
    # Indexed records already contain factual abstracts. General web titles are
    # not enough to justify a speculative paper-identity lookup.
    if row.get('academic') and row.get('content'):return row
    ids=dict(academic.identifiers(row));target=row.get('url','')
    if ids.get('doi'):target='https://doi.org/'+ids['doi']
    elif ids.get('pmid'):target='https://pubmed.ncbi.nlm.nih.gov/'+ids['pmid']+'/'
    elif ids.get('pmcid'):target='https://pmc.ncbi.nlm.nih.gov/articles/'+ids['pmcid']+'/'
    elif not resolved:return row
    result=dict(row)
    # A publisher 403 can still yield a stable DOI/PMID for an alternative public copy.
    try:
        identity_key='discovery-identity:v2:'+hashlib.sha256(target.encode()).hexdigest()
        identity=store.cache_get(identity_key)
        if not identity:
            identity=await source_reader.identify(target)
            if identity:store.cache_put(identity_key,identity,86400)
        if identity and (resolved or academic.same(row,identity)):
            result=academic.combine(result,identity)
            abstract=identity.get('content','')
            result.update(content=abstract,academic=True,snippet_kind='indexed_abstract' if abstract else 'metadata',title=identity['title'],
                provider=row.get('provider','native'),identity_status='identified',status='abstract_only' if abstract else 'metadata_only')
            # A partial tool response still requires an independent read. Metadata
            # enrichment cannot silently turn it into verified evidence.
            if row.get('verification_required'):result.update(verification_required=True,status='metadata_only',content='')
            result.pop('identity_verified',None)
        else:result['identity_status']='unresolved'
    except ValueError:result['identity_status']='unresolved'
    return result
