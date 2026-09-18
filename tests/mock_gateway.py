"""Offline QA gateway. Never loaded by the delivered application or launcher."""
import base64
import io
import json
from fastapi import FastAPI,Request
from fastapi.responses import StreamingResponse
from PIL import Image,ImageDraw

app=FastAPI()
observed=[]


def answer(body):
    prompt=body.get('input') or body.get('messages',[{}])[-1].get('content','')
    try: value=json.loads(prompt)
    except (ValueError,TypeError): return '连接成功'
    ctx=value['资料与当前内容'];kind=value.get('schema',{}).get('title');sources=[x['id'] for x in ctx['sources']]
    source=sources[0] if sources else ''
    if kind=='TopicsResult':
        result={'topics':[{'title':title,'angle':angle,'audience':'希望理解证据的普通读者','reason':'问题明确，可以从已有材料出发，解释条件与边界。','source_ids':sources[:1]} for title,angle in [
          ('力量训练的效果，为什么不能只看一项数字？','从训练目标、观察指标和个体差异切入'),('读懂一项训练研究，先问这三个问题','从研究人群、比较条件和结果含义入手'),('同样的训练计划，为什么适合的人不同？','讨论个体条件与计划调整'),('运动建议里的“有效”，究竟是什么意思？','区分统计结果与实际应用'),('训练越多越好吗？先看恢复与目标','解释剂量和恢复的关系'),('别急着照搬：从研究到实践还有多远','解释外推需要满足的条件'),('当两篇研究得出不同结论，应该相信谁？','对比方法与研究范围'),('建立训练记录，比追逐完美计划更重要吗？','关注观察、调整与可持续性'),('如何给一条运动建议划定适用边界','把建议改写成带条件的判断'),('为什么个人经验不能代替全部证据','比较经验、观察与系统研究')]]}
    elif kind=='EvidenceResult': result={'summary':'材料强调研究结果受人群、条件和指标限制，适合用于解释训练建议的适用边界。','claims':[{'id':'C1','text':'研究结果的适用范围取决于研究人群、训练条件及观察指标','type':'fact','source_ids':sources[:1],'status':'supported'}],'gaps':['尚未提供具体研究，正文不能添加具体样本量或效应数值。']}
    elif kind=='OutlineResult': result={'thesis':'训练建议需要放回条件中理解，而不能只比较一个结果数字。','reader_question':'如何判断一条训练建议是否适合自己？','takeaway':'先明确目标，再看研究条件与自身情况是否一致。','counterpoint':'简化指标有助于快速沟通，但不应替代完整判断。','boundary':'本文是阅读研究的方法说明，不是个体训练处方。','sections':[
      {'id':'s1','title':'先问清楚，这个数字测量了什么','purpose':'把观察指标放回训练目标中','points':['区分目标与测量指标','说明资料的适用范围'],'claim_ids':['C1']},
      {'id':'s2','title':'从研究人群，走到具体的人','purpose':'说明外推条件','points':['看人群、训练条件是否相近','不能直接推广到所有人'],'claim_ids':['C1']},
      {'id':'s3','title':'让建议带上适用条件','purpose':'交付阅读和判断方法','points':['保留不确定性','根据目标与反馈调整'],'claim_ids':['C1']}]}
    elif kind=='ReviewResult':
        quote='这意味着，这个结论对所有人都成立。'
        bad=quote in ctx.get('article','')
        result={'decision':'revise' if bad else 'pass','summary':'有一处结论外推超出材料范围，建议补充适用条件。' if bad else '当前正文保留了资料的适用边界，表达清晰；请最终核对来源。','issues':[{'id':'issue1','severity':'blocker','quote':quote,'reason':'材料明确说明不能直接推广到所有人，这句话与来源不一致。','suggestion':'这个结论只适用于与研究条件相近的情况，不能直接推广到所有人。','source_ids':sources[:1]}] if bad else [],'dimensions':{'准确':3 if bad else 4,'观点':4,'有用':4,'自然':4,'好读':4},'title':ctx['title'],'alt_titles':['读懂训练研究，从理解边界开始'],'digest':'理解指标，也理解它的适用范围。','tags':['运动科学','研究解读']}
    elif kind=='RevisionResult': result={'replacement':'先看清楚数字代表什么，再判断它是否回答了你的训练问题。','explanation':'压缩重复表达，保留原意。'}
    elif kind=='VisualResult': result={'images':[{'id':'cover','role':'cover','prompt':'浅绿色与米白色，训练笔记与一本打开的研究书籍，克制的编辑插画，无文字，无虚构数据','caption':'从证据到实践','after_heading':''}]}
    elif '排版建议' in value['任务']: return '1. 保留三节标题，突出从证据到应用的顺序。\n2. 在解释适用条件的一节后放置示意图。\n3. 让图注说明图片为示意，不代表真实研究数据。'
    else:
        return ('## 先问清楚，这个数字测量了什么\n\n'
        '我们常常习惯用一个数字评价训练：提高了多少、改善了多少、是否超过另一种方法。但数字必须放回问题中，才能说明它的价值。\n\n'
        f'研究结果的适用范围取决于研究人群、训练条件及观察指标。只比较结果，可能忽略它究竟回答了什么问题。'+(f'[{source}]' if source else '')+'\n\n'
        '## 从研究人群，走到具体的人\n\n'
        '一项研究可以帮助我们理解某些条件下的变化，却不能替每个人做完全部判断。阅读时，需要回到研究对象、训练安排与观察期限。\n\n'
        '这意味着，这个结论对所有人都成立。\n\n'
        '## 让建议带上适用条件\n\n'
        '训练计划应结合个体条件与目标。一个更稳妥的顺序是：明确问题，核对条件，再根据观察结果调整判断。\n\n'
        '本文没有提供具体研究数据，因此不讨论样本量或效应大小。它所能交付的，是理解建议时的一种阅读方法。')
    return json.dumps(result,ensure_ascii=False)


@app.get('/v1/models')
def models(): return {'data':[{'id':'qa-text-model'},{'id':'qa-review-model'},{'id':'qa-image-model'}]}


@app.get('/observed')
def calls(): return observed


@app.post('/v1/{path:path}')
async def generate(path:str,request:Request):
    body=await request.json();observed.append({'path':path,'model':body.get('model')})
    if path=='images/generations':
        im=Image.new('RGB',(768,512),'#ecf1e5');d=ImageDraw.Draw(im);d.rounded_rectangle((180,90,580,400),20,fill='#ffffff',outline='#abbfa0',width=3);d.line((380,110,380,380),fill='#b9cbb0',width=3)
        for y in range(160,350,35):d.line((220,y,345,y),fill='#c5d4bc',width=5);d.line((414,y,540,y),fill='#b6cfa5',width=5)
        b=io.BytesIO();im.save(b,'PNG');text=json.dumps({'type':'image_generation.completed','b64_json':base64.b64encode(b.getvalue()).decode()})
        return StreamingResponse(iter(['data: '+text+'\n\n']),media_type='text/event-stream')
    text=answer(body)
    async def stream():
        import asyncio
        for i in range(0,len(text),90):
            if path=='chat/completions': event={'choices':[{'delta':{'content':text[i:i+90]},'finish_reason':None}]}
            elif path=='responses': event={'type':'response.output_text.delta','delta':text[i:i+90]}
            else: event={'type':'content_block_delta','delta':{'type':'text_delta','text':text[i:i+90]}}
            yield 'data: '+json.dumps(event,ensure_ascii=False)+'\n\n';await asyncio.sleep(.03)
        if path=='chat/completions': event={'choices':[{'delta':{},'finish_reason':'stop'}],'usage':{'prompt_tokens':1000,'completion_tokens':600}}
        elif path=='responses': event={'type':'response.completed','response':{'usage':{'input_tokens':1000,'output_tokens':600}}}
        else: event={'type':'message_stop'}
        yield 'data: '+json.dumps(event)+'\n\n'
    return StreamingResponse(stream(),media_type='text/event-stream')
