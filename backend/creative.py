"""Article intent persists across stages; exploration never establishes a fact."""
import copy
import unicodedata
from . import store


def intent(a):
    return copy.deepcopy(a.get('creative_intent') or dict(version=1,
        original_request=a['brief'].get('purpose') or a['brief'].get('topic',''),
        selected=dict(title=a['brief'].get('topic',''), angle='', evidence_status='待调查'),
        batches=[], feedback=[]))


def batches(a):
    history=(a.get('creative_intent') or {}).get('batches',[])
    if history:return history
    if a.get('topics'):
        return [dict(id='legacy-'+a['id'],at='',feedback='',topics=a['topics'])]
    return []


def validate_candidates(a, rows):
    def title_key(title):
        return ''.join(c for c in unicodedata.normalize('NFKC',title).casefold()
                       if not c.isspace() and not unicodedata.category(c).startswith('P'))
    previous={title_key(t['title']) for batch in batches(a)[-3:] for t in batch['topics']}
    if rows and previous and all(title_key(t['title']) in previous for t in rows):
        raise ValueError('本批标题与最近三批全部重复。请根据本次反馈生成新的选题，不能只改编号、顺序或说明；重写 topics.yaml 后再次调用 Finish。')


def adopt(a, title, topic_id=''):
    candidate=next((t for t in a['topics'] if (t.get('id')==topic_id if topic_id else t['title']==title)),None)
    if topic_id and not candidate:
        candidate=next((t for batch in batches(a) for t in batch['topics'] if t.get('id')==topic_id),None)
    if topic_id and not candidate: raise ValueError('此选题不在当前文章的已保存批次中，请刷新后重新选择')
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
    current['adopted_plan']=copy.deepcopy(plan)
    if not current['original_request']: current['original_request']=title
    current.pop('direction_change',None)
    a['creative_intent']=current
    a['title']=plan['title'];a['brief']['topic']=plan['title']
    a.setdefault('input_drafts',{})['topic']=plan['title']
    a['stages']['topic']='done';a['current_stage']='sources'


def candidates(a, rows, feedback=''):
    current=intent(a)
    history=current.get('batches') or copy.deepcopy(batches(a))
    if not current.get('original_request'):
        current['original_request']=feedback or '围绕'+(a['brief'].get('domain') or a['brief']['column'])+'寻找选题'
    for row in rows:
        row['id']='T'+store.uid()[:12]
        row['evidence_status']='待调查；已有相关资料' if row.get('source_ids') else '待调查；尚需资料'
    current['batches']=history+[dict(id=store.uid(),at=store.now(),feedback=feedback,topics=copy.deepcopy(rows))]
    if feedback: current['feedback']=(current.get('feedback',[])+[feedback])[-12:]
    a['creative_intent']=current;a['topics']=rows


def context(a):
    value=a.get('creative_intent') or intent(a)
    # Full history belongs to the UI; model context only needs recent exploration.
    return copy.deepcopy({**value,'batches':batches(a)[-3:]})
