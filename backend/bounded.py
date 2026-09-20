"""Apply a requested bounded wording with exact anchors and reversible local edits."""
import asyncio
import copy
from typing import Literal
from pydantic import BaseModel,Field
from . import store,workflow,research,flow_state,evidence_state


class Edit(BaseModel):
    target: Literal['content','thesis','reader_question','takeaway','counterpoint','boundary','section_title','section_purpose','section_point']
    section_id: str = ''
    point_index: int = Field(0,ge=0)
    original: str = Field(min_length=1,max_length=6000)
    replacement: str = Field(min_length=1,max_length=6000)


class Decision(BaseModel):
    issue_id: str
    wording: str = Field(min_length=1,max_length=3000)
    explanation: str
    edits: list[Edit] = Field(default_factory=list,max_length=15)


class Result(BaseModel):
    decisions: list[Decision] = Field(min_length=1,max_length=10)


def replace(a,edit,undo=False):
    old,new=(edit['replacement'],edit['original']) if undo else (edit['original'],edit['replacement'])
    target=edit['target'];container=a if target=='content' else a['outline'];key=target
    if target.startswith('section_'):
        container=next((s for s in a['outline'].get('sections',[]) if s['id']==edit['section_id']),None)
        if container is None:return False
        key=target.removeprefix('section_')
        if key=='point':
            # Point positions can move. Match the original text within the stable section.
            points=container.get('points',[]);matches=[i for i,p in enumerate(points) if old and p.count(old)==1]
            if len(matches)!=1:return False
            points[matches[0]]=points[matches[0]].replace(old,new,1);return True
    text=container.get(key,'')
    if not old or not isinstance(text,str) or text.count(old)!=1:return False
    container[key]=text.replace(old,new,1);return True


def start(a,value):
    request=dict(stage='bound',revision=a['revision'],issue_ids=value.issue_ids,action_id=value.action_id,chain=False)
    job=store.create_job(a['id'],request)
    workflow.TASKS[job['id']]=asyncio.create_task(run(job['id'],copy.deepcopy(a),value.issue_ids))
    return job


async def run(jid,snapshot,ids):
    try:
        store.update_job(jid,status='running',message='正在依据已有材料生成限定表述')
        lookup={x['id']:x for x in flow_state.issues(snapshot)}
        result=await research.structured(snapshot,'review',
            '用户明确请求直接采用限定表述。只处理这些建议：'+store.encode([lookup[i] for i in ids])+'. '
            '依据已提供的来源，不联网、不补造证据。每项给出真正可用的 wording 和 explanation，附相关正文/大纲局部 edits。'
            'original 必须逐字复制现有字段中唯一的连续片段，replacement 为限定后的替换。保持文内来源编号及文章目标。'
            'section 使用稳定 section_id。避免改写无关段落，不返回整篇文章。定位不到不要编造 original，edits 留空并解释。'
            '没有证据的比例不能改成模糊概数，无直接因果证据用观察关联/待验证机制，不宣称已核实。',Result,jid)
        if set(d['issue_id'] for d in result['decisions'])!=set(ids) or len(result['decisions'])!=len(ids):raise ValueError('限定结果未对应所选建议，未应用')
        if store.job(jid)['status']=='cancelled':return
        with store.LOCK:
            current=store.get_article(snapshot['id'])
            if evidence_state.objective(current)!=evidence_state.objective(snapshot):raise store.Conflict('文章方向已改变，限定结果未应用')
            for iid in ids:
                if evidence_state.dependency(current,lookup[iid])!=evidence_state.dependency(snapshot,lookup[iid]):raise store.Conflict('相关依据已变化，限定结果未应用')
                if current.get('research_decisions',{}).get(iid)!=snapshot.get('research_decisions',{}).get(iid):raise store.Conflict('该建议已由你处理，未覆盖当前决定')
            applications=[]
            def change(a):
                decisions=a.setdefault('research_decisions',{})
                for item in result['decisions']:
                    iid=item['issue_id'];applied=[];unapplied=[]
                    for edit in item['edits']:
                        # Validate against both start snapshot and current content.
                        if replace(copy.deepcopy(snapshot),edit) and replace(a,edit):applied.append(edit)
                        else:unapplied.append(edit)
                    application=dict(job_id=jid,edits=applied,unapplied=unapplied,explanation=item['explanation'],previous=copy.deepcopy(decisions.get(iid)))
                    decisions[iid]=dict(dependency_key=evidence_state.dependency(a,lookup[iid]),at=store.now(),handling='bounded',wording=item['wording'],text=lookup[iid]['text'],application=application)
                    applications.append(dict(issue_id=iid,wording=item['wording'],**application))
                a['research']['issues']=flow_state.issues(a)
            saved=store.save_article(current['id'],current['revision'],change,'AI 应用限定表述',invalidate='write' if current.get('content') else 'outline')
            store.update_job(jid,status='completed',ended=store.now(),message='限定表述已保存，可查看改动或撤销',result=dict(applications=applications,revision=saved['revision']))
    except asyncio.CancelledError:store.update_job(jid,status='cancelled',ended=store.now(),message='已停止，未应用限定表述')
    except Exception as exc:store.update_job(jid,status='conflict' if isinstance(exc,store.Conflict) else 'failed',ended=store.now(),message=str(exc) if isinstance(exc,(ValueError,store.Conflict)) else '限定生成未完成，已有内容保留；请求可能已计费，不自动重试')
    finally:workflow.TASKS.pop(jid,None)


def undo(a,ids):
    for iid in reversed(ids):
        decision=a.get('research_decisions',{}).get(iid,{})
        application=decision.get('application',{})
        for edit in reversed(application.get('edits',[])):
            if not replace(a,edit,undo=True):raise store.Conflict('限定后的相关内容已被修改，未自动撤销；可在历史版本中查看原文')
        if application.get('previous'):a['research_decisions'][iid]=application['previous']
        else:
            a.get('research_decisions',{}).pop(iid,None)
            for issue in a.get('research',{}).get('issues',[]):
                if issue['id']==iid:
                    issue['status']='open' if decision.get('dependency_key')==evidence_state.dependency(a,issue) else 'stale'
                    issue.pop('application',None);issue.pop('wording',None)
