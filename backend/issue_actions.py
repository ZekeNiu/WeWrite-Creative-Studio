"""Explicit resolution decisions, revision protection, and resumable tasks."""
from . import store,flow_state,workflow,evidence_state
from .models import JobRequest


def parent(a):
    r=a.get('research',{})
    jid=r.get('resume_job_id') or r.get('job_id')
    if not jid: return None
    try: j=store.job(jid)
    except KeyError: return None
    if j['article_id']!=a['id'] or j.get('stage') not in ('sources','outline','review','topic') or (j['status']!='needs_input' and not j.get('waiting_for_materials')): return None
    if a['stages'].get('outline' if j['stage']=='sources' else j['stage'])=='done': return None
    jobs=store.jobs(a['id'])
    if any(x['id']!=jid and x['created']>j['created'] and x.get('stage')==j['stage'] for x in jobs): return None
    return j


def apply(id,value):
    with store.LOCK:
        for j in store.jobs(id):
            if value.action in ('verify','bound_auto') and j['request'].get('action_id')==value.action_id:
                return dict(article=store.get_article(id),job=flow_state.job_view(j))
        a=store.get_article(id)
        if a['revision']!=value.revision: raise store.Conflict('资料已更新，请刷新核实问题后重试')
        if any(j['status'] in ('queued','running') for j in store.jobs(id)): raise store.Conflict('请等待当前任务完成或先停止')
        lookup={x['id']:x for x in flow_state.issues(a)}
        if set(value.issue_ids)-lookup.keys(): raise ValueError('核实问题已改变，请刷新后重试')
        if value.action in ('bound','waive') and not value.wording.strip():
            raise ValueError('请填写本篇保留的限定表述，或选择本篇不使用该主张')
        if value.action=='attach': return dict(article=a,job=None)
        if value.action=='bound_auto':
            from . import bounded
            return dict(article=a,job=bounded.start(a,value))
        original=parent(a)
        if value.action=='verify':
            instruction='只核实以下问题；可解释的局限保留边界，不追求不存在的研究：\n'+'\n'.join(lookup[i]['text'] for i in value.issue_ids)
            request=JobRequest(stage='research',revision=a['revision'],instruction=instruction,issue_ids=value.issue_ids,
                action_id=value.action_id,chain=False,continuation_job_id=original['id'] if original else '')
            return dict(article=a,job=workflow.start(id,request))
        def change(v):
            decisions=v.setdefault('research_decisions',{})
            if value.action=='undo':
                from .bounded import undo
                undo(v,value.issue_ids)
            for iid in value.issue_ids:
                if value.action in ('waive','bound','exclude'):
                    decisions[iid]=dict(dependency_key=evidence_state.dependency(v,lookup[iid]),at=store.now(),handling='excluded' if value.action=='exclude' else 'bounded',wording=value.wording.strip(),text=lookup[iid]['text'])
            v['research']['issues']=flow_state.issues(v)
            v['research']['pending']=any(x['kind']=='blocking' and x['status'] in ('open','stale') for x in v['research']['issues'])
            if original:
                v['research']['resume_job_id']=original['id'];v['research']['resume_stage']=original['stage']
        a=store.save_article(id,value.revision,change,'处理核实建议：'+value.action,invalidate='write' if value.action=='undo' and a.get('content') else None)
        job=None
        if value.action in ('waive','bound','exclude') and original and not a['research']['pending'] and a['auto'].get(original['stage']):
            job=workflow.start(id,JobRequest(stage=original['stage'],revision=a['revision'],resume_job_id=original['id'],chain=original['request'].get('chain',True)))
        return dict(article=a,job=job)
