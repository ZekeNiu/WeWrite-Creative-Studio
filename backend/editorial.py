"""Argument synthesis, independent factual audit and reviewable whole-draft edits."""
import copy
import difflib
import hashlib
import json
import re
import time
from pydantic import BaseModel,Field,field_validator
from typing import Literal
from . import store,providers,source_context,research_contract,review_state
from .models import EvidenceJudgement
from .structured_output import parse

VERSION=2
DIMENSIONS=('accuracy','viewpoint','usefulness','voice','readability')


class Argument(BaseModel):
    id:str
    judgement:str
    evidence_ids:list[str]=Field(default_factory=list,max_length=20)
    source_ids:list[str]=Field(default_factory=list,max_length=20)
    reasoning:str
    boundary:str=''


class ArgumentSynthesis(BaseModel):
    thesis:str
    chain:list[Argument]=Field(default_factory=list,max_length=12)
    strongest_counterargument:str
    conflicts:list[str]=Field(default_factory=list,max_length=12)
    boundaries:list[str]=Field(default_factory=list,max_length=12)
    reader_value:str
    unresolved:list[str]=Field(default_factory=list,max_length=16)


class FactFinding(BaseModel):
    quote:str
    status:Literal['supported','limited','unsupported','contradicted']
    reason:str
    source_id:str=''
    source_quote:str=''
    basis:Literal['observed','author_interpretation','external_reference','not_applicable','unassessed']='unassessed'
    checks:dict[str,Literal['matched','mismatch','unknown','not_applicable']]=Field(default_factory=dict)
    boundary:str=''

    @field_validator('checks',mode='before')
    @classmethod
    def conservative_unknown(cls,value):
        return EvidenceJudgement.conservative_unknown(value)


class AuditedSegment(BaseModel):
    segment_id:str
    no_factual_claim:bool=False
    reason:str=''
    facts:list[FactFinding]=Field(default_factory=list,max_length=20)


class FactAudit(BaseModel):
    segments:list[AuditedSegment]=Field(default_factory=list,max_length=12)


class EditedDraft(BaseModel):
    content:str
    explanation:str
    changes:list[str]=Field(default_factory=list,max_length=16)
    unresolved:list[str]=Field(default_factory=list,max_length=16)


def key(value):return hashlib.sha256(store.encode(value).encode()).hexdigest()


def synthesis_key(a):
    from .evidence_state import objective,current_spans
    return key([VERSION,objective(a),current_spans(a),a.get('research',{}).get('coverage'),a.get('research_decisions'),
        providers.fingerprint(providers.service_for('research'),'text')])


async def generate(a,job_id,route,instruction,schema,extra=None):
    from . import prompts
    service=providers.service_for(route);partial='';last=0
    async def emit(delta):
        nonlocal partial,last
        partial+=delta
        if time.monotonic()-last>.5:store.update_job(job_id,partial=partial);last=time.monotonic()
    context=dict(brief=a['brief'],research_contract=a.get('research_contract',{}),sources=source_context.sources(a),
        evidence=source_context.evidence(a),argument_synthesis=a.get('argument_synthesis',{}),outline=a.get('outline',{}),
        issue_decisions=a.get('research_decisions',{}),**(extra or {}))
    if schema is FactAudit:
        from .research import audit_context
        context={**audit_context(a,'review'),**(extra or {})}
    prompt=json.dumps(dict(task=instruction,context=context,schema=schema.model_json_schema()),ensure_ascii=False)
    try:raw,usage=await providers.generate(service,prompts.system(route,a['brief']),prompt,emit)
    except BaseException:
        store.add_usage(a['id'],stage=route,model=service['model'],service=service['name'],status='unknown',estimated_cost=None)
        raise
    store.add_usage(a['id'],stage=route,**usage);store.update_job(job_id,partial=raw)
    return parse(raw,schema)


async def synthesize(a,job_id):
    signature=synthesis_key(a)
    if a.get('argument_synthesis',{}).get('input_key')==signature:return a
    store.update_job(job_id,message='正在形成核心判断、证据链与最强反方',current_step='synthesis')
    result=await generate(a,job_id,'research','在大纲之前综合论证：用固定任务书保留选题价值，形成核心判断、支持链、最强反方、证据冲突、适用边界和读者所得。'
        'chain 每个判断解释证据如何支持；evidence_ids/source_ids 只引用输入中已有且适用的依据。不能把背景当核心证明，不能将作者机制推测变成实测。未解决事项写入 unresolved，不自行降低目标。',ArgumentSynthesis)
    evidence={e.get('evidence_id'):e.get('source_id') for c in a.get('evidence',{}).get('claims',[]) for e in c.get('evidence',[])}
    sources={s['id'] for s in a['sources'] if s.get('selected')}
    ids=[item['id'] for item in result['chain']]
    if len(set(ids))!=len(ids) or any(not x for x in ids):raise ValueError('论证综合的判断编号重复或为空')
    for item in result['chain']:
        if set(item['source_ids'])-sources or set(item['evidence_ids'])-set(evidence):raise ValueError('论证综合引用了未知依据，已保留原始结果')
        if {evidence[eid] for eid in item['evidence_ids']}-set(item['source_ids']):raise ValueError('论证综合的证据与来源对应不一致')
    result.update(version=VERSION,input_key=signature,created=store.now())
    store.update_job(job_id,argument_synthesis=result)
    return store.save_article(a['id'],a['revision'],lambda v:v.update(argument_synthesis=result),'形成论证综合')


def segments(content):
    result=[]
    for match in re.finditer(r'\S[\s\S]*?(?=\n\s*\n|\Z)',content):
        text=match.group().strip()
        if not text:continue
        for offset in range(0,len(text),2500):
            piece=text[offset:offset+2500]
            factual_text=re.sub(r'\[S[^\]\n]+\]','',piece)
            result.append(dict(id='P'+str(len(result)+1),text=piece,start=match.start()+offset,
                mandatory=bool(re.search(r'\d|[“”「」]|研究(?:发现|显示|表明|证实|证明|只支持|仅支持)|实验证明|数据显示|\bstudy (?:found|showed)|\btrial (?:found|showed)',factual_text,re.I))))
    return result


def audit_findings(a,parts,result):
    from .bibliography import citation_ids
    source_map={s['id']:s for s in a['sources'] if s.get('selected')}
    rows=result.get('segments',[]);issues=[];checked=[]
    def issue(part,quote,reason,ids=()):
        issues.append(dict(id='F'+key([part['id'],quote,reason])[:16],severity='blocker',quote=quote,reason=reason,suggestion='',source_ids=list(ids),status='pending',kind='fact_check'))
    for part in parts:
        matches=[r for r in rows if r['segment_id']==part['id']]
        if len(matches)!=1:
            issue(part,part['text'],'这一段未得到完整独立核查。');continue
        row=matches[0]
        if row.get('no_factual_claim') and not row.get('facts') and not part['mandatory']:
            checked.append(dict(segment_id=part['id'],status='no_factual_claim',reason=row.get('reason','')));continue
        facts=row.get('facts',[])
        if not facts:
            issue(part,part['text'],'本段含需核对的数字、研究或引语，但没有逐项核查结果。');continue
        checked.append(dict(segment_id=part['id'],status='checked',facts=facts))
        for fact in facts:
            quote=fact['quote'];src=source_map.get(fact.get('source_id'));support=fact['status']
            failure=fact['reason']
            if not quote or quote not in part['text']:
                issue(part,part['text'],'事实核查未能定位到本段原句。');continue
            if support in ('supported','limited'):
                if not src or src.get('status') not in ('retrieved','abstract_only','user_provided') or not fact['source_quote'] or fact['source_quote'] not in src.get('text',''):
                    support='unsupported';failure='未在可用原文中定位到对应引文，尚不能确认正文表述。'
                else:
                    span=dict(evidence_id='audit',claim=quote,boundary=fact.get('boundary',''))
                    verdict=EvidenceJudgement.model_validate(dict(evidence_id='audit',support=support,reason=fact['reason'],basis=fact.get('basis','unassessed'),checks=fact.get('checks',{}))).model_dump()
                    research_contract.apply_judgements([span],[verdict]);support=span['support']
                    if support=='limited' and fact['status']=='supported':support='unsupported';failure='来源仅提供解释或转引，正文尚未明确保留这一层限制。'
                if support in ('supported','limited') and fact['source_id'] not in citation_ids(part['text']):
                    issue(part,quote,'重要事实未在相邻段落标明可支持它的来源。',[fact['source_id']]);continue
            fact['checked_status']=support
            if support not in ('supported','limited'):issue(part,quote,failure or '来源尚不足以支持该表述。',[fact['source_id']] if src else [])
    return checked,issues


async def audit(a,job_id):
    parts=segments(a['content']);checked=[];issues=[]
    for start in range(0,len(parts),12):
        batch=parts[start:start+12]
        store.update_job(job_id,message=f'正在独立核查正文事实（{start+1}—{start+len(batch)}段）',current_step='fact_check')
        result=await generate(a,job_id,'review','独立审核每个 segments 段落，不采信作者或研究整理的自评。每段必须返回唯一 segment_id；逐条检查所有数字、具体研究结论、直接引语、重要事实，包括未标引用的表述。'
            'facts.quote 逐字摘录正文，source_quote 逐字摘录原文，source_id 指向实际支持该句的来源；检查相邻引用是否张冠李戴。不能用记忆补证。'
            '每条给出 status、reason、basis 和 '+ '/'.join(research_contract.CHECKS)+' 各项 checks；观察与实验、分母、适用人群、相关与因果及时间版本不可混淆，不适用项明确标not_applicable。'
            '只有无事实性主张才 no_factual_claim=true。limited 仅限正文已经明确保留限定条件；正文缺条件应 unsupported。范文和个人经历不得挪用。',FactAudit,dict(segments=batch))
        done,problems=audit_findings(a,batch,result);checked.extend(done);issues.extend(problems)
    return dict(version=VERSION,input_key=review_state.signature(a),segments=checked,issues=issues,complete=len(checked)==len(parts),created=store.now())


async def edit(a,job_id,instruction=''):
    store.update_job(job_id,message='正在整体编辑结构、论证和表达，原稿保留',current_step='editing')
    return await generate(a,job_id,'write','生成完整编辑候选稿：检查开头是否聚焦、论证顺序、重复观点、段落篇幅、结尾所得，必要时重组整节。'
        '按固定任务书保留用户选题、语气与论证主线，论证综合供参考；必要的限定融入句意，核查过程留在说明中，不把正文改成审查报告。保留用户人工决定，仅从提供原文核对事实，不能靠改句式掩盖无证据主张。'
        'source IDs 保留，不手工重编号。中文篇幅以brief.words为目标（±15%）；引用跟随具体事实，避免每句机械加引文。'
        'content 返回完整Markdown正文，不含标题和参考文献表；说明结构变化与仍未解决的问题。用户补充要求：'+instruction,EditedDraft,dict(article=a['content'],review=a.get('review',{})))


def gate(review,factual):
    result=copy.deepcopy(review);scores=result.get('dimensions',{})
    valid=all(type(scores.get(k)) is int and 1<=scores[k]<=5 for k in DIMENSIONS)
    enough=valid and min(scores[k] for k in DIMENSIONS)>=3 and sum(scores[k] for k in DIMENSIONS)>=20
    result['dimensions']={k:scores.get(k) for k in DIMENSIONS}
    result['fact_audit']=factual;result['quality_version']=VERSION
    result.setdefault('issues',[]).extend(factual.get('issues',[]))
    if not enough:
        result['issues'].append(dict(id='quality-dimensions',severity='major',quote='',reason='五项编辑评分未达到自动通过要求：平均至少4分、各项至少3分，缺项需复核。',suggestion='',source_ids=[],status='pending'))
    if result['issues'] or not factual.get('complete') or not enough:result['decision']='revise'
    return result


def record_draft(a,kind,content,parent_id=None,**details):
    rows=a.setdefault('draft_versions',[])
    item=dict(id=store.uid(),kind=kind,content=content,content_key=key(content),created=store.now(),parent_id=parent_id or a.get('current_draft_id',''),**details)
    rows.append(item);a['current_draft_id']=item['id']
    if details.get('origin')=='ai':a.pop('human_edit_base',None)
    return item


def note_human_change(a):
    current=next((x for x in a.get('draft_versions',[]) if x['id']==a.get('current_draft_id')),None)
    if current and current.get('origin')=='ai':
        a.setdefault('human_edit_base',dict(draft_id=current['id'],created=store.now()))


def diff(before,after):
    result=[]
    old=before.splitlines(keepends=True);new=after.splitlines(keepends=True)
    for kind,i,j,k,l in difflib.SequenceMatcher(a=old,b=new,autojunk=False).get_opcodes():
        result.append(dict(kind=kind,before=''.join(old[i:j]),after=''.join(new[k:l])))
    return result


def save_candidate(base,job_id,edited,review):
    candidate=dict(id=store.uid(),version=VERSION,base_key=review_state.signature(base),base_revision=base['revision'],base_content=base['content'],
        content=edited['content'],explanation=edited['explanation'],changes=edited.get('changes',[]),unresolved=edited.get('unresolved',[]),
        review=review,diff=diff(base['content'],edited['content']),status='pending',created=store.now(),job_id=job_id)
    latest=store.get_article(base['id'])
    return store.save_article(base['id'],latest['revision'],lambda v:v.setdefault('editorial_candidates',[]).append(candidate),'保存整体编辑候选'),candidate


def candidate_review(article_id,candidate_id,review):
    latest=store.get_article(article_id)
    def change(v):
        c=next(x for x in v['editorial_candidates'] if x['id']==candidate_id)
        c.update(review=review,checked=True)
    return store.save_article(article_id,latest['revision'],change,'保存候选稿独立审核')


def adopt(a,candidate_id,automatic=False):
    def change(v):
        candidate=next((x for x in v.get('editorial_candidates',[]) if x['id']==candidate_id),None)
        if not candidate or candidate['status']!='pending':raise ValueError('整体编辑候选已处理或不存在')
        if not candidate.get('checked'):raise ValueError('候选稿尚未完成独立核查，请完成后再采用')
        if review_state.signature(v)!=candidate['base_key']:raise store.Conflict('正文、任务或依据已改变；候选已保留，请对照差异后重新生成')
        if automatic and any(x['severity']=='blocker' for x in candidate['review'].get('issues',[])):raise ValueError('候选仍有事实问题，不能自动采用')
        from .bibliography import citation_ids
        if set(citation_ids(candidate['content']))-{s['id'] for s in v['sources'] if s.get('selected')}:raise ValueError('候选含未知引用，不能直接采用')
        v['content']=candidate['content'];candidate['status']='adopted';candidate['adopted_by']='auto' if automatic else 'human'
        record_draft(v,'edited',v['content'],candidate_id=candidate_id,origin='ai')
        review=copy.deepcopy(candidate['review']);review.update(round_id=store.uid(),job_id=candidate['job_id'],reviewed_key=review_state.signature(v),content_revision=v['revision'])
        if review['decision']=='pass':review['completion']='ai'
        v['review']=review;v['stages']['write']='done';v['stages']['review']='done' if review['decision']=='pass' else 'needs_input'
    return store.save_article(a['id'],a['revision'],change,'自动采用整体编辑稿' if automatic else '采用整体编辑候选',invalidate='review')
