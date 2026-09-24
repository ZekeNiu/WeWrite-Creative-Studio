"""Shared, read-only workflow readiness and legacy presentation."""
import hashlib
import json
from .models import STAGES, LABELS


def material_sources(a):
    return [{k:s.get(k) for k in ('id','selected','text','title','use','personal_material','bibliography')} for s in a['sources']]


def signature(a):
    from .evidence_state import objective,selected,digest
    return digest([objective(a),selected(a)])


def legacy_signature(a):
    return hashlib.sha256(json.dumps([a['brief'],a['title'],material_sources(a)],sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def issue_id(text,source_ids=()):
    return hashlib.sha256(json.dumps([' '.join(text.split()),sorted(source_ids)],ensure_ascii=False).encode()).hexdigest()[:20]


def issues(a):
    r=a.get('research',{})
    rows=r.get('issues')
    if rows is None:
        rows=[dict(id=issue_id(text),text=text,kind=kind,source_ids=[],claim='',status='open')
              for kind,key in [('blocking','gaps'),('limitation','conflicts')] for text in r.get(key,[])]
    from .evidence_state import dependency
    decisions=a.get('research_decisions',{})
    result=[]
    for raw in rows:
        x=dict(raw);d=decisions.get(x['id'],{})
        x['priority']=x.get('priority') or ('high' if x.get('kind')=='blocking' else 'normal')
        if x['text'] in ('未取得可用于当前主题的资料；可补充材料或检查检索渠道后重试。','尚未取得可定位的原文证据，请补充材料或继续检索。'): x['system_kind']='no_evidence'
        valid=(d.get('dependency_key')==dependency(a,x) if d.get('dependency_key') else d.get('material_key') in (signature(a),legacy_signature(a)))
        if valid:
            x.update(status=d.get('handling','bounded'),wording=d.get('wording',''))
            if d.get('application'):x['application']=d['application']
            x['application_state']=d.get('application_state') or ('applied' if d.get('application',{}).get('edits') and not d.get('application',{}).get('unapplied') else 'pending' if a.get('content') or a.get('outline') else 'not_needed')
        elif x.get('status') in ('waived','bounded','excluded'):
            x['status']='stale'
        result.append(x)
    return result


def ready(a):
    result={s:dict(allowed=True,reason='',target=s) for s in STAGES}
    def block(stage,reason,target): result[stage]=dict(allowed=False,reason=reason,target=target)
    if not a['outline'].get('sections'): block('write','尚未生成大纲，请先完成大纲','outline')
    elif a['stages']['outline']!='done': block('write','请先确认当前大纲；已有大纲需要更新时，可编辑后点击确认','outline')
    # Advice does not block creation. The generation context retains evidence limits.
    if not a['brief']['topic']:
        for s in ('sources','outline','write'): block(s,'请先在选题环节选择或采用一个主题','topic')
    if not a['content'].strip():
        for s in ('review','visual','layout'): block(s,'请先写作或导入正文','write')
    if not a['visual']['enabled']: block('visual','配图为可选环节，请先启用 AI 配图或上传图片','visual')
    return result


def present(a):
    from .evidence_state import sync
    sync(a)
    from .review_state import present as review_present
    review_present(a)
    a['visual'].pop('budget',None)
    from .evidence_state import material_view
    a['materials_state']=material_view(a)
    a['workflow']=ready(a)
    if a.get('research'):
        a['research']['issues']=issues(a)
        from .issue_actions import parent
        active=parent(a)
        if active: a['research'].update(resume_job_id=active['id'],resume_stage=active['stage'])
        else:
            a['research'].pop('resume_job_id',None);a['research'].pop('resume_stage',None)
    return a


def job_view(j):
    j=dict(j)
    if j.get('stage') in (*STAGES,'research','revise','image','layout_advice','edit'):
        j['retry_request']=retry_request(j,0)
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


def retry_request(job,revision):
    original=job.get('request') or {};stage=job['stage']
    request=dict(stage=stage,revision=revision,chain=original.get('chain',False))
    if stage=='image' and job.get('image_id'):request.update(image_id=job['image_id'],chain=False)
    if original.get('stage')==stage:
        fields={'topic':('instruction',),'sources':('instruction',),'research':('instruction','research_parent_id','issue_ids'),
                'outline':('instruction','section_id'),'write':('instruction',),'review':('instruction',),
                'revise':('instruction','selected_text'),'image':('image_id',),'visual':('instruction',),
                'edit':('instruction',),'layout_advice':('instruction',)}.get(stage,())
        request.update({k:original[k] for k in fields if original.get(k) is not None})
    return request
