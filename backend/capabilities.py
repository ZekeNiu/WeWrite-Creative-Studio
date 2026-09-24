"""Per-model tests; never reassign an article route as a side effect."""
import io
from PIL import Image
from . import store,providers,security,search_tools,outputs
from . import public_network
from .models import ROUTES
from .service_errors import ServiceFailure,SearchEvidenceMissing,service_identity


SEARCH_UNCONFIGURED='尚未发送搜索请求：请配置模型原生联网接口；仍可配合工作台已配置的搜索服务使用。'


def metadata(s,kind):
    return dict(model=s['model'],protocol=s['protocol'],test_version=providers.capability_version(kind),
        parameters=providers.test_parameters(s,kind),service=service_identity(s))


def search_protocol(cfg,sid,model):
    item=next((p for p in cfg.get('model_connections',[]) if p['service_id']==sid and p['model']==model),None)
    if item: return item['search_protocol']
    search=cfg['search'];service=next((s for s in cfg['services'] if s['id']==sid),{})
    if sid==(search['native_service_id'] or cfg['default_service']) and model==(search['native_model'] or service.get('model')):
        return search['native_protocol']
    return 'inherit'


def resolve(cfg,sid,model,kind,protocol=None):
    s=next((dict(s) for s in cfg['services'] if s['id']==sid),None)
    if not s: raise ValueError('找不到模型服务')
    s['model']=model;s['secret']=security.key(sid)
    if not model or not s['secret']: raise ValueError('请先填写 Key 和模型名称')
    if kind=='search':
        choice=protocol or search_protocol(cfg,sid,model)
        if choice!='inherit': s['protocol']=choice
    return s


def cards(cfg):
    rows={}
    def add(sid,model,role):
        service=next((s for s in cfg['services'] if s['id']==sid),None)
        if not service: return
        model=model or service['model'];key=(sid,model)
        card=rows.setdefault(key,dict(service_id=sid,model=model,name=service['name'],roles=[],search_protocol=search_protocol(cfg,sid,model),capabilities={}))
        if role not in card['roles']: card['roles'].append(role)
    for s in cfg['services']: add(s['id'],s['model'],'default')
    for role in ROUTES:
        route=cfg['routes'].get(role,{})
        sid=route.get('service_id') or cfg['default_service']
        if role=='research' and not route.get('service_id'):
            inherited=cfg['routes'].get('sources',{});sid=inherited.get('service_id') or cfg['default_service']
            model=route.get('model') or inherited.get('model','')
        else: model=route.get('model','')
        add(sid,model,role)
    add(cfg['search']['native_service_id'] or cfg['default_service'],cfg['search']['native_model'],'search')
    for card in rows.values():
        for kind in ('text','tools','image','search'):
            try:
                s=resolve(cfg,card['service_id'],card['model'],kind)
                value=store.capability(providers.fingerprint(s,kind))
                if kind=='search' and s['protocol']=='chat': value=dict(status='unused',message=SEARCH_UNCONFIGURED,request_sent=False,**metadata(s,kind))
            except ValueError as exc: value=dict(status='unconfigured',message=str(exc))
            card['capabilities'][kind]=value
    return list(rows.values())


async def test(sid,request):
    from . import execution_budget as budget
    cfg=providers.settings();kind=request.kind
    s=resolve(cfg,sid,request.model,kind,request.protocol)
    key=providers.fingerprint(s,kind)
    if kind=='search' and s['protocol']=='chat':
        return dict(status='unused',message=SEARCH_UNCONFIGURED,request_sent=False,**metadata(s,kind))
    job=store.create_job('connection-'+kind,dict(stage=kind)) if kind!='tools' else None
    record=None;charged=False
    try:
        if kind=='text':
            s['max_tokens']=256
            record=budget.reserve(job['id'],s,'你是连接测试助手。请只回复：连接成功')
            text,usage=await providers.generate(s,'你是连接测试助手。','请只回复：连接成功')
            if not text.strip():raise ValueError('接口未返回有效文本')
            result=dict(message='小样本文本连接已通过（输出上限 256 Token）；不代表完整创作流程已通过',reply=text[:100],usage=usage)
        elif kind=='tools':result=await test_tools(s)
        elif kind=='image':
            record=budget.reserve(job['id'],dict(s,input_price=None,output_price=None),fixed=s.get('image_price'))
            blob=await providers.image_generate(s,'A single green leaf on an ivory background, minimal editorial illustration, no text','1024x1024')
            img=Image.open(io.BytesIO(blob));img.load();filename=store.uid()+'.png'
            img.convert('RGB').save(outputs.diagnostics()/filename)
            usage=dict(status='completed',estimated_cost=s.get('image_price'))
            result=dict(message='收到实际图片，生图连接测试通过',width=img.width,height=img.height,image_url='/api/connection-tests/'+filename)
        else:
            query='查找世界卫生组织身体活动指南的官方网页'
            s['_job_id']=job['id']
            record=budget.reserve(job['id'],s,query,2000,s.get('search_price'))
            rows,meta=await search_tools.native(s,query,1)
            usage=budget.search_usage(s,meta)
            budget.charge(record,usage);charged=True
            if not any([await public_network.public_url(r['url']) for r in rows]):
                exc=SearchEvidenceMissing('接口已响应，但搜索未返回公开来源',usage)
                exc.details['search_diagnostic']=meta.get('search_diagnostic');raise exc
            result=dict(message=f'联网已通过：取得真实搜索工具记录及 {len(rows)} 个来源',sources=rows,usage=meta,queries=meta.get('queries',[]),search_diagnostic=meta.get('search_diagnostic'))
        if record and not charged:budget.charge(record,usage);charged=True
        result.update(status='tested',request_sent=True,response_received=True,**metadata(s,kind))
        store.capability(key,result)
        if kind in ('text','image'):
            raw=store.get_settings()
            for row in raw.get('services',[]):
                if row['id']==sid and row['model']==s['model']:row['status' if kind=='text' else 'image_status']='tested'
            store.set_settings(raw)
        if job:store.update_job(job['id'],status='completed',ended=store.now())
        return dict(result,at=store.capability(key)['at'])
    except BaseException as exc:
        if record and not charged:budget.charge(record,getattr(exc,'usage',None) or dict(status='unknown',estimated_cost=None))
        if job:store.update_job(job['id'],status='failed',ended=store.now())
        if not isinstance(exc,Exception):raise
        message=str(exc) if isinstance(exc,ValueError) else '连接或结果解析失败，请检查服务配置'
        if s['secret']:message=message.replace(s['secret'],'[已隐藏]')
        details=getattr(exc,'details',None) or dict(category='validation',request_sent=bool(record) or kind=='tools')
        store.capability(key,dict(status='failed',message=message,failure=details,
            **({'search_diagnostic':details['search_diagnostic']} if details.get('search_diagnostic') else {}),
            **{k:details[k] for k in ('request_sent','response_received') if k in details},**metadata(s,kind)))
        if hasattr(exc,'details'):raise
        raise ServiceFailure(message,**details) from None


async def test_tools(service):
    import json
    from . import agent_transport,execution_budget
    job=store.create_job('connection-tools',dict(stage='tools',execution_limits={'max_requests':2}))
    s=dict(service,_job_id=job['id'])
    spec=dict(name='connection_probe',description='读取测试随机值',parameters=dict(type='object',properties={},required=[],additionalProperties=False))
    system='先调用 connection_probe，然后逐字返回工具提供的随机值，不添加其他内容。'
    messages=[dict(role='user',content='开始工具往返测试')]
    marker=store.uid()
    try:
        for index in range(2):
            s['_tool_choice']='required' if index==0 else 'auto'
            record=execution_budget.reserve(job['id'],s,system+json.dumps(messages))
            try:r=await agent_transport.turn(s,system,messages,[spec])
            except BaseException as exc:
                execution_budget.charge(record,getattr(exc,'usage',None) or dict(status='unknown',estimated_cost=None));raise
            execution_budget.charge(record,r['usage']);messages.extend(r['wire'])
            if index==0:
                if len(r['calls'])!=1 or r['calls'][0]['name']!='connection_probe':
                    raise agent_transport.response_error(s,'missing_tool_call' if r['text'] else 'empty_response',
                        '接口已响应，但未返回要求的工具调用；当前接入的工具能力未验证',r.get('diagnostic',{}),r['usage'])
                agent_transport.append_results(s['protocol'],messages,[(r['calls'][0]['id'],marker)])
            elif r['calls'] or r['text'].strip()!=marker:raise ValueError('模型未正确使用工具返回值，多轮调用未验证')
        store.update_job(job['id'],status='completed',ended=store.now())
        return dict(message='基础工具往返已通过（实际服务参数，2 次请求）；完整选题仍需实际运行',diagnostic=store.job(job['id']).get('response_diagnostic'))
    except BaseException:
        store.update_job(job['id'],status='failed',ended=store.now());raise
