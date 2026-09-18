"""Per-model tests; never reassign an article route as a side effect."""
import io
from PIL import Image
from . import store,providers,security,search_tools,outputs
from . import public_network
from .models import ROUTES


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
        for kind in ('text','image','search'):
            try:
                s=resolve(cfg,card['service_id'],card['model'],kind)
                value=store.capability(providers.fingerprint(s,kind))
                if kind=='search' and s['protocol']=='chat': value=dict(status='unused',message='请选择此模型的联网接入方式')
            except ValueError as exc: value=dict(status='unconfigured',message=str(exc))
            card['capabilities'][kind]=value
    return list(rows.values())


async def test(sid,request):
    cfg=providers.settings();kind=request.kind
    s=resolve(cfg,sid,request.model,kind,request.protocol)
    key=providers.fingerprint(s,kind)
    if kind=='search' and s['protocol']=='chat':
        return dict(status='unused',message='当前文本接口未接入联网工具，请选择独立联网接入方式')
    try:
        if kind=='text':
            s['max_tokens']=256
            text,usage=await providers.generate(s,'你是连接测试助手。','请只回复：连接成功')
            if not text.strip(): raise ValueError('接口未返回有效文本')
            result=dict(message='文本调用成功',reply=text[:100],usage=usage)
        elif kind=='image':
            blob=await providers.image_generate(s,'A single green leaf on an ivory background, minimal editorial illustration, no text','1024x1024')
            img=Image.open(io.BytesIO(blob));img.load();filename=store.uid()+'.png'
            img.convert('RGB').save(outputs.diagnostics()/filename)
            result=dict(message='收到实际图片，生图连接测试通过',width=img.width,height=img.height,image_url='/api/connection-tests/'+filename)
        else:
            rows,meta=await search_tools.native(s,'查找世界卫生组织身体活动指南的官方网页',1)
            if not any([await public_network.public_url(r['url']) for r in rows]): raise ValueError('搜索未返回公开来源')
            result=dict(message=f'取得真实搜索工具记录及 {len(rows)} 个来源',sources=rows,usage=meta,queries=meta.get('queries',[]))
        result.update(status='tested',model=s['model'],protocol=s['protocol'])
        store.capability(key,result)
        # Legacy service badges represent only that service's default model.
        if kind in ('text','image'):
            raw=store.get_settings()
            for row in raw.get('services',[]):
                if row['id']==sid and row['model']==s['model']: row['status' if kind=='text' else 'image_status']='tested'
            store.set_settings(raw)
        store.add_usage('connection-'+kind,stage=kind,model=s['model'],service=s['name'],status='completed',estimated_cost=None)
        return dict(result,at=store.capability(key)['at'])
    except Exception as exc:
        # Persist useful failures without logging provider bodies or credentials.
        message=str(exc) if isinstance(exc,ValueError) else '连接或结果解析失败，请检查服务配置'
        if s['secret']: message=message.replace(s['secret'],'[已隐藏]')
        store.capability(key,dict(status='failed',message=message,model=s['model'],protocol=s['protocol']))
        raise ValueError(message) from None
