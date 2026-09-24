import asyncio
import base64
import json
import hashlib
import re
import time
from urllib.parse import urlsplit
import httpx
from . import store, security
from .models import Settings, Service
from .service_errors import bind,http_failure,connection_failure


def settings():
    value=Settings.model_validate(store.get_settings() or {}).model_dump()
    for s in value['services']:
        s.pop('key',None); s['key_set']=bool(store.get_secret(s['id']))
    value['search'].pop('key',None)
    value['search']['key_set']=bool(store.get_secret('tavily'))
    value['search'].pop('openalex_key',None)
    value['search']['openalex_key_set']=bool(store.get_secret('openalex'))
    value['route_capabilities']={}
    for kind in ('image','search'):
        try:
            s=effective_service(kind,value)
            value['route_capabilities'][kind]=dict(store.capability(fingerprint(s,kind)),model=s['model'],service=s['name'])
            if kind=='search' and s['protocol']=='chat':
                value['route_capabilities'][kind].update(status='unused',reason='当前协议不使用模型自带搜索；工作台可独立检索')
        except ValueError:
            value['route_capabilities'][kind]={'status':'unconfigured'}
    from .capabilities import cards
    value['model_capabilities']=cards(value)
    return value


def fingerprint(s,kind):
    return hashlib.sha256(json.dumps([kind,s['base_url'],s['protocol'],s['model'],s.get('secret','')]).encode()).hexdigest()


def effective_service(kind,cfg=None):
    cfg=cfg or settings()
    route=cfg['search'] if kind=='search' else cfg.get('routes',{}).get(kind,{})
    sid=(route.get('native_service_id') if kind=='search' else route.get('service_id')) or cfg.get('default_service')
    s=next((dict(x) for x in cfg['services'] if x['id']==sid),None)
    if not s: raise ValueError('请先选择该能力使用的模型服务')
    s['model']=(route.get('native_model') if kind=='search' else route.get('model')) or s['model']
    if kind=='search':
        from .capabilities import search_protocol
        protocol=search_protocol(cfg,s['id'],s['model'])
        if protocol!='inherit': s['protocol']=protocol
    s['secret']=security.key(s['id'])
    if not s['secret'] or not s['model']: raise ValueError('请先填写 Key 和模型名称')
    return s


def save_settings(value: Settings):
    value=Settings.model_validate(value.model_dump())
    old=settings(); previous={s['id']:s for s in old['services']}
    ids=set(); secrets={}
    for s in value.services:
        if not s.id or s.id in ('tavily','openalex') or s.id.startswith('wewrite:') or s.id in ids: raise ValueError('服务编号重复或无效')
        ids.add(s.id); s.base_url=security.validate_base(s.base_url)
        old_s=previous.get(s.id,{})
        changed=any(getattr(s,k)!=old_s.get(k) for k in ('base_url','protocol','model')) or s.key is not None
        s.status='untested' if changed else old_s.get('status','untested')
        s.image_status='untested' if changed else old_s.get('image_status','untested')
    value.search.base_url=security.validate_base(value.search.base_url)
    referenced=[value.default_service,value.search.native_service_id]+[r.service_id for r in value.routes.values()]+[c.service_id for c in value.model_connections]
    if any(sid and sid not in ids for sid in referenced):raise ValueError('有流程仍引用已删除或不存在的服务，请重新选择后保存')
    for s in value.services:
        if s.key is not None:secrets[s.id]=security.encode_key(s.key)
        s.key=None;s.key_set=bool(secrets.get(s.id,store.get_secret(s.id)))
    if value.search.key is not None:secrets['tavily']=security.encode_key(value.search.key)
    value.search.key=None
    if value.search.openalex_key is not None:secrets['openalex']=security.encode_key(value.search.openalex_key)
    value.search.openalex_key=None
    for removed in set(previous)-ids:secrets[removed]=None
    with store.connection() as db:
        for sid,secret in secrets.items():
            if secret is None:db.execute('DELETE FROM secrets WHERE id=?',(sid,))
            else:db.execute('INSERT OR REPLACE INTO secrets VALUES(?,?)',(sid,secret))
        db.execute('INSERT OR REPLACE INTO settings VALUES(1,?)',(store.encode(value.model_dump(exclude_none=True)),))
    return settings()


def migrate_settings():
    raw=store.get_settings()
    if not raw: return
    value=Settings.model_validate(raw).model_dump(exclude_none=True)
    search=value['search'];sid=search['native_service_id'] or value['default_service']
    service=next((s for s in value['services'] if s['id']==sid),None)
    if service:
        model=search['native_model'] or service['model']
        if not any(p['service_id']==sid and p['model']==model for p in value['model_connections']):
            value['model_connections'].append(dict(service_id=sid,model=model,search_protocol=search['native_protocol']))
    if value!=raw: store.set_settings(value)


def service_for(stage, override=None):
    cfg=settings(); route=cfg.get('routes',{}).get(stage,{})
    if stage=='research' and not route.get('service_id'):
        inherited=cfg.get('routes',{}).get('sources',{})
        route={**inherited,**{k:v for k,v in route.items() if v}}
    sid=override or route.get('service_id') or cfg.get('default_service')
    s=next((s.copy() for s in cfg['services'] if s['id']==sid),None)
    if not s: raise ValueError('请先在“AI 服务”中配置并选择该环节使用的服务')
    if not override: s['model']=route.get('model') or s['model']
    if not s['model']: raise ValueError('请在“AI 服务”中填写模型名称')
    s['secret']=security.key(s['id'])
    if not s['secret']: raise ValueError('请在“AI 服务”中填写 API Key')
    return s


def endpoint(base, path):
    base=base.rstrip('/')
    for suffix in ('/chat/completions','/responses','/messages','/images/generations','/models'):
        if base.endswith(suffix): base=base[:-len(suffix)]; break
    return base+('/' if base.endswith('/v1') else '/v1/')+path


def headers(s):
    h={'Authorization':'Bearer '+s['secret'],'Content-Type':'application/json'}
    if s['protocol']=='anthropic': h.update({'x-api-key':s['secret'],'anthropic-version':'2023-06-01'})
    return h


def http_error(status,detail=''):
    from .service_errors import http_failure
    return str(http_failure(status,detail))


async def frames(response):
    data=[]
    async for line in response.aiter_lines():
        if not line:
            if data:
                yield '\n'.join(data); data=[]
        elif line.startswith('data:'): data.append(line[5:].lstrip())
    if data: yield '\n'.join(data)


class StructuredOutputUnsupported(ValueError):
    """An explicitly rejected formatting option, before any generated content."""


async def response_body(response):
    return await response.aread()


def extract_json_text(d, protocol):
    if protocol=='chat':
        content=d.get('choices',[{}])[0].get('message',{}).get('content','')
        return ''.join(x.get('text','') for x in content if isinstance(x,dict)) if isinstance(content,list) else content or ''
    if protocol=='anthropic': return ''.join(x.get('text','') for x in d.get('content',[]) if x.get('type')=='text')
    return d.get('output_text') or ''.join(c.get('text','') for x in d.get('output',[]) for c in x.get('content',[]) if c.get('type')=='output_text')


async def generate(s, system, prompt, emit=None):
    from . import execution_budget
    return await execution_budget.text_request(_generate,s,system,prompt,emit)


async def _generate(s, system, prompt, emit=None):
    protocol=s['protocol']; started=time.monotonic(); text=''; usage={}; completed=False; truncated=False
    common={'model':s['model'],'stream':s.get('stream',True)}
    if protocol=='chat':
        path='chat/completions'; body=dict(common,messages=[{'role':'system','content':system},{'role':'user','content':prompt}],max_tokens=s.get('max_tokens',8000))
        if common['stream']:body['stream_options']={'include_usage':True}
        if s.get('response_schema'):
            body['response_format']=dict(type='json_schema',json_schema=dict(name='research_result',schema=s['response_schema'],strict=False))
    elif protocol=='responses':
        path='responses'; body=dict(common,instructions=system,input=prompt,max_output_tokens=s.get('max_tokens',8000))
    else:
        path='messages'; body=dict(common,system=system,messages=[{'role':'user','content':prompt}],max_tokens=s.get('max_tokens',8000))
    if s.get('temperature') is not None: body['temperature']=s['temperature']
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(240,connect=20)) as client:
            async with client.stream('POST',endpoint(s['base_url'],path),headers=headers(s),json=body) as response:
                if response.status_code>=400:
                    detail=(await response_body(response)).decode('utf-8',errors='replace')
                    if response.status_code in (400,422) and body.get('response_format') and re.search(r'response_format|json_schema|json schema|structured.output',detail.lower()) and re.search(r'unsupported|not supported|not support|does not support|unrecognized|unknown parameter|不支持|未知参数',detail.lower()):
                        raise StructuredOutputUnsupported('当前接口明确不支持结构化输出参数')
                    raise bind(http_failure(response.status_code,detail,response.headers),s)
                if 'text/event-stream' not in response.headers.get('content-type',''):
                    raw=await response_body(response); d=json.loads(raw)
                    if d.get('error'): raise bind(http_failure(response.status_code,json.dumps(d),response.headers),s)
                    text=extract_json_text(d,protocol); usage=d.get('usage',{})
                    completed=True
                    if protocol=='chat' and common['stream'] is False:
                        choices=d.get('choices',[])
                        if len(choices)!=1:raise ValueError('模型没有返回唯一的完整结果')
                        completed=bool(choices[0].get('finish_reason'))
                    truncated=d.get('status')=='incomplete' or d.get('stop_reason')=='max_tokens' or any(x.get('finish_reason')=='length' for x in d.get('choices',[]))
                    if emit: await emit(text)
                else:
                    async for frame in frames(response):
                        if frame=='[DONE]': continue
                        try: d=json.loads(frame)
                        except json.JSONDecodeError: raise ValueError('模型流格式无效，已保留此前返回内容') from None
                        if d.get('error') or d.get('type') in ('error','response.failed'):
                            raise bind(http_failure(response.status_code,json.dumps(d.get('response') or d),response.headers),s)
                        delta=''
                        if protocol=='chat':
                            for choice in d.get('choices',[]):
                                delta+=choice.get('delta',{}).get('content') or ''
                                if choice.get('finish_reason'):
                                    completed=True; truncated=choice['finish_reason']=='length'
                            if d.get('usage'): usage=d['usage']
                        elif protocol=='anthropic':
                            if d.get('type')=='content_block_delta' and d.get('delta',{}).get('type')=='text_delta': delta=d['delta'].get('text','')
                            if d.get('type')=='message_start': usage.update(d.get('message',{}).get('usage',{}))
                            if d.get('type')=='message_delta':
                                usage.update(d.get('usage',{})); truncated=d.get('delta',{}).get('stop_reason')=='max_tokens'
                            if d.get('type')=='message_stop': completed=True
                        else:
                            if d.get('type')=='response.output_text.delta': delta=d.get('delta','')
                            if d.get('type') in ('response.completed','response.incomplete'):
                                completed=True; truncated=d['type']=='response.incomplete'; usage=d.get('response',{}).get('usage',{})
                        if delta:
                            text+=delta
                            if emit: await emit(delta)
    except httpx.HTTPError as exc:
        raise bind(connection_failure(exc),s) from None
    if not completed: raise ValueError('模型连接提前结束，未收到完成信号；部分结果已保留')
    if truncated: raise ValueError('模型输出达到长度上限；请提高最大输出长度后重试，部分结果已保留')
    if not text.strip(): raise ValueError('模型未返回可用正文，请检查该模型和协议是否匹配')
    inp=usage.get('input_tokens',usage.get('prompt_tokens'))
    out=usage.get('output_tokens',usage.get('completion_tokens'))
    cost=None
    if inp is not None and out is not None and s.get('input_price') is not None and s.get('output_price') is not None:
        cost=(inp*s['input_price']+out*s['output_price'])/1_000_000
    return text,dict(model=s['model'],service=s['name'],input_tokens=inp,output_tokens=out,seconds=round(time.monotonic()-started,2),estimated_cost=cost,currency=s.get('currency','CNY'),status='completed')


async def list_models(s):
    try:
        async with httpx.AsyncClient(timeout=25) as client:
            r=await client.get(endpoint(s['base_url'],'models'),headers=headers(s))
            if r.status_code>=400: raise ValueError(http_error(r.status_code))
            d=r.json()
            return sorted({str(x.get('id') or x.get('name')) for x in d.get('data',d.get('models',[])) if x.get('id') or x.get('name')})
    except httpx.HTTPError: raise ValueError('读取模型列表失败；可以手动填写模型名称') from None


async def image_generate(s, prompt, size, emit=None):
    body={'model':s['model'],'prompt':prompt,'n':1,'size':size,'response_format':'b64_json','stream':True}
    final=None
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(300,connect=20)) as client:
            async with client.stream('POST',endpoint(s['base_url'],'images/generations'),headers=headers(s),json=body) as r:
                if r.status_code>=400: raise bind(http_failure(r.status_code,(await r.aread()).decode('utf-8',errors='replace'),r.headers),s)
                if 'text/event-stream' in r.headers.get('content-type',''):
                    async for frame in frames(r):
                        if frame=='[DONE]': continue
                        d=json.loads(frame)
                        if d.get('error') or d.get('type') in ('error','image_generation.failed'): raise bind(http_failure(r.status_code,json.dumps(d),r.headers),s)
                        if d.get('type')=='image_generation.completed' or (d.get('data') and not d.get('type')): final=d
                        elif emit: await emit('图片正在生成…')
                else:
                    final=json.loads(await r.aread())
                    if final.get('error'):raise bind(http_failure(r.status_code,json.dumps(final),r.headers),s)
            if not final: raise ValueError('图片流未返回最终图片，不会把中间预览当作成功')
            item=(final.get('data') or [final])[0]
            if item.get('b64_json'): return base64.b64decode(item['b64_json'],validate=True)
            if item.get('url'):
                from .materials import fetch_bytes
                blob,_=await fetch_bytes(item['url'],max_bytes=30*1024*1024)
                return blob
            raise ValueError('图片接口没有返回可保存的图片')
    except httpx.HTTPError as exc: raise bind(connection_failure(exc),s) from None


async def search(query, days=None):
    cfg=settings()['search']; secret=security.key('tavily')
    identity=dict(id='tavily',name='Tavily 检索',model='tavily',protocol='search',secret=secret)
    if not secret: raise ValueError('尚未配置搜索服务，可在设置中填写 Tavily Key，或直接导入材料')
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            from datetime import datetime,timedelta,timezone
            body={
                'query':query,'max_results':8,'search_depth':'basic','include_raw_content':True,'include_answer':False,
                **({'start_date':(datetime.now(timezone.utc)-timedelta(days=days)).date().isoformat()} if days else {})}
            r=await client.post(cfg['base_url'].rstrip('/')+'/search',headers={'Authorization':'Bearer '+secret},json=body)
            if r.status_code>=400: raise bind(http_failure(r.status_code,r.text,r.headers),identity)
            return r.json().get('results',[])
    except httpx.HTTPError as exc: raise bind(connection_failure(exc),identity) from None
