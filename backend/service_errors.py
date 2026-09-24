"""Actionable, bounded diagnostics without reflecting upstream response bodies."""
import json
import math
import re
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime


class ServiceFailure(ValueError):
    def __init__(self,message,**details):
        super().__init__(message)
        self.details=details


class SearchEvidenceMissing(ValueError):
    """A valid search response without verified sources may use configured fallback."""
    def __init__(self,message,usage=None):
        super().__init__(message)
        self.details=dict(category='search_evidence_missing',request_sent=True,response_received=True,http_status=200)
        self.usage=usage


def identifier(value):
    value=str(value or '')
    return value if re.fullmatch(r'[\w.:-]{1,100}',value,re.ASCII) and not value.lower().startswith(('sk-','bearer','api_key','api-key')) else ''


def http_failure(status,detail='',headers=None):
    try:data=json.loads(detail)
    except (ValueError,TypeError):data={}
    error=data.get('error',data) if isinstance(data,dict) else {}
    error=error if isinstance(error,dict) else {}
    code=identifier(error.get('code'));kind=identifier(error.get('type'))
    message=str(error.get('message','')).strip().lower()
    category,text={
        400:('invalid_request','模型不接受当前请求，请检查接口协议、模型名称和高级参数'),
        401:('authentication','API Key 无效或已过期，请检查服务配置'),
        403:('permission','服务拒绝访问，请检查 Key 的分组或模型权限'),
        404:('not_found','模型或接口地址不存在，请检查协议、地址和模型名称'),
        429:('rate_limit_or_quota','服务限制了本次请求（HTTP 429），具体是限流还是额度问题尚不明确，请核对服务商状态和额度'),
    }.get(status,('service_error',f'上游服务返回 HTTP {status}，请检查服务状态后重试'))
    codes={code.lower(),kind.lower()}
    if codes & {'insufficient_balance','insufficient_quota','quota_exceeded','billing_hard_limit_reached'} or (kind.lower()=='billing_error' and message in ('insufficient balance','insufficient account balance')):
        category,text='quota','模型服务账户余额或额度不足，请在当前服务商处核对额度后重新运行'
        if code.lower()=='insufficient_balance' or kind.lower()=='billing_error':text='模型服务账户余额不足，请在当前服务商处充值后重试'
    elif codes & {'rate_limit_exceeded','rate_limit_error','too_many_requests','requests_limit_exceeded'}:
        category,text='rate_limit','模型服务请求限流，请等待限制解除后重新运行'
    headers={k.lower():v for k,v in (headers or {}).items()}
    details=dict(category=category,http_status=status,request_sent=True,response_received=True,provider_code=code,provider_type=kind,
        request_id=identifier(headers.get('x-request-id') or headers.get('request-id') or headers.get('x-amzn-requestid')))
    retry=headers.get('retry-after')
    if retry and category in ('rate_limit','rate_limit_or_quota','service_error'):
        try:
            try:seconds=float(retry)
            except ValueError:seconds=(parsedate_to_datetime(retry)-datetime.now(timezone.utc)).total_seconds()
            if math.isfinite(seconds) and 0<=seconds<=86400:
                seconds=math.ceil(seconds);details.update(retry_after_seconds=seconds,retry_at=(datetime.now(timezone.utc)+timedelta(seconds=seconds)).isoformat())
        except (ValueError,TypeError,OverflowError):pass
    return ServiceFailure(text,**details)


def connection_failure(exc):
    import httpx
    timeout=isinstance(exc,httpx.TimeoutException)
    return ServiceFailure('模型工具等待响应超时；本次费用可能未知，已保留任务，请核对服务状态后重新运行' if timeout else
        '模型服务连接中断；本次费用可能未知，已保留任务，请检查连接后重新运行',category='timeout' if timeout else 'connection',request_sent=True,response_received=False)


def service_identity(service):
    # No URL, headers, request payload or credentials are copied into the job.
    return {k:service.get(k,'') for k in ('id','name','model','protocol')}


def bind(error,service):
    error.details['service']=service_identity(service)
    secret=service.get('secret','')
    if secret:
        for key in ('provider_code','provider_type','request_id'):
            if secret in error.details.get(key,''):error.details[key]=''
    return error
