"""Real search tool adapters. A prose answer alone is never a successful search."""
import asyncio
import hashlib
import json
import re
import time
from urllib.parse import quote,urlsplit
import xml.etree.ElementTree as ET
import httpx
from . import providers, materials
from .service_errors import bind,http_failure,connection_failure,SearchEvidenceMissing,ServiceFailure,service_identity


def record_search(s,diagnostic):
    if s.get('_job_id'):
        from . import store
        store.update_job(s['_job_id'],search_diagnostic=diagnostic)
        store.event(s['_job_id'],'search_response',**diagnostic)


def safe_usage(value):
    value=value if isinstance(value,dict) else {}
    def number(name,alias):
        n=value.get(name,value.get(alias))
        return n if isinstance(n,int) and not isinstance(n,bool) and n>=0 else None
    return dict(input_tokens=number('input_tokens','prompt_tokens'),output_tokens=number('output_tokens','completion_tokens'))


def search_result(s,rows,meta,limit,http_status,blocks,tool_calls):
    """Persist safe counts/usage before evidence and limit validation."""
    from .execution_budget import search_usage
    valid=[]
    for row in rows:
        try:
            url=urlsplit(row['url'])
            if url.scheme in ('http','https') and url.hostname and not url.username and not url.password:valid.append(row)
        except (ValueError,TypeError):continue
    rows=list({r['url']:r for r in valid}.values())
    managed=s['protocol']=='gemini' or (s['protocol']=='anthropic' and providers.deepseek_official(s['base_url']))
    warnings=[]
    if managed and s['protocol']=='anthropic':
        warnings.append('DeepSeek 官方内部检索次数由服务端决定，无法提前严格限制；工作台按实际发出的 API 请求执行预算，内部检索可能产生额外费用。')
    usage=search_usage(s,meta)
    diagnostic=dict(request_count=1,tool_calls=tool_calls,result_blocks=blocks,source_count=len(rows),
        tool_id_fingerprints=meta.get('tool_id_fingerprints',[]),
        provider_queries=meta['calls'] if s['protocol']=='gemini' else None,requested_limit=limit,
        limit_status='provider_managed' if managed else 'exceeded' if meta['calls']>limit else 'within_limit',warnings=warnings,
        request_sent=True,response_received=True,http_status=http_status,service=service_identity(s),usage=usage)
    meta['search_diagnostic']=diagnostic
    record_search(s,diagnostic)
    if not meta['calls'] or not rows:
        exc=SearchEvidenceMissing('接口已响应，但未取得真实搜索工具记录及有效来源；当前服务的联网接入未验证',usage)
    elif not managed and meta['calls']>limit:
        exc=bind(ServiceFailure(f'{s.get("name") or "当前服务"} 返回 {meta["calls"]} 次搜索工具调用，超过本次上限 {limit}；已保留诊断，本次调用未通过次数限制校验',category='search_limit_exceeded',request_sent=True,response_received=True,http_status=http_status),s)
        exc.usage=usage
    else:return rows,meta
    exc.details.update(http_status=http_status,search_diagnostic=diagnostic)
    raise exc


async def native(s,query,limit=1):
    trace=dict(request_sent=False,response_received=False)
    try:return await _native(s,query,limit,trace)
    except BaseException as exc:
        if isinstance(exc,(TypeError,KeyError,AttributeError)):
            exc=bind(ServiceFailure('搜索接口响应结构异常；本次未通过联网验证',category='malformed_response',
                **{k:v for k,v in trace.items() if k!='usage'}),s)
        if not getattr(exc,'usage',None) and trace.get('usage'):
            from .execution_budget import search_usage
            exc.usage=search_usage(s,dict(calls=0,usage=safe_usage(trace['usage'])))
            if s.get('search_price')!=0:exc.usage['estimated_cost']=None
        details=getattr(exc,'details',{})
        if 'search_diagnostic' not in details:
            diagnostic=dict(request_count=int(trace['request_sent']),tool_calls=None,result_blocks=None,source_count=None,requested_limit=limit,
                limit_status='unknown',warnings=[],service=service_identity(s),
                request_sent=details.get('request_sent',trace['request_sent']),response_received=details.get('response_received',trace['response_received']),
                http_status=details.get('http_status',trace.get('http_status')),usage=getattr(exc,'usage',None))
            record_search(s,diagnostic)
            if hasattr(exc,'details'):exc.details['search_diagnostic']=diagnostic
        raise exc


async def _native(s,query,limit,trace):
    if s['protocol']=='gemini': return await gemini(s,query,limit,trace)
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
            trace['request_sent']=True
            async with client.stream('POST',providers.endpoint(s['base_url'],path),headers=providers.headers(s),json=body) as response:
                trace.update(response_received=True,http_status=response.status_code)
                if response.status_code>=400: raise bind(http_failure(response.status_code,(await response.aread()).decode('utf-8',errors='replace'),response.headers),s)
                if 'text/event-stream' in response.headers.get('content-type',''):
                    result={}; blocks=[]; completed=False
                    async for frame in providers.frames(response):
                        if frame=='[DONE]': continue
                        event=json.loads(frame)
                        if event.get('error') or event.get('type') in ('error','response.failed'): raise bind(http_failure(response.status_code,json.dumps(event.get('response') or event),response.headers),s)
                        if event.get('type') in ('response.completed','response.done'): result=event.get('response',{});completed=True
                        if event.get('type')=='message_start':
                            result=event.get('message',{});trace['usage']=result.get('usage') or {}
                        if event.get('type')=='content_block_start': blocks.append(event.get('content_block',{}))
                        if event.get('type')=='message_delta':
                            result.setdefault('usage',{}).update(event.get('usage',{}));trace['usage']=result['usage']
                        if event.get('type')=='message_stop': completed=True
                    if not completed: raise bind(ServiceFailure('搜索流中断，未收到完成信号；本任务不自动重复该付费请求',category='malformed_response',request_sent=True,response_received=True,http_status=response.status_code),s)
                    if blocks: result['content']=blocks
                else:
                    result=json.loads(await response.aread())
                    if isinstance(result,dict) and result.get('error'):raise bind(http_failure(response.status_code,json.dumps(result),response.headers),s)
    except httpx.HTTPError as exc: raise bind(connection_failure(exc),s) from None
    except json.JSONDecodeError:raise bind(ServiceFailure('搜索接口响应不是有效 JSON；当前接入未验证',category='malformed_response',request_sent=True,response_received=True,http_status=response.status_code),s) from None
    if not isinstance(result,dict):raise bind(ServiceFailure('搜索接口响应结构异常；当前接入未验证',category='malformed_response',request_sent=True,response_received=True,http_status=200),s)
    trace['usage']=safe_usage(result.get('usage'))
    rows=[]; used=set(); blocks=0
    if s['protocol']=='responses':
        for index,item in enumerate(result.get('output',[])):
            if item.get('type')=='web_search_call' and item.get('status')=='completed':
                # Missing IDs count separately, never silently undercount a legacy response.
                used.add(item.get('id') or ('missing',index));blocks+=1
                for source in item.get('action',{}).get('sources',[]):
                    if source.get('url'): rows.append({'url':source['url'],'title':source.get('title') or source['url'],'content':'','provider':'native'})
        # Citations count only when an actual completed tool call is present.
        if used:
            for item in result.get('output',[]):
                for content in item.get('content',[]):
                    for c in content.get('annotations',[]):
                        if c.get('type')=='url_citation' and c.get('url'):
                            rows.append({'url':c['url'],'title':c.get('title') or c['url'],'content':'','provider':'native'})
    else:
        used={b['id'] for b in result.get('content',[]) if b.get('type')=='server_tool_use' and b.get('name')=='web_search' and isinstance(b.get('id'),str) and b['id']}
        for b in result.get('content',[]):
            if b.get('type')!='web_search_tool_result':continue
            blocks+=1
            if b.get('tool_use_id') not in used: continue
            if not isinstance(b.get('content'),list): continue
            for c in b['content']:
                if c.get('type')=='web_search_result' and c.get('url'):
                    rows.append({'url':c['url'],'title':c.get('title') or c['url'],'content':'','provider':'native','published_date':c.get('page_age','')})
    meta=dict(calls=len(used),seconds=round(time.monotonic()-started,2),usage=trace['usage'])
    # Fingerprints allow comparing repeated IDs without storing arbitrary provider text.
    meta['tool_id_fingerprints']=sorted(hashlib.sha256(str(x).encode()).hexdigest()[:16] for x in used)
    return search_result(s,rows,meta,limit,response.status_code,blocks,len(used))


async def gemini(s,query,limit=1,trace=None):
    trace=trace if trace is not None else {}
    # Use only the configured gateway. A relay credential must never be sent elsewhere.
    base=re.sub(r'/(?:v1|v1beta)/?$', '', s['base_url'].rstrip('/'))
    url=base+'/v1beta/models/'+quote(s['model'].removeprefix('models/'),safe='')+':generateContent'
    started=time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(100,connect=15)) as client:
            trace['request_sent']=True
            r=await client.post(url,headers={'x-goog-api-key':s['secret'],'Authorization':'Bearer '+s['secret']},
                json={'contents':[{'role':'user','parts':[{'text':'请使用 Google Search 检索并给出来源：'+query}]}],
                      'tools':[{'google_search':{}}], 'generationConfig':{'maxOutputTokens':2000}})
            trace.update(response_received=True,http_status=r.status_code)
            if r.status_code>=400: raise bind(http_failure(r.status_code,r.text,r.headers),s)
            data=r.json()
            if isinstance(data,dict) and data.get('error'):raise bind(http_failure(r.status_code,json.dumps(data),r.headers),s)
    except httpx.HTTPError as exc:raise bind(connection_failure(exc),s) from None
    except json.JSONDecodeError:raise bind(ServiceFailure('Gemini 联网接口响应格式异常；当前接入方式未验证',category='malformed_response',request_sent=True,response_received=True,http_status=r.status_code),s) from None
    if not isinstance(data,dict):raise bind(ServiceFailure('Gemini 搜索接口响应结构异常；当前接入未验证',category='malformed_response',request_sent=True,response_received=True,http_status=r.status_code),s)
    trace['usage']=safe_usage({'input_tokens':data.get('usageMetadata',{}).get('promptTokenCount'), 'output_tokens':data.get('usageMetadata',{}).get('candidatesTokenCount')})
    rows=[];queries=[]
    for c in data.get('candidates',[]):
        ground=c.get('groundingMetadata',{})
        queries.extend(ground.get('webSearchQueries',[]))
        for index,chunk in enumerate(ground.get('groundingChunks',[])):
            web=chunk.get('web',{})
            if web.get('uri'):
                excerpts=[x.get('segment',{}).get('text','') for x in ground.get('groundingSupports',[]) if index in x.get('groundingChunkIndices',[])]
                rows.append(dict(url=web['uri'],title=web.get('title') or web['uri'],content=' '.join(excerpts),provider='native',snippet_kind='grounded_summary',status='excerpt_only'))
    # Gemini can expand a request into several queries; record actual queries separately.
    return search_result(s,rows,dict(calls=len(set(queries)),queries=queries,seconds=round(time.monotonic()-started,2),
        usage=trace['usage']),limit,r.status_code,len(rows),None)


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
