import asyncio
import io
import json
import re
import time
from PIL import Image
from pydantic import ValidationError
from . import store, providers, prompts, materials, rendering, research
from .models import STAGES, LABELS, SCHEMAS

TASKS: dict[str,asyncio.Task]={}


def parse(stage,text):
    if stage not in SCHEMAS: return text.strip().removeprefix('```markdown\n').removesuffix('```').strip()
    cleaned=text.strip()
    if cleaned.startswith('```'): cleaned=re.sub(r'^```(?:json)?\s*|\s*```$','',cleaned)
    try: return SCHEMAS[stage].model_validate_json(cleaned).model_dump()
    except (ValidationError,ValueError): raise ValueError('模型结果不符合本环节的数据格式，原始结果已保留。可换模型或重新生成。') from None


def validate_result(stage,result,a):
    sources={s['id']:s for s in a['sources'] if s['selected']}
    if stage in ('topic','sources','review'):
        items=result.get({'topic':'topics','sources':'claims','review':'issues'}[stage],[])
        ids=[]
        for x in items:
            if 'id' in x:
                if x['id'] in ids: raise ValueError('模型返回了重复的条目编号，请重新生成')
                ids.append(x['id'])
            if any(s not in sources for s in x.get('source_ids',[])): raise ValueError('模型引用了本任务中不存在或未采用的来源，结果未应用')
            if stage=='sources' and x['type']=='fact' and not x['source_ids']: x['status']='unsupported'
            if stage=='sources' and x['type']=='user_experience' and not any(sources[s].get('personal_material') for s in x['source_ids']): x['status']='unsupported'
        if stage=='review':
            for x in items: x['status']='pending'
            if items and result['decision']=='pass': result['decision']='revise'
            if any(i['severity']=='blocker' for i in items): result['decision']='revise'
    if stage=='write':
        citations=re.findall(r'\[(S[a-zA-Z0-9]+)\]',result)
        if any(c not in sources for c in citations): raise ValueError('正文引用了不存在的来源编号，结果已保留但未应用')


def prerequisites(stage,a):
    if stage in ('sources','outline','write') and not a['brief']['topic']:
        raise ValueError('请先选择一个选题，或在创作设置中填写指定主题')
    if stage=='write' and (not a['outline'] or a['stages']['outline']=='stale'):
        raise ValueError('请先确认当前大纲；已有大纲需要更新时，可编辑后点击确认')
    if stage in ('outline','write') and a['evidence'] and a['stages']['sources']=='stale' and not (stage=='outline' and providers.settings()['search']['enabled']):
        raise ValueError('采用的素材已变化，请先重新分析素材，避免沿用过期证据')
    if stage in ('review','visual','layout','layout_advice','revise') and not a['content'].strip():
        raise ValueError('请先写作或导入正文')


def start(article_id,request):
    a=store.get_article(article_id)
    if a['revision']!=request.revision: raise store.Conflict('文章已更新，请等待保存完成后重试')
    if request.stage not in [*STAGES,'revise','image','layout_advice','research']: raise ValueError('未知环节')
    prerequisites(request.stage,a)
    j=store.create_job(article_id,request.model_dump())
    TASKS[j['id']]=asyncio.create_task(run(j['id']))
    return j


def cancel(id):
    if id in TASKS: TASKS[id].cancel()
    return store.update_job(id,status='cancelled',ended=store.now(),message='已停止；已完成的结果保留，已发出的请求可能仍计费')


async def call(job_id,stage,a,request):
    s=providers.service_for(stage); text=''; last=0
    async def emit(delta):
        nonlocal text,last
        text+=delta
        if time.monotonic()-last>.3:
            store.update_job(job_id,partial=text)
            store.event(job_id,'progress',stage=stage,characters=len(text))
            last=time.monotonic()
    try:
        raw,usage=await providers.generate(s,prompts.system(stage,a['brief']),prompts.prompt(stage,a,request),emit)
        store.add_usage(a['id'],stage=stage,**usage)
        store.update_job(job_id,partial=raw)
    except BaseException:
        store.update_job(job_id,partial=text)
        store.add_usage(a['id'],stage=stage,model=s['model'],service=s['name'],status='unknown',estimated_cost=None,currency=s.get('currency','CNY'))
        raise
    result=parse(stage,raw); validate_result(stage,result,a)
    store.update_job(job_id,result=result)
    return result



def apply_result(a,stage,result,request):
    def change(v):
        v['stages'][stage]='done'
        if stage=='topic':
            v['topics']=result['topics']
            if v['auto']['topic']:
                v['title']=result['topics'][0]['title']; v['brief']['topic']=v['title']
            else: v['stages']['topic']='needs_input'
        elif stage=='sources': v['evidence']=result
        elif stage=='outline':
            if request.get('section_id') and v['outline']:
                section=next((x for x in result['sections'] if x['id']==request['section_id']),None)
                if section is None: raise ValueError('模型没有返回指定章节，大纲保持不变')
                v['outline']['sections']=[section if x['id']==section['id'] else x for x in v['outline']['sections']]
            else: v['outline']=result
        elif stage=='write': v['content']=result
        elif stage=='review':
            from wewrite.commands.humanness_score import score_article
            result['tool_hints']=score_article(v['content'])
            result['content_revision']=v['revision']
            v['review']=result
            if result['decision']!='pass': v['stages']['review']='needs_input'
        elif stage=='visual': v['image_plans']=result['images'][:v['visual']['count']]
        v['current_stage']=stage
    return store.save_article(a['id'],a['revision'],change,'AI 完成'+LABELS[stage],invalidate=stage)


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
    s=providers.service_for('image'); price=s.get('image_price')
    if price is None or price<=0: raise ValueError('请先在图片服务中填写可靠的每张预估价格，才能按预算生成图片')
    if s.get('currency','CNY')!='CNY': raise ValueError('图片预算以人民币计，请配置人民币每张价格')
    used=sum(u.get('reserved_cost',0) for u in store.usage(a['id']) if u.get('stage')=='image')
    if used+price>a['visual']['budget']+1e-8: raise ValueError('本篇图片预算不足，请调整预算或减少图片数量。未知结果的请求仍占用预留。')
    reservation=store.add_usage(a['id'],stage='image',model=s['model'],service=s['name'],reserved_cost=price,estimated_cost=price,currency='CNY',status='reserved')
    store.update_job(job_id,message='正在生成图片；连接中断时不会自动重复请求')
    try:
        blob=await providers.image_generate(s,plan['prompt'],a['visual']['size'])
    except BaseException:
        store.update_usage(reservation['id'],status='unknown',estimated_cost=None)
        raise
    image=Image.open(io.BytesIO(blob)); image.load()
    if image.width*image.height>40_000_000: raise ValueError('图片尺寸过大')
    filename=store.uid()+'.png'; p=store.article_dir(a['id'])/'assets'; p.mkdir(exist_ok=True)
    image.convert('RGB').save(p/filename,'PNG')
    store.update_usage(reservation['id'],status='completed')
    item=dict(plan,filename=filename,selected=True,created=store.now(),id=store.uid())
    store.update_job(job_id,result={'image':item})
    try:
        return store.save_article(a['id'],a['revision'],lambda v:v['images'].append(item),'生成图片',invalidate='visual')
    except store.Conflict:
        current=store.get_article(a['id']);item['selected']=False
        store.save_article(a['id'],current['revision'],lambda v:v['images'].append(item),'保存待确认图片')
        raise store.Conflict('文章在生图期间已更新。图片已保存在配图库，默认未采用，请查看后选择。') from None


async def run(job_id):
    j=store.job(job_id); a=store.get_article(j['article_id']); req=j['request']; stage=req['stage']
    try:
        if a['revision']!=req['revision']: raise store.Conflict('启动前文章已有更新，请重新开始')
        store.update_job(job_id,status='running')
        while True:
            prerequisites(stage,a)
            store.update_job(job_id,stage=stage,message='正在'+LABELS.get(stage,{'revise':'修改选段','image':'生成图片','layout_advice':'分析排版'}.get(stage,stage)),partial='')
            store.event(job_id,'stage',stage=stage)
            if stage in ('topic','sources','outline','review','research'):
                a,pending=await research.gather(a,job_id,stage,req.get('instruction','') if stage=='research' else '')
                if pending:
                    store.update_job(job_id,status='completed',ended=store.now(),message='资料已保留；关键证据仍有缺口或冲突，请到素材查看')
                    break
                if stage in ('outline','review') and a['stages']['sources']=='stale':
                    evidence=await call(job_id,'sources',a,req);a=apply_result(a,'sources',evidence,req)
            if stage=='research':
                store.update_job(job_id,status='completed',ended=store.now(),message='资料检索与整理已完成');break
            if stage=='layout':
                rendering.render(a)
                def layout_ready(v):
                    v['stages']['layout']='done';v['current_stage']='layout'
                a=store.save_article(a['id'],a['revision'],layout_ready,'生成排版预览')
            elif stage=='image':
                plan=next((p for p in a['image_plans'] if p['id']==req['image_id']),None)
                if not plan: raise ValueError('请先生成或添加配图方案')
                a=await generate_image(a,job_id,plan)
            elif stage=='revise':
                result=await call(job_id,stage,a,req)
                item=dict(id=store.uid(),original=req['selected_text'] or a['content'],base_revision=a['revision'],**result)
                def suggest(v):
                    v['suggestions'].append(item);v['current_stage']='write'
                a=store.save_article(a['id'],a['revision'],suggest,'生成修改建议')
            elif stage=='layout_advice':
                result=await call(job_id,stage,a,req)
                a=store.save_article(a['id'],a['revision'],lambda v:v.update(layout_advice=result),'生成排版建议')
            else:
                result=await call(job_id,stage,a,req)
                a=apply_result(a,stage,result,req)
                if stage=='review' and a['auto']['review'] and result['decision']!='pass':
                    fixed=apply_review_fixes(a)
                    if fixed:
                        a=fixed; store.update_job(job_id,message='正在复审修改后的正文（第 2 轮）')
                        result=await call(job_id,'review',a,req); a=apply_result(a,'review',result,req)
                if stage=='visual' and a['auto']['visual']:
                    for plan in a['image_plans']: a=await generate_image(a,job_id,plan)
            store.event(job_id,'saved',revision=a['revision'])
            if stage not in STAGES or not req['chain'] or not a['auto'][stage] or a['stages'][stage]=='needs_input': break
            idx=STAGES.index(stage)+1
            if idx>=len(STAGES): break
            stage=STAGES[idx]
            if stage=='visual' and not a['visual']['enabled']: stage='layout'
            req={**req,'instruction':'','section_id':'','selected_text':''}
        store.update_job(job_id,status='completed',ended=store.now(),message='已完成，等待你查看' if stage not in STAGES or not a['auto'].get(stage) else '本次流程已完成或已到达需要处理的环节')
    except asyncio.CancelledError:
        store.update_job(job_id,status='cancelled',ended=store.now(),message='已停止；内容已保留，已发出的请求可能计费')
    except store.Conflict as exc:
        note=' 原始生成结果已保留，可展开查看。' if store.job(job_id).get('partial') else ''
        store.update_job(job_id,status='conflict',ended=store.now(),message=str(exc)+note)
    except Exception as exc:
        message=str(exc) if isinstance(exc,(ValueError,KeyError)) else '此环节未完成，内容已保留。请检查配置或重试。'
        store.update_job(job_id,status='failed',ended=store.now(),message=message)
    finally:
        store.event(job_id,'finished',status=store.job(job_id)['status']); TASKS.pop(job_id,None)
