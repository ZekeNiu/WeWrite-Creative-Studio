"""Isolated UI acceptance fixtures. Never imported by the normal launcher."""
import io
import json
from PIL import Image
from backend.app import app
from backend import providers,materials,browser_search,search_tools

async def generate(s,system,prompt,emit=None):
    v=json.loads(prompt) if prompt.startswith('{') else {}
    schema=v.get('schema',{}).get('title');ctx=v.get('context') or v.get('资料与当前内容') or {}
    sources=ctx.get('sources',[]);ids=[x['id'] for x in sources]
    if schema=='ResearchPlan':r={'needed':not sources,'queries':['训练 研究证据'],'questions':['研究适用范围']}
    elif schema=='SearchSelection':r={'urls':[x['url'] for x in v.get('candidates',[])]}
    elif schema=='ResearchNotes':r={'summary':'这是一份模拟验收材料：已整理原始发现、适用范围与局限。','evidence':[{'source_id':ids[0],'quote':'研究只适用于给定条件。','claim':'解释结果需要限定条件','boundary':'不能外推到所有人'}] if ids else [],'gaps':[],'conflicts':[],'followup_queries':[]}
    elif schema=='TopicsResult':r={'topics':[{'title':f'验收选题 {i+1}：如何理解研究边界','angle':'从证据与读者问题出发','audience':'大众读者','reason':'有可追溯的素材','source_ids':ids[:1]} for i in range(10)]}
    elif schema=='EvidenceResult':r={'summary':'模拟资料分析，不能用于真实健康建议','claims':[{'id':'C1','text':'结论受条件限制','type':'fact','source_ids':ids[:1],'status':'bounded','boundary':'仅用于验收'}],'gaps':[]}
    elif schema=='OutlineResult':r={'thesis':'理解研究需要关注边界','reader_question':'研究能说明什么','takeaway':'先看证据再应用','counterpoint':'不同人群可能不同','boundary':'模拟内容','sections':[{'id':'s1','title':'证据与条件','purpose':'解释证据','points':['研究范围'],'claim_ids':['C1']}]}
    elif schema=='ReviewResult':r={'decision':'pass','summary':'模拟审核完成；不代表真实事实验证','issues':[],'dimensions':{'准确':4},'title':'理解证据的边界','digest':'验收样稿','tags':['验收']}
    elif schema=='RevisionResult':r={'replacement':'研究只适用于给定条件。','explanation':'保留边界'}
    elif schema=='VisualResult':r={'images':[{'id':'cover','role':'cover','prompt':'A green leaf','caption':'模拟验收图片'}]}
    else:r='## 证据与条件\n\n这是模拟验收样稿。研究只适用于给定条件。'+('['+ids[0]+']' if ids else '')
    text=json.dumps(r,ensure_ascii=False) if isinstance(r,dict) else r
    if emit:await emit(text)
    return text,{'model':s['model'],'service':s['name'],'input_tokens':120,'output_tokens':240,'seconds':.01,'estimated_cost':None,'status':'completed'}

async def search(query,engine='bing'):
    return [{'url':f'https://fixture.example.org/paper/{i}','title':f'模拟原始研究 {i+1}','content':'研究只适用于给定条件。','provider':engine} for i in range(3)]

async def native(s,query,limit=1):return await search(query,'native'),{'calls':1,'seconds':.01,'usage':{'input_tokens':20,'output_tokens':30}}
async def read(url):return materials.source('模拟原始研究','研究只适用于给定条件。'+url+'\n这是供界面验收使用的模拟材料。'*20,url,'web')
async def image(s,*args):
    out=io.BytesIO();Image.new('RGB',(256,256),'#91bba6').save(out,'PNG');return out.getvalue()
async def public(url):return url.startswith('https://fixture.example.org/')
providers.generate=generate
providers.image_generate=image
browser_search.search=search
browser_search.public_url=public
materials.from_url=read
search_tools.native=native
