"""Shared, read-only workflow readiness and legacy presentation."""
import hashlib
import json
from .models import STAGES, LABELS


def material_sources(a):
    return [{k:s.get(k) for k in ('id','selected','text','title','use','personal_material','bibliography')} for s in a['sources']]


def signature(a):
    sources=material_sources(a)
    return hashlib.sha256(json.dumps([a['brief'],a['title'],sources],sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def issue_id(text,source_ids=()):
    return hashlib.sha256(json.dumps([' '.join(text.split()),sorted(source_ids)],ensure_ascii=False).encode()).hexdigest()[:20]


def issues(a):
    r=a.get('research',{})
    rows=r.get('issues')
    if rows is None:
        rows=[dict(id=issue_id(text),text=text,kind=kind,source_ids=[],claim='',status='open')
              for kind,key in [('blocking','gaps'),('limitation','conflicts')] for text in r.get(key,[])]
    decisions=a.get('research_decisions',{})
    key=signature(a)
    return [dict(x,status='waived' if decisions.get(x['id'],{}).get('material_key')==key else
                 ('open' if x.get('status')=='waived' or (r.get('stale') and x.get('status')=='resolved') else x.get('status','open'))) for x in rows]


def ready(a):
    result={s:dict(allowed=True,reason='',target=s) for s in STAGES}
    def block(stage,reason,target): result[stage]=dict(allowed=False,reason=reason,target=target)
    r=a.get('research',{})
    blockers=[x for x in issues(a) if x['kind']=='blocking' and x['status']=='open']
    material_ok=(a['stages']['sources']=='done' and bool(a['evidence']) and not r.get('stale')) or (bool(r) and not r.get('stale') and not blockers)
    if not material_ok: block('outline','请先整理素材并处理待核实问题，再生成大纲','sources')
    if not a['outline'].get('sections'): block('write','尚未生成大纲，请先完成大纲','outline')
    elif a['stages']['outline']!='done': block('write','请先确认当前大纲；已有大纲需要更新时，可编辑后点击确认','outline')
    if a['stages']['sources']=='stale' and a['evidence']:
        block('outline','采用的素材已变化，请先重新分析素材，避免沿用过期证据','sources')
        block('write','采用的素材已变化，请先重新分析素材，避免沿用过期证据','sources')
    if blockers and not r.get('stale'):
        block('outline','资料核对暂停，请先处理待核实问题','sources')
        block('write','资料核对暂停，请先处理待核实问题','sources')
    if not a['brief']['topic']:
        for s in ('sources','outline','write'): block(s,'请先在选题环节选择或采用一个主题','topic')
    if not a['content'].strip():
        for s in ('review','visual','layout'): block(s,'请先写作或导入正文','write')
    if not a['visual']['enabled']: block('visual','配图为可选环节，请先启用 AI 配图或上传图片','visual')
    return result


def present(a):
    from .review_state import present as review_present
    review_present(a)
    a['visual'].pop('budget',None)
    a['workflow']=ready(a)
    if a.get('research'): a['research']['issues']=issues(a)
    return a


def job_view(j):
    if j.get('stage')=='review' and j.get('status')=='needs_input' and j.get('current_step')=='generation':
        from . import store
        a=store.get_article(j['article_id']);review=a.get('review') or {}
        same_round=(review.get('job_id')==j['id'] and review.get('round_id')==j.get('review_round_id'))
        legacy_round=(not review.get('round_id') and review.get('content_revision')==j.get('generation_revision'))
        if (same_round or legacy_round) and review.get('completion')=='human' and a['stages']['review']=='done':
            j=dict(j,status='completed',message='本轮意见已处理',review_completion='human')
    # Older releases incorrectly labelled paused research as completed.
    r=j.get('research',{})
    notes=r.get('notes',{})
    if not r.get('stats') and j['status']=='completed' and j.get('result') is None and (notes.get('gaps') or notes.get('conflicts')):
        j=dict(j,status='needs_input',legacy_pause=True,
               message='资料核对暂停，尚未完成'+LABELS.get(j.get('stage'),'当前环节'))
    return j
