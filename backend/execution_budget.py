"""A shared per-job meter for text, tool-internal searches and image requests."""
from contextvars import ContextVar
from . import store,task_progress

ACTIVE=ContextVar('paid_request_job',default=None)


def reserve(job_id,service,payload='',output=None,extra=0,fixed=None,execution_id=None):
    with store.LOCK:
        job=store.job(job_id)
        meter=job.get('execution_usage',dict(requests=0,known_cost=0,unknown=0,pending=0))
        meter.setdefault('pending',0)
        estimate=fixed
        if estimate is None and extra is not None and all(service.get(k) is not None for k in ('input_price','output_price')):
            estimate=(len(payload.encode('utf-8'))*service['input_price']+(output or service.get('max_tokens',8000))*service['output_price'])/1_000_000+extra
        meter['requests']+=1;meter['pending']+=estimate or 0
        store.update_job(job_id,execution_usage=meter)
        return store.add_usage(job['article_id'],stage=job['stage'],job_id=job_id,execution_id=execution_id,
            model=service.get('model',''),service=service.get('name',''),currency=service.get('currency','CNY'),
            status='reserved',estimated_cost=None,reservation=estimate)


def charge(record,usage):
    with store.LOCK:
        store.update_usage(record['id'],**usage)
        job=store.job(record['job_id']);meter=job['execution_usage'];meter['pending']=max(0,meter.get('pending',0)-(record.get('reservation') or 0))
        cost=usage.get('estimated_cost')
        if cost is None:meter['unknown']+=1
        else:meter['known_cost']+=cost
        store.update_job(job['id'],execution_usage=meter)


def search_usage(service,meta):
    u=meta.get('usage',{});inp=u.get('input_tokens',u.get('prompt_tokens'));out=u.get('output_tokens',u.get('completion_tokens'))
    cost=None
    if inp is not None and out is not None and all(service.get(k) is not None for k in ('input_price','output_price','search_price')):
        cost=(inp*service['input_price']+out*service['output_price'])/1_000_000+service['search_price']*meta['calls']
    return dict(status='completed',input_tokens=inp,output_tokens=out,estimated_cost=cost)


async def text_request(fn,service,system,prompt,emit=None):
    jid=ACTIVE.get()
    if not jid:return await fn(service,system,prompt,emit)
    record=reserve(jid,service,system+prompt)
    try:
        async with task_progress.request(jid,'模型调用','模型回复已收到'):
            text,usage=await fn(service,system,prompt,emit)
    except BaseException as exc:
        charge(record,dict(status='unknown',estimated_cost=None));exc._metered=True;raise
    charge(record,usage)
    return text,dict(usage,_request_id=record['id'])
