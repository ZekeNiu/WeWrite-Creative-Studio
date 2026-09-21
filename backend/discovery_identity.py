"""Resolve opaque search redirects before selecting and identifying a source."""
from urllib.parse import urlsplit,urljoin
import hashlib
import httpx
from . import public_network,store,source_reader,academic


async def normalize(row):
    url=row.get('url','');host=urlsplit(url).hostname
    if host!='vertexaisearch.cloud.google.com' or '/grounding-api-redirect/' not in url:return row
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
    result=dict(row,url=target,discovery_url=url)
    # A publisher 403 can still yield a stable DOI/PMID for an alternative public copy.
    try:
        identity_key='discovery-identity:v1:'+hashlib.sha256(target.encode()).hexdigest()
        identity=store.cache_get(identity_key)
        if not identity:
            identity=await source_reader.identify(target)
            if identity:store.cache_put(identity_key,identity,86400)
        if identity:
            result=academic.combine(result,identity)
            result.update(content=identity.get('content',''),academic=True,snippet_kind='indexed_abstract',title=identity['title'],provider=row.get('provider','native'),identity_status='identified')
    except ValueError:pass
    return result
