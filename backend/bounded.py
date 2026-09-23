"""Explicit local wording/exclusion edits with exact anchors and reversible receipts."""
import asyncio
import copy
from typing import Literal
from pydantic import BaseModel, Field
from . import store, workflow, research, flow_state, evidence_state
from .models import ApplicationState


class Edit(BaseModel):
    target: Literal['content','thesis','reader_question','takeaway','counterpoint','boundary','section_title','section_purpose','section_point']
    section_id: str = ''
    point_index: int = Field(0, ge=0)
    original: str = Field(min_length=1, max_length=6000)
    replacement: str = Field(max_length=6000)


class Decision(BaseModel):
    issue_id: str
    wording: str = Field(min_length=1, max_length=3000)
    explanation: str
    edits: list[Edit] = Field(default_factory=list, max_length=15)


class Result(BaseModel):
    decisions: list[Decision] = Field(min_length=1, max_length=10)


def field(a, edit, undo=False):
    target=edit['target']
    if target=='content':return a,'content'
    container=a['outline'];key=target
    if target.startswith('section_'):
        container=next((s for s in container.get('sections',[]) if s['id']==edit['section_id']),None)
        if container is None:return None,None
        key=target.removeprefix('section_')
        if key=='point':
            points=container.get('points',[]);original=edit['replacement'] if undo else edit['original']
            matches=[i for i,text in enumerate(points) if (original and text.count(original)==1) or (not original and text=='')]
            if len(matches)!=1:return None,None
            return points,matches[0]
    return container,key


def replace(a, edit, undo=False):
    container,key=field(a,edit,undo)
    if container is None:return False
    text=container[key] if isinstance(container,list) else container.get(key,'')
    if not isinstance(text,str):return False
    old,new=(edit['replacement'],edit['original']) if undo else (edit['original'],edit['replacement'])
    if old and text.count(old)==1:at=text.index(old)
    elif undo and 'anchor' in edit:
        left,right=edit['anchor']['left'],edit['anchor']['right'];needle=left+old+right
        if not needle:
            if text:return False
            at=0
        elif text.count(needle)==1:at=text.index(needle)+len(left)
        else:return False
    else:return False
    if not undo:edit['anchor']=dict(left=text[max(0,at-64):at],right=text[at+len(old):at+len(old)+64])
    container[key]=text[:at]+new+text[at+len(old):]
    return True


def start(a, value):
    mode='exclude' if value.action=='exclude' else 'bound'
    request=dict(stage='bound',operation=mode,revision=a['revision'],issue_ids=value.issue_ids,action_id=value.action_id,chain=False)
    job=store.create_job(a['id'],request)
    workflow.TASKS[job['id']]=asyncio.create_task(run(job['id'],copy.deepcopy(a),value.issue_ids,mode))
    return job


async def run(jid, snapshot, ids, mode='bound'):
    from .execution_budget import ACTIVE
    budget_token=ACTIVE.set(jid)
    applications=[]
    try:
        verb='移除不使用的主张' if mode=='exclude' else '采用限定表述'
        store.update_job(jid,status='running',message='正在依据已有材料'+verb)
        for offset in range(0,len(ids),10):
            group=ids[offset:offset+10];lookup={x['id']:x for x in flow_state.issues(snapshot)}
            instruction=('用户明确请求本篇不使用这些主张。删除相关断言，必要时仅调整衔接，不把同一主张换一种说法保留。replacement 允许为空。' if mode=='exclude' else
                         '用户明确请求采用限定表述。只依据已有证据改为准确的适用范围；不把缺据数字改成概数，不把观察关联改成因果。')
            result=await research.structured(snapshot,'review',instruction+
                '只处理这些建议：'+store.encode([lookup[i] for i in group])+'. '
                '不联网、不补造证据，不改变文章目标，不重写全文。每项给出后续约束 wording、explanation 和相关正文/大纲 edits。'
                'original 必须逐字复制现有字段中唯一的连续片段；section 使用稳定 section_id。'
                '修改所有能定位的相关位置，保持无关段落与其来源编号。定位不到则 edits 留空并解释。',Result,jid)
            if set(d['issue_id'] for d in result['decisions'])!=set(group) or len(result['decisions'])!=len(group):raise ValueError('修改结果未对应所选建议，本组未应用')
            if store.job(jid)['status']=='cancelled':return
            with store.LOCK:
                current=store.get_article(snapshot['id'])
                if evidence_state.objective(current)!=evidence_state.objective(snapshot):raise store.Conflict('文章方向已改变，本组修改未应用')
                for iid in group:
                    if evidence_state.dependency(current,lookup[iid])!=evidence_state.dependency(snapshot,lookup[iid]):raise store.Conflict('相关依据已变化，本组修改未应用')
                    if current.get('research_decisions',{}).get(iid)!=snapshot.get('research_decisions',{}).get(iid):raise store.Conflict('建议已有新的处理决定，本组未覆盖')
                group_applications=[]
                def change(a):
                    decisions=a.setdefault('research_decisions',{});consumed=copy.deepcopy(snapshot)
                    for item in result['decisions']:
                        iid=item['issue_id'];applied=[];unapplied=[]
                        for raw in item['edits']:
                            edit=copy.deepcopy(raw)
                            if not replace(consumed,copy.deepcopy(edit)):
                                unapplied.append(dict(edit,reason='任务开始时无法唯一定位，或与其他修改重叠'))
                            elif not replace(a,edit):
                                unapplied.append(dict(edit,reason='当前文字已改变或出现重复，未覆盖人工编辑'))
                            else:applied.append(edit)
                        state: ApplicationState='partial' if applied and unapplied else 'applied' if applied else 'pending' if snapshot.get('content') or snapshot.get('outline') else 'not_needed'
                        application=dict(job_id=jid,operation=mode,edits=applied,unapplied=unapplied,explanation=item['explanation'],previous=copy.deepcopy(decisions.get(iid)))
                        decisions[iid]=dict(dependency_key=evidence_state.dependency(a,lookup[iid]),at=store.now(),handling='excluded' if mode=='exclude' else 'bounded',wording=item['wording'],text=lookup[iid]['text'],application_state=state,application=application)
                        group_applications.append(dict(issue_id=iid,wording=item['wording'],application_state=state,**application))
                saved=store.save_article(current['id'],current['revision'],change,'AI '+verb,invalidate='write' if current.get('content') else 'outline')
                applications.extend(group_applications);snapshot=copy.deepcopy(saved)
                receipt=dict(applications=applications,revision=saved['revision'],changed=sum(len(x['edits']) for x in applications),remaining=len(ids)-len(applications)+sum(x['application_state'] in ('pending','partial') for x in applications))
                store.update_job(jid,result=receipt,message=f"已处理 {len(applications)}/{len(ids)} 项建议，修改 {receipt['changed']} 处")
        store.update_job(jid,status='completed',ended=store.now(),message=f"处理决定已保存，正文/大纲修改 {receipt['changed']} 处；{receipt['remaining']} 项仍需核对，可查看改动或撤销")
    except asyncio.CancelledError:
        store.update_job(jid,status='cancelled',ended=store.now(),message=f'已停止；此前已完成 {len(applications)} 项，未完成部分未应用')
    except Exception as exc:
        message=str(exc) if isinstance(exc,(ValueError,store.Conflict)) else '生成未完成，请求可能已计费，不自动重试'
        store.update_job(jid,status='conflict' if isinstance(exc,store.Conflict) else 'failed',ended=store.now(),message=message+f'；此前已完成 {len(applications)} 项，改动可查看或撤销')
    finally:
        ACTIVE.reset(budget_token)
        workflow.TASKS.pop(jid,None)


def undo(a, ids):
    decisions=a.get('research_decisions',{})
    for iid in sorted(ids,key=lambda iid:decisions.get(iid,{}).get('at',''),reverse=True):
        decision=decisions.get(iid,{});application=decision.get('application',{})
        for edit in reversed(application.get('edits',[])):
            if not replace(a,edit,undo=True):raise store.Conflict('相关内容已被修改，未自动撤销；可在历史版本中查看原文')
        if application.get('previous'):decisions[iid]=application['previous']
        else:
            decisions.pop(iid,None)
            for issue in a.get('research',{}).get('issues',[]):
                if issue['id']==iid:
                    issue['status']='open' if decision.get('dependency_key')==evidence_state.dependency(a,issue) else 'stale'
                    for key in ('application','wording','application_state'):issue.pop(key,None)
