"""Persistent end-to-end search checks, using the same pipeline as writing."""
import asyncio
from pydantic import BaseModel, Field
from . import store, providers, security, workflow, research
from .models import ResearchNotes


class CheckRequest(BaseModel):
    column: str = Field('运动科学', max_length=100)
    topic: str = Field('', max_length=500)
    without_tavily: bool = False


QUERIES = {
    '运动科学': 'resistance training muscle hypertrophy systematic review',
    '运动健康': 'WHO physical activity sedentary behaviour guidelines adults',
    'AI': 'retrieval augmented generation language models research',
}


def fingerprint():
    cfg = providers.settings()
    services = []
    for kind in ('research', 'search'):
        try:
            s = providers.service_for(kind) if kind == 'research' else providers.effective_service(kind)
            services.append(providers.fingerprint(s, kind))
        except ValueError:
            services.append('unconfigured')
    search = {k: v for k, v in cfg['search'].items() if k not in ('key', 'key_set')}
    return research.digest([search, services, security.key('tavily'),security.key('openalex')])


def result(job):
    if not job:
        return None
    check = dict(job.get('check', {}))
    telemetry = job.get('research', {}).get('telemetry', {})
    active = job['status'] in ('queued', 'running')
    if 'steps' not in check:
        check['steps'] = {
            'retrieval': 'passed' if telemetry.get('relevant') else ('running' if active else 'unverified'),
            'reading': 'passed' if telemetry.get('fulltext') else ('partial' if telemetry.get('abstracts') else 'unverified'),
            'organizing': 'running' if telemetry.get('phase') == 'organizing' and active else 'unverified',
        }
    return dict(check, id=job['id'], status=job['status'], message=job.get('message', ''),
                created=job['created'], ended=job.get('ended'), request=job['request'],
                stale=job.get('config_fingerprint') != fingerprint(),
                research=job.get('research', {}), usage=store.usage(job['article_id']))


def start(request):
    existing = store.latest_search_check(active=True)
    if existing:
        return result(existing)
    query = request.topic.strip() or QUERIES.get(request.column, request.column)
    a = store.create_article({'column': request.column, 'topic': query}, diagnostic=True)
    job = store.create_job(a['id'], dict(request.model_dump(), kind='search_check', stage='research', revision=0, chain=False))
    store.update_job(job['id'], config_fingerprint=fingerprint())
    workflow.TASKS[job['id']] = asyncio.create_task(run(job['id']))
    return result(store.job(job['id']))


async def run(job_id):
    from .execution_budget import ACTIVE
    budget_token=ACTIVE.set(job_id)
    job = store.job(job_id)
    a = store.get_article(job['article_id'])
    w = research.Research(a, job_id, 'sources')
    if job['request'].get('without_tavily'):
        w.cfg['tavily_enabled'] = False
    store.update_job(job_id, status='running')
    notes = {}
    error = ''
    try:
        await w.discover([a['brief']['topic']])
        if not w.added:
            raise ValueError('未找到与问题相关且可读取的来源。请查看渠道记录；可更换问题或补充原文后重试。')
        w.telemetry['phase'] = 'organizing'
        w.update('正在让 AI 整理已读取的原文，并逐字核对引用')
        notes = research.validate_spans(await research.structured(a, 'sources',
            '回答主题中的一个具体问题。summary 不超过150个中文字，evidence 只需1至3条；每条逐字复制来源中一段连续原文（20–180 字符），'
            '不可翻译或添加省略号。claim 必须直接由所引片段支持，注明适用边界。优先引用已读取全文的来源。'
            '至少提供一条证据；资料不足须如实给出 gaps，不要凑数。', ResearchNotes, job_id), a['sources'])
        w.notes = notes
    except asyncio.CancelledError:
        w.update('测试已停止，已取得的资料保留；可重新测试')
        store.update_job(job_id, status='cancelled', ended=store.now())
        return
    except Exception as exc:
        error = str(exc) if isinstance(exc, ValueError) else '连接或处理失败，请查看渠道记录后重试'
        phase={'retrieval':'检索','selection':'AI 筛选','reading':'原文读取','organizing':'AI 整理'}.get(w.telemetry['phase'],'资料处理')
        error=phase+'未完成：'+error
    finally:
        ACTIVE.reset(budget_token)
        workflow.TASKS.pop(job_id, None)
    evidence = []
    for e in notes.get('evidence', []):
        src = next(s for s in a['sources'] if s['id'] == e['source_id'])
        evidence.append(dict(e, title=src['title'], url=src['url']))
    steps = {
        'retrieval': 'passed' if w.telemetry['relevant'] else 'failed',
        'reading': 'passed' if w.telemetry['fulltext'] else ('partial' if w.telemetry['abstracts'] else 'failed'),
        'organizing': ('passed' if any(e['source_status']=='retrieved' for e in evidence) else 'partial') if notes.get('summary') and evidence else 'failed',
    }
    passed = all(s == 'passed' for s in steps.values()) and any(e['source_status'] == 'retrieved' for e in evidence) and not w.policy_issue
    if w.policy_issue: error=w.policy_issue
    if not passed and not error:
        error = '仅取得摘要或搜索片段，尚未完成原文验证。' if steps['reading'] != 'passed' else 'AI 整理未取得可逐字定位的原文证据，请查看资料或更换整理模型。'
    w.update('工作台搜索测试通过' if passed else '测试未完全通过：' + error)
    store.update_job(job_id, status='completed' if passed else 'failed', ended=store.now(),
                     check=dict(passed=passed, steps=steps, summary=notes.get('summary', ''), evidence=evidence,
                                gaps=notes.get('gaps', []), conflicts=notes.get('conflicts', []), error=error))
