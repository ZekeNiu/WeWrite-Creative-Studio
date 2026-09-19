"""Real search tool adapters. A prose answer alone is never a successful search."""
import asyncio
import json
import re
import time
from urllib.parse import quote
import xml.etree.ElementTree as ET
import httpx
from . import providers, materials


async def native(s,query,limit=1):
    if s['protocol']=='gemini': return await gemini(s,query,limit)
    if s['protocol']=='responses':
        path='responses'
        body={'model':s['model'],'input':'联网检索以下问题，优先原始来源，返回出处：'+query,
              'tools':[{'type':'web_search'}],'tool_choice':'required','max_tool_calls':limit,
              'include':['web_search_call.action.sources'],'max_output_tokens':2000,'stream':False}
    elif s['protocol']=='anthropic':
        path='messages'
        body={'model':s['model'],'max_tokens':2000,'stream':False,
              'messages':[{'role':'user','content':'请使用 web_search 搜索并列出来源：'+query}],
              'tools':[{'type':'web_search_20250305','name':'web_search','max_uses':limit}]}
    else: raise ValueError('当前文本协议未接入原生搜索；将使用其他检索渠道')
    started=time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(100,connect=15)) as client:
            async with client.stream('POST',providers.endpoint(s['base_url'],path),headers=providers.headers(s),json=body) as response:
                if response.status_code>=400: raise ValueError(providers.http_error(response.status_code))
                if 'text/event-stream' in response.headers.get('content-type',''):
                    result={}; blocks=[]; completed=False
                    async for frame in providers.frames(response):
                        if frame=='[DONE]': continue
                        event=json.loads(frame)
                        if event.get('error') or event.get('type') in ('error','response.failed'): raise ValueError('搜索工具返回错误')
                        if event.get('type') in ('response.completed','response.done'): result=event.get('response',{});completed=True
                        if event.get('type')=='message_start': result=event.get('message',{})
                        if event.get('type')=='content_block_start': blocks.append(event.get('content_block',{}))
                        if event.get('type')=='message_delta': result.setdefault('usage',{}).update(event.get('usage',{}))
                        if event.get('type')=='message_stop': completed=True
                    if not completed: raise ValueError('搜索流中断，未收到完成信号；本任务不自动重复该付费请求')
                    if blocks: result['content']=blocks
                else: result=json.loads(await response.aread())
    except httpx.TimeoutException: raise ValueError('原生搜索超时，可能已计费；本任务不重复请求该服务') from None
    except httpx.HTTPError: raise ValueError('原生搜索连接失败，正在尝试其他渠道') from None
    rows=[]; calls=0
    if s['protocol']=='responses':
        for item in result.get('output',[]):
            if item.get('type')=='web_search_call' and item.get('status')=='completed':
                calls+=1
                for source in item.get('action',{}).get('sources',[]):
                    if source.get('url'): rows.append({'url':source['url'],'title':source.get('title') or source['url'],'content':'','provider':'native'})
        # Citations count only when an actual completed tool call is present.
        if calls:
            for item in result.get('output',[]):
                for content in item.get('content',[]):
                    for c in content.get('annotations',[]):
                        if c.get('type')=='url_citation' and c.get('url'):
                            rows.append({'url':c['url'],'title':c.get('title') or c['url'],'content':'','provider':'native'})
    else:
        used={b.get('id') for b in result.get('content',[]) if b.get('type')=='server_tool_use' and b.get('name')=='web_search'}
        for b in result.get('content',[]):
            if b.get('type')!='web_search_tool_result' or b.get('tool_use_id') not in used: continue
            if not isinstance(b.get('content'),list): continue
            calls+=1
            for c in b['content']:
                if c.get('type')=='web_search_result' and c.get('url'):
                    rows.append({'url':c['url'],'title':c.get('title') or c['url'],'content':'','provider':'native','published_date':c.get('page_age','')})
    if not calls or not rows: raise ValueError('未取得真实搜索工具记录和来源，不能确认此模型支持联网搜索')
    if calls>limit: raise ValueError('中转站未遵守搜索工具次数上限，请核对账单；已停止使用该渠道')
    rows=list({r['url']:r for r in rows}.values())
    return rows,{'calls':calls,'seconds':round(time.monotonic()-started,2),'usage':result.get('usage',{})}


async def gemini(s,query,limit=1):
    # Use only the configured gateway. A relay credential must never be sent elsewhere.
    base=re.sub(r'/(?:v1|v1beta)/?$', '', s['base_url'].rstrip('/'))
    url=base+'/v1beta/models/'+quote(s['model'].removeprefix('models/'),safe='')+':generateContent'
    started=time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(100,connect=15)) as client:
            r=await client.post(url,headers={'x-goog-api-key':s['secret'],'Authorization':'Bearer '+s['secret']},
                json={'contents':[{'role':'user','parts':[{'text':'请使用 Google Search 检索并给出来源：'+query}]}],
                      'tools':[{'google_search':{}}], 'generationConfig':{'maxOutputTokens':2000}})
            if r.status_code>=400: raise ValueError(providers.http_error(r.status_code))
            data=r.json()
    except httpx.TimeoutException: raise ValueError('Gemini 联网测试超时，可能已计费，不自动重复提交') from None
    except (httpx.HTTPError,ValueError) as exc:
        if isinstance(exc,ValueError) and not isinstance(exc,json.JSONDecodeError): raise
        raise ValueError('Gemini 联网接口连接或响应格式异常；当前接入方式未验证') from None
    rows=[];queries=[]
    for c in data.get('candidates',[]):
        ground=c.get('groundingMetadata',{})
        queries.extend(ground.get('webSearchQueries',[]))
        for index,chunk in enumerate(ground.get('groundingChunks',[])):
            web=chunk.get('web',{})
            if web.get('uri'):
                excerpts=[x.get('segment',{}).get('text','') for x in ground.get('groundingSupports',[]) if index in x.get('groundingChunkIndices',[])]
                rows.append(dict(url=web['uri'],title=web.get('title') or web['uri'],content=' '.join(excerpts),provider='native',snippet_kind='grounded_summary',status='excerpt_only'))
    if not queries or not rows: raise ValueError('未取得真实搜索工具记录和来源；当前 Gemini 接入方式未验证')
    # Gemini can expand a request into several queries; record actual queries separately.
    return list({r['url']:r for r in rows}.values()),dict(calls=len(set(queries)),queries=queries,seconds=round(time.monotonic()-started,2),
        usage={'input_tokens':data.get('usageMetadata',{}).get('promptTokenCount'), 'output_tokens':data.get('usageMetadata',{}).get('candidatesTokenCount')})


_ncbi_last=0.0


async def ncbi(client,path,params):
    global _ncbi_last
    # All operations run on the backend event loop; reserve a slot before awaiting.
    now=time.monotonic(); slot=max(now,_ncbi_last+.4); _ncbi_last=slot
    await asyncio.sleep(max(0,slot-now))
    r=await client.get('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'+path,params={**params,'tool':'WeWriteStudio'})
    r.raise_for_status(); return r


async def pubmed(query):
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            r=await ncbi(client,'esearch.fcgi',{'db':'pubmed','term':query,'retmode':'json','retmax':5,'sort':'relevance'})
            ids=r.json().get('esearchresult',{}).get('idlist',[])
            if not ids: return []
            r=await ncbi(client,'efetch.fcgi',{'db':'pubmed','id':','.join(ids),'retmode':'xml'})
            root=ET.fromstring(r.content)
        rows=[]
        for a in root.findall('.//PubmedArticle'):
            pmid=a.findtext('.//PMID'); title=''.join(a.find('.//ArticleTitle').itertext()) if a.find('.//ArticleTitle') is not None else 'PubMed 研究'
            abstract='\n'.join(''.join(x.itertext()) for x in a.findall('.//AbstractText'))
            doi=next((x.text for x in a.findall('.//ArticleId') if x.get('IdType')=='doi'),'')
            date='-'.join(x.text or '' for x in a.findall('.//JournalIssue/PubDate/*'))
            pmc=next((x.text or '' for x in a.findall('.//ArticleId') if x.get('IdType')=='pmc'),'')
            bib=dict(title=title,authors=[{'family':x.findtext('LastName',''),'given':x.findtext('ForeName',''),'literal':x.findtext('CollectiveName','')} for x in a.findall('.//Author')],
                document_type='J',venue=a.findtext('.//Journal/Title',''),year=a.findtext('.//JournalIssue/PubDate/Year',''),
                volume=a.findtext('.//JournalIssue/Volume',''),issue=a.findtext('.//JournalIssue/Issue',''),pages=a.findtext('.//MedlinePgn',''),doi=doi,
                url='https://pubmed.ncbi.nlm.nih.gov/'+(pmid or '')+'/',access_date=__import__('datetime').date.today().isoformat())
            extra=dict(bibliography=bib,pmid=pmid,academic=True,discovery_channels=['pubmed'],metadata_provenance=[{'provider':'pubmed','url':bib['url']}])
            if pmc and re.fullmatch(r'PMC\d+',pmc):
                rows.append(dict(title=title+' [开放全文]',url='https://pmc.ncbi.nlm.nih.gov/articles/'+pmc+'/',content=abstract,
                                 provider='pubmed_fulltext',status='excerpt_only',doi=doi,published_date=date,fulltext_urls=['https://pmc.ncbi.nlm.nih.gov/articles/'+pmc+'/'],**extra))
            if pmid: rows.append(dict(title=title,url='https://pubmed.ncbi.nlm.nih.gov/'+pmid+'/',content=abstract,
                                      provider='pubmed',status='abstract_only',doi=doi,published_date=date,**extra))
        return rows
    except (httpx.HTTPError,ET.ParseError,ValueError): raise ValueError('PubMed 暂时不可用，正在尝试其他来源') from None
