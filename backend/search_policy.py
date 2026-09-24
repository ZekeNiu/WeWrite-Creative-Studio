"""Shared search fallback policy; never replay a failed paid request."""
from .service_errors import ServiceFailure

BROWSERS=('google','bing','baidu','duckduckgo')


def web_order(cfg):
    return ['native','tavily','browser'] if cfg.get('allow_fallback',True) else ['native']


def free_fallback(error,cfg):
    if not cfg.get('allow_fallback',True) or not isinstance(error,ServiceFailure):return False
    details=error.details;category=details.get('category');status=details.get('http_status')
    return category in ('timeout','connection','rate_limit','search_unavailable','output_truncated') or (
        category=='service_error' and isinstance(status,int) and 500<=status<600)


def record_fallback(job_id,error):
    from . import store
    message='联网服务暂未完成，正在尝试免费后备搜索；本任务不重发失败请求，不追加其他付费搜索。已有未知费用仍保留，后续分析继续记录用量。'
    store.update_job(job_id,free_search_only=True)
    store.event(job_id,'search_fallback',message=message,category=error.details.get('category'),service=error.details.get('service'))
    diagnostic=store.job(job_id).get('search_diagnostic')
    if diagnostic:
        diagnostic=dict(diagnostic,warnings=list(dict.fromkeys([*diagnostic.get('warnings',[]),message])))
        store.update_job(job_id,search_diagnostic=diagnostic)
    return message
