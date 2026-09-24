import asyncio
import io
import json
import re
import time
from PIL import Image
from pydantic import ValidationError
from . import store, providers, prompts, materials, rendering, research, creative,editorial,account_memory,native_runtime,native_workflow
from .models import STAGES, LABELS, SCHEMAS
from .structured_output import parse as parse_structured

TASKS: dict[str,asyncio.Task]={}


def parse(stage,text):
    if stage not in SCHEMAS: return text.strip().removeprefix('```markdown\n').removesuffix('```').strip()
    cleaned=text.strip()
    if cleaned.startswith('```'): cleaned=re.sub(r'^```(?:json)?\s*|\s*```$','',cleaned)
    try: return parse_structured(cleaned,SCHEMAS[stage])
    except (ValidationError,ValueError): raise ValueError('模型结果不符合本环节的数据格式，原始结果已保留。可换模型或重新生成。') from None


def validate_result(stage,result,a):
    sources={s['id']:s for s in a['sources'] if s['selected']}
    if stage in ('topic','sources','review'):
        items=result.get({'topic':'topics','sources':'claims','review':'issues'}[stage],[])
        ids=[]
        for x in items:
            if x.get('id'):
                if x['id'] in ids: raise ValueError('模型返回了重复的条目编号，请重新生成')
                ids.append(x['id'])
            if any(s not in sources for s in x.get('source_ids',[])): raise ValueError('模型引用了本任务中不存在或未采用的来源，结果未应用')
            if stage=='sources' and x['type']=='fact' and not x['source_ids']: x['status']='unsupported'
            if stage=='sources' and x['type']=='user_experience' and not any(sources[s].get('personal_material') for s in x['source_ids']): x['status']='unsupported'
        if stage=='review':
            if not items and result['decision']!='pass': raise ValueError('模型未给出可处理的审核意见，请重新审核；当前正文已保留')
            for x in items: x['status']='pending'
            if any(x['severity']!='minor' for x in items) and result['decision']=='pass': result['decision']='revise'
            if any(i['severity']=='blocker' for i in items): result['decision']='revise'
    if stage=='write':
        from .bibliography import citation_ids
        citations=citation_ids(result)
        if any(c not in sources for c in citations): raise ValueError('正文引用了不存在的来源编号，结果已保留但未应用')
    if stage=='outline':
        arguments={x['id'] for x in a.get('argument_synthesis',{}).get('chain',[])}
        claims={x['id'] for x in a.get('evidence',{}).get('claims',[])}
        for section in result['sections']:
            if set(section.get('argument_ids',[]))-arguments or set(section.get('claim_ids',[]))-claims:
                raise ValueError('大纲引用了不存在的判断或证据，结果已保留但未应用')


def prerequisites(stage,a):
    from .flow_state import ready
    state=ready(a).get(stage)
    if state and not state['allowed']: raise ValueError(state['reason'])
    if stage in ('layout_advice','revise','edit') and not a['content'].strip():
        raise ValueError('请先写作或导入正文')


def start(article_id,request):
    a=store.get_article(article_id)
    for existing in store.jobs(article_id):
        if existing['status'] in ('queued','running') and all(existing['request'].get(k)==request.model_dump().get(k) for k in ('stage','revision','instruction','selected_text','section_id','image_id','issue_ids','chain','resume_job_id','continuation_job_id','research_parent_id')):
            return existing
    if request.research_parent_id:
        parent=store.job(request.research_parent_id)
        if request.stage!='research' or parent['article_id']!=article_id or parent['status'] in ('running','queued') or not parent.get('research') or a.get('research',{}).get('job_id')!=parent['id']:
            raise ValueError('原检索任务已被替代，不能继续；请查看当前整理结果')
    if request.continuation_job_id:
        original=store.job(request.continuation_job_id)
        from .flow_state import job_view
        if request.stage!='research' or original['article_id']!=article_id or (job_view(original)['status']!='needs_input' and not original.get('waiting_for_materials')):
            raise ValueError('核实任务不能恢复其他文章或已结束的任务')
    if request.resume_job_id:
        original=store.job(request.resume_job_id)
        from .flow_state import job_view
        if original['article_id']!=article_id or (job_view(original)['status']!='needs_input' and not original.get('waiting_for_materials')) or original['stage']!=request.stage:
            raise ValueError('此任务不能从该环节恢复')
        for existing in store.jobs(article_id):
            if existing['request'].get('resume_job_id')==request.resume_job_id and existing['request'].get('revision')==request.revision: return existing
        from .issue_actions import parent
        valid=parent(a)
        if not valid or valid['id']!=request.resume_job_id: raise ValueError('原待续任务已被替代或完成，请从当前环节操作')
    if a['revision']!=request.revision: raise store.Conflict('文章已更新，请等待保存完成后重试')
    if request.stage not in [*STAGES,'revise','image','layout_advice','research','edit']: raise ValueError('未知环节')
    prerequisites(request.stage,a)
    j=store.create_job(article_id,request.model_dump())
    TASKS[j['id']]=asyncio.create_task(run(j['id']))
    return j


def cancel(id):
    j=store.job(id)
    if j['status'] not in ('queued','running'):return j
    if j.get('external_inflight'):
        from pathlib import Path
        home=Path(j['external_home']).resolve()
        if not home.is_relative_to((store.DATA/'native').resolve()):raise ValueError('外部任务路径无效')
        (home/'cancel-requested').write_text('cancel','utf-8')
        return store.update_job(id,cancel_requested=True,message='正在等待已发送微信请求的回执；随后停止，避免丢失远端结果')
    if id in TASKS: TASKS[id].cancel()
    return store.update_job(id,status='cancelled',ended=store.now(),message='已停止；已完成的结果保留，已发出的请求可能仍计费')


async def call(job_id,stage,a,request):
    request.pop('_account_use',None)
    factual=await editorial.audit(a,job_id) if stage=='review' else None
    if stage=='sources' and a.get('research',{}).get('analysis_signature')==research.analysis_signature() and a.get('evidence',{}).get('claims'):
        # Research already owns verified claim/evidence pairs. A second summary must not replace them.
        return dict(a['evidence'],intent=None,direction_change=a.get('creative_intent',{}).get('direction_change',''))
    store.update_job(job_id,current_step='generation',generation_revision=a['revision'],message='正在生成'+LABELS.get(stage,'当前环节'))
    s=providers.service_for(stage); text=''; last=0
    async def emit(delta):
        nonlocal text,last
        text+=delta
        if time.monotonic()-last>.3:
            store.update_job(job_id,partial=text)
            store.event(job_id,'progress',stage=stage,characters=len(text))
            last=time.monotonic()
    try:
        if stage in ('topic','outline','write','revise'):
            request['_account_use']=account_memory.capture(a,job_id,stage)
        raw,usage=await providers.generate(s,prompts.system(stage,a['brief']),prompts.prompt(stage,a,request),emit)
        account_memory.finish_use(request.get('_account_use'),'returned')
        store.add_usage(a['id'],stage=stage,**usage)
        store.update_job(job_id,partial=raw)
    except BaseException:
        account_memory.finish_use(request.get('_account_use'),'incomplete')
        store.update_job(job_id,partial=text)
        from .execution_budget import ACTIVE
        if not getattr(__import__('sys').exception(),'_metered',False):store.add_usage(a['id'],stage=stage,model=s['model'],service=s['name'],status='unknown',estimated_cost=None,currency=s.get('currency','CNY'))
        raise
    result=parse(stage,raw); validate_result(stage,result,a)
    if stage=='review':result=editorial.gate(result,factual)
    store.update_job(job_id,result=result)
    account_memory.guard(request.get('_account_use'))
    return result



def apply_result(a,stage,result,request):
    def change(v):
        v['stages'][stage]='done'
        if stage=='topic':
            creative.candidates(v,result['topics'],request.get('instruction',''))
            if v['auto']['topic']:
                creative.adopt(v,result['topics'][0]['title'],result['topics'][0]['id'])
            else: v['stages']['topic']='needs_input'
        elif stage=='sources':
            v['evidence']=prompts.clean_context(result)
            current=creative.intent(v)
            if result.get('intent') and not current.get('expanded'):
                current.update(selected={**result['intent'],'title':v['brief']['topic']},expanded=True)
            if result.get('direction_change'): current['direction_change']=result['direction_change']
            v['creative_intent']=current
        elif stage=='outline':
            if request.get('section_id') and v['outline']:
                section=next((x for x in result['sections'] if x['id']==request['section_id']),None)
                if section is None: raise ValueError('模型没有返回指定章节，大纲保持不变')
                v['outline']['sections']=[section if x['id']==section['id'] else x for x in v['outline']['sections']]
            else: v['outline']=result
            if v.get('research'): v['research']['outline_key']=research.digest(v['outline'])
        elif stage=='write':
            v['content']=result
            editorial.record_draft(v,'initial',result,origin='ai')
        elif stage=='review':
            from wewrite.commands.humanness_score import score_article
            from .review_state import signature
            result['tool_hints']=score_article(v['content'])
            result['content_revision']=v['revision']
            result.update(round_id=store.uid(),job_id=request.get('_job_id',''),reviewed_key=signature(v))
            if result['decision']=='pass': result['completion']='ai'
            v['review']=result
            if result['decision']!='pass': v['stages']['review']='needs_input'
        elif stage=='visual': v['image_plans']=result['images'][:v['visual']['count']]
        v['current_stage']=stage
    return store.save_article(a['id'],a['revision'],change,'AI 完成'+LABELS[stage],invalidate=stage,account_use=request.get('_account_use'))


def apply_review_fixes(a):
    content=a['content']; applied=[]
    for issue in a['review'].get('issues',[]):
        quote=issue['quote']
        if issue['status']=='pending' and quote and content.count(quote)==1:
            content=content.replace(quote,issue['suggestion'],1); applied.append(issue['id'])
    if not applied: return None
    def change(v):
        v['content']=content
        for issue in v['review']['issues']:
            if issue['id'] in applied: issue['status']='accepted'
    return store.save_article(a['id'],a['revision'],change,'自动应用审核建议',invalidate='write')


async def generate_image(a,job_id,plan):
    from .execution_budget import reserve,charge
    from .service_errors import service_identity
    store.update_job(job_id,stage='image',image_id=plan['id'],activity='准备生成图片',last_progress_at=store.now())
    s=providers.service_for('image'); price=s.get('image_price')
    reservation=reserve(job_id,dict(s,input_price=None,output_price=None),fixed=price)
    store.update_job(job_id,service=service_identity(s),activity='等待图片服务返回',message='正在生成图片；连接中断时不会自动重复请求')
    try:
        blob=await providers.image_generate(s,plan['prompt'],a['visual']['size'])
        image=Image.open(io.BytesIO(blob)); image.load()
        if image.width*image.height>40_000_000: raise ValueError('图片尺寸过大')
        filename=store.uid()+'.png'; p=store.article_dir(a['id'])/'assets'; p.mkdir(exist_ok=True)
        image.convert('RGB').save(p/filename,'PNG')
    except BaseException:
        charge(reservation,dict(status='unknown',estimated_cost=None))
        raise
    charge(reservation,dict(status='completed',estimated_cost=price))
    item=dict(plan,plan_id=plan['id'],filename=filename,selected=True,created=store.now(),id=store.uid())
    store.update_job(job_id,result={'image':item})
    try:
        return store.save_article(a['id'],a['revision'],lambda v:v['images'].append(item),'生成图片',invalidate='visual')
    except store.Conflict:
        current=store.get_article(a['id']);item['selected']=False
        store.save_article(a['id'],current['revision'],lambda v:v['images'].append(item),'保存待确认图片')
        raise store.Conflict('文章在生图期间已更新。图片已保存在配图库，默认未采用，请查看后选择。') from None


async def run(job_id):
    from .execution_budget import ACTIVE
    budget_token=ACTIVE.set(job_id)
    j=store.job(job_id); a=store.get_article(j['article_id']); req={**j['request'],'_job_id':job_id}; stage=req['stage']
    try:
        if a['revision']!=req['revision']: raise store.Conflict('启动前文章已有更新，请重新开始')
        store.update_job(job_id,status='running')
        while True:
            prerequisites(stage,a)
            store.update_job(job_id,stage=stage,target_stage=j['request']['stage'],message='正在'+LABELS.get(stage,{'revise':'修改选段','image':'生成图片','layout_advice':'分析阅读与结构'}.get(stage,stage)),partial='',result=None,failure=None,last_progress_at=store.now())
            store.event(job_id,'stage',stage=stage)
            # Draft review owns its independent factual audit. Re-running the
            # research pipeline here repeats notes and coverage checks before
            # auditing the same draft; missing facts remain review findings.
            if stage=='research':
                a,pending=await research.gather(a,job_id,stage,req.get('instruction',''))
                if pending and stage in ('sources','research'):
                    if stage in ('sources','research'):
                        if stage=='research' or not (req.get('chain') and a['auto'].get('sources')):
                            store.update_job(job_id,status='completed',ended=store.now(),message='本次核实已完成，仍有建议待处理，可带限定继续',waiting_for_materials=stage=='sources',result={'materials_state':a.get('materials_state')})
                            return
            if stage=='research':
                if req.get('continuation_job_id'):
                    original=store.job(req['continuation_job_id']);target=original['stage']
                    from .issue_actions import parent
                    if parent(a) and a['auto'].get(target):
                        stage=target;req={**original['request'],'resume_job_id':original['id'],'_job_id':job_id}
                        store.update_job(job_id,resumed_from=original['id'])
                        continue
                store.update_job(job_id,status='completed',ended=store.now(),message='资料检索与整理已完成');return
            if stage in native_runtime.STAGES:
                packet=await native_runtime.generate(a,job_id,stage,req)
                a=native_workflow.apply(a,stage,packet,req)
                if stage in ('review','edit'):store.update_job(job_id,review_round_id=a.get('review',{}).get('round_id'),current_step='generation')
                if stage=='visual' and a['auto']['visual']:
                    for plan in a['image_plans']:a=await generate_image(a,job_id,plan)
            elif stage=='layout':
                rendering.render(a)
                def layout_ready(v):
                    v['stages']['layout']='done';v['current_stage']='layout'
                a=store.save_article(a['id'],a['revision'],layout_ready,'生成排版预览')
            elif stage=='image':
                plan=next((p for p in a['image_plans'] if p['id']==req['image_id']),None)
                if not plan: raise ValueError('请先生成或添加配图方案')
                a=await generate_image(a,job_id,plan)
            else:raise ValueError('未知执行环节')
            store.update_job(job_id,stage=stage)
            store.event(job_id,'saved',revision=a['revision'])
            if stage not in STAGES or not req['chain'] or not a['auto'][stage] or a['stages'][stage]=='needs_input': break
            idx=STAGES.index(stage)+1
            if idx>=len(STAGES): break
            stage=STAGES[idx]
            if stage=='visual' and not a['visual']['enabled']: stage='layout'
            req={**req,'instruction':'','section_id':'','selected_text':''}
        store.update_job(job_id,status='needs_input' if a['stages'].get(stage)=='needs_input' else 'completed',ended=store.now(),message='需要你确认当前结果' if a['stages'].get(stage)=='needs_input' else '已完成，等待你查看' if stage not in STAGES or not a['auto'].get(stage) else '本次流程已完成或已到达需要处理的环节')
    except asyncio.CancelledError:
        store.update_job(job_id,status='cancelled',ended=store.now(),message='已停止；内容已保留，已发出的请求可能计费')
    except account_memory.StaleContext as exc:
        store.update_job(job_id,status='needs_input',ended=store.now(),message=str(exc),account_candidate=True)
    except store.Conflict as exc:
        note=' 原始生成结果已保留，可展开查看。' if store.job(job_id).get('partial') else ''
        store.update_job(job_id,status='conflict',ended=store.now(),message=str(exc)+note)
    except Exception as exc:
        message=str(exc) if isinstance(exc,(ValueError,KeyError)) else '此环节未完成，内容已保留。请检查配置或重试。'
        details=getattr(exc,'details',None) or dict(category='validation' if isinstance(exc,(ValueError,KeyError)) else 'unknown')
        store.update_job(job_id,status='failed',ended=store.now(),message=message,
                         failure=dict(details,stage=store.job(job_id)['stage'],at=store.now()))
    finally:
        ACTIVE.reset(budget_token)
        store.event(job_id,'finished',status=store.job(job_id)['status']); TASKS.pop(job_id,None)


async def edit_candidate(a,job_id,request):
    import copy
    base=copy.deepcopy(a)
    edited=await editorial.edit(base,job_id,request.get('instruction',''))
    a,candidate=editorial.save_candidate(base,job_id,edited,dict(decision='needs_input',issues=[],summary='候选尚未完成独立核查'))
    account_memory.guard(candidate.get('account_use'))
    proposed=copy.deepcopy(base);proposed['content']=edited['content']
    report=await call(job_id,'review',proposed,request)
    a=editorial.candidate_review(a['id'],candidate['id'],report)
    account_memory.guard(candidate.get('account_use'))
    candidate=next(x for x in a['editorial_candidates'] if x['id']==candidate['id'])
    store.update_job(job_id,editorial_candidate_id=candidate['id'],message='整体编辑候选及核查已保存，请查看差异')
    return a,candidate
