"""Article intent persists across stages; exploration never establishes a fact."""
import copy
from . import store


def intent(a):
    return copy.deepcopy(a.get('creative_intent') or dict(version=1,
        original_request=a['brief'].get('purpose') or a['brief'].get('topic',''),
        selected=dict(title=a['brief'].get('topic',''), angle='', evidence_status='待调查'),
        batches=[], feedback=[]))


def adopt(a, title, topic_id=''):
    candidate=next((t for t in a['topics'] if (t.get('id')==topic_id if topic_id else t['title']==title)),None)
    if topic_id and not candidate: raise ValueError('候选选题已更新，请重新选择')
    plan=copy.deepcopy(candidate or dict(title=title,angle='',evidence_status='待调查'))
    plan['id']=plan.get('id') or 'T'+store.uid()[:12]
    current=intent(a)
    if current.get('selected')!=plan and a.get('research'):
        # Past attempts remain in job snapshots; questions about discarded candidates do not bind the new article.
        a['research'].update(issues=[],gaps=[],conflicts=[],stale=True,pending=False)
        a['research'].pop('resume_job_id',None);a['research'].pop('resume_stage',None)
        for claim in a.get('evidence',{}).get('claims',[]): claim['stale']=True
        a['stages']['sources']='stale'
    current.update(selected=plan, adopted_at=store.now(), expanded=bool(plan.get('angle')))
    if not current['original_request']: current['original_request']=title
    current.pop('direction_change',None)
    a['creative_intent']=current
    a['title']=plan['title'];a['brief']['topic']=plan['title']
    a['stages']['topic']='done';a['current_stage']='sources'


def candidates(a, rows, feedback=''):
    current=intent(a)
    if not current.get('original_request'):
        current['original_request']=feedback or '围绕'+(a['brief'].get('domain') or a['brief']['column'])+'寻找选题'
    for row in rows:
        row['id']='T'+store.uid()[:12]
        row['evidence_status']='待调查；已有相关资料' if row.get('source_ids') else '待调查；尚需资料'
    current['batches']=(current.get('batches',[])+[dict(id=store.uid(),at=store.now(),feedback=feedback,topics=copy.deepcopy(rows))])[-3:]
    if feedback: current['feedback']=(current.get('feedback',[])+[feedback])[-12:]
    a['creative_intent']=current;a['topics']=rows


def context(a):
    value=intent(a)
    # History is useful for exploration; selected intent is authoritative downstream.
    return value
