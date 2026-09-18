"""Explicit resolution decisions, revision protection, and resumable tasks."""
from . import store,flow_state,workflow
from .models import JobRequest


def parent(a):
    r=a.get('research',{})
    jid=r.get('resume_job_id') or r.get('job_id')
    if not jid: return None
    j=store.job(jid)
    if j['article_id']!=a['id'] or j.get('stage') not in ('outline','review','topic'): return None
    return j


def apply(id,value):
    with store.LOCK:
        for j in store.jobs(id):
            if value.action=='verify' and j['request'].get('action_id')==value.action_id:
                return dict(article=store.get_article(id),job=flow_state.job_view(j))
        a=store.get_article(id)
        if a['revision']!=value.revision: raise store.Conflict('资料已更新，请刷新核实问题后重试')
        if any(j['status'] in ('queued','running') for j in store.jobs(id)): raise store.Conflict('请等待当前任务完成或先停止')
        lookup={x['id']:x for x in flow_state.issues(a)}
        if set(value.issue_ids)-lookup.keys(): raise ValueError('核实问题已改变，请刷新后重试')
        if a.get('research',{}).get('stale') and value.action in ('waive','undo'):
            raise ValueError('材料已改变，请先重新核实，再决定是否忽略')
        original=parent(a)
        if value.action=='verify':
            instruction='只核实以下问题；可解释的局限保留边界，不追求不存在的研究：\n'+'\n'.join(lookup[i]['text'] for i in value.issue_ids)
            request=JobRequest(stage='research',revision=a['revision'],instruction=instruction,issue_ids=value.issue_ids,
                action_id=value.action_id,chain=False,continuation_job_id=original['id'] if original else '')
            return dict(article=a,job=workflow.start(id,request))
        def change(v):
            decisions=v.setdefault('research_decisions',{})
            for iid in value.issue_ids:
                if value.action=='waive': decisions[iid]=dict(material_key=flow_state.signature(v),at=store.now(),handling='bounded',text=lookup[iid]['text'])
                elif value.action=='undo': decisions.pop(iid,None)
            if value.action=='attach':
                v['pending_issue_attachments']=value.issue_ids
                return
            v['research']['issues']=flow_state.issues(v)
            v['research']['pending']=any(x['kind']=='blocking' and x['status']=='open' for x in v['research']['issues'])
            if original:
                v['research']['resume_job_id']=original['id'];v['research']['resume_stage']=original['stage']
        a=store.save_article(id,value.revision,change,'处理核实问题：'+value.action)
        job=None
        if value.action=='waive' and original and not a['research']['pending'] and a['auto'].get(original['stage']):
            job=workflow.start(id,JobRequest(stage=original['stage'],revision=a['revision'],resume_job_id=original['id'],chain=original['request'].get('chain',True)))
        return dict(article=a,job=job)
