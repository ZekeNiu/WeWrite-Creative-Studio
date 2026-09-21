"""v1.4.12 acceptance server: synthetic articles, no external model/network calls."""
import asyncio
import io
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
parent=ROOT/'output/test-workspaces';parent.mkdir(parents=True,exist_ok=True)
os.environ['WEWRITE_STUDIO_DATA']=tempfile.mkdtemp(prefix='qa-v1412-',dir=parent)
os.environ['WEWRITE_HOME']=str(Path(os.environ['WEWRITE_STUDIO_DATA'])/'wewrite')
from backend.app import app
from backend import store, providers, materials,source_notebook
from backend.models import Settings
from tests.quality_fixtures import judgements
import httpx

async def deny_network(*args,**kwargs):raise RuntimeError('模拟验收不允许外部网络请求')
httpx.AsyncClient.send=deny_network
store.init()
providers.save_settings(Settings.model_validate(dict(services=[dict(id='fixture',name='离线验收',model='synthetic',key='synthetic-key')],default_service='fixture',search=dict(enabled=False,academic_enabled=False,browser_enabled=False,allow_fallback=False))))


async def generate(s,system,prompt,emit=None):
    await asyncio.sleep(.15)
    value=json.loads(prompt);schema=value.get('schema',{}).get('title')
    ctx=value.get('context') or value.get('资料与当前内容',{});sources=ctx.get('sources',[])
    if schema=='TopicsResult':r=dict(topics=[dict(id='T'+str(i),title='模拟选题 '+str(i),angle='保留研究适用条件',reason='回答具体问题',reader_question='如何理解证据',novelty='解释范围',takeaway='不外推',source_ids=[]) for i in range(1,7)])
    elif schema=='ResearchPlan':r=dict(needed=False,academic=False,queries=[],questions=[],reason='核对用户已提供资料')
    elif schema=='CoverageAudit':
        from tests.quality_fixtures import coverage_audit
        r=coverage_audit(value['candidates'])
    elif schema=='EvidenceJudgements':r=judgements(value['candidates'],ctx['research_contract'])
    elif schema=='ResearchNotes':
        r=dict(summary='研究支持关联；适用范围仍需保留。',evidence=[dict(source_id=x['id'],quote='研究只支持关联。',claim='研究支持关联',claim_id='C1',quality='suitable',source_type='原始资料',adoption_reason='原文明示关联',use_scope='研究人群',boundary='不能解释为因果') for x in sources if '研究只支持关联。' in x.get('text','')],issues=[dict(id='L1',text='样本有限，只适用于原研究人群。',kind='limitation',claim='适用范围',source_ids=[],status='open')],gaps=[],conflicts=[],followup_queries=[])
    elif schema=='OutlineResult':r=dict(thesis='研究支持关联',reader_question='如何理解研究',takeaway='保留适用条件',counterpoint='存在其他解释',boundary='不推断因果',sections=[dict(id='sec1',title='证据与应用',purpose='解释边界',points=['研究支持关联'],claim_ids=['C1'])])
    elif schema=='ReviewResult':r=dict(decision='pass',summary='模拟审核：保留研究边界。',issues=[],dimensions={'准确':4,'深度':4,'自然':4},digest='理解关联',title='研究的边界',tags=['研究'])
    elif schema=='VisualResult':r=dict(images=[dict(id='cover',role='cover',prompt='原提示词',caption='原图注')])
    elif schema=='RevisionResult':r=dict(replacement='研究仅支持所观察到的关联。',explanation='明确范围')
    elif schema=='Result':
        excluded='用户明确请求本篇不使用' in value.get('instruction','')
        # The instruction is a JSON field; keep the fixture independent of surrounding prose.
        excluded=excluded or '用户明确请求本篇不使用' in prompt
        selected=[q for q in ctx['issue_decisions'] if q['id']=='Q1']
        r=dict(decisions=[dict(issue_id=q['id'],wording='本篇不采用确定因果结论' if excluded else '研究仅支持关联',explanation='模拟局部修改',edits=[dict(target='content',original='训练必定有效。[S1]',replacement='' if excluded else '研究只支持关联。[S1]')]) for q in selected])
    elif schema=='EvidenceResult':r=dict(summary='模拟资料',claims=[],gaps=[])
    else:r='## 证据与应用\n\n模拟验收样稿：研究只支持关联。'+('['+sources[0]['id']+']' if sources else '')+'\n\n解释应限于研究中的人群和条件。'
    if schema=='ResearchNotes':r['coverage']=[dict(question_id=q['id'],status='supported',reason='模拟已核对问题') for q in ctx['research_contract']['questions']]
    raw=json.dumps(r,ensure_ascii=False) if isinstance(r,dict) else r
    if emit:await emit(raw)
    return raw,dict(model='synthetic',service='fixture',input_tokens=0,output_tokens=0,status='completed')


providers.generate=generate
async def image_generate(*args,**kwargs):
    from PIL import Image
    buffer=io.BytesIO();Image.new('RGB',(160,100),'green').save(buffer,'PNG');return buffer.getvalue()
providers.image_generate=image_generate

a=store.create_article(dict(topic='模拟排除与长证据'))
def seed(v):
    v['sources']=[dict(materials.source('长证据资料','研究只支持关联。'+'完整原文内容。'*1500),id='S1')]
    source_notebook.save(v['sources'][0],[dict(category='limitations',note='不能推断因果',quote='研究只支持关联。')],'synthetic',[dict(start=0,end=8)])
    v['content']='开头。\n\n训练必定有效。[S1]\n\n保留其他段落。'
    v['evidence']=dict(claims=[dict(id='C1',text='训练必定有效',status='unsupported',type='fact',source_ids=['S1'],evidence=[])])
    v['research']=dict(policy_version=4,summary='确定因果判断缺少依据。',issues=[dict(id='Q1',text='因果主张需要处理',kind='blocking',claim='训练必定有效',claim_id='C1',source_ids=['S1'],status='open'),dict(id='L1',text='样本有限',kind='limitation',claim='适用范围',source_ids=['S1'],status='open')],pending=True,stale=False)
    v['research'].update(query_ledger=[dict(query='causal evidence',question='因果关系是否成立',purpose='counterevidence',time_scope='all',status='exhausted',attempts=[dict(channel='pubmed',status='no_results',query='causal evidence',count=0)])],candidates=[dict(title='模拟候选',url='https://example.org/fixture',channel='pubmed',query='causal evidence',status='not_selected',reason='未回答核心问题')])
    v['stages']['write']='done';v['current_stage']='sources'
store.save_article(a['id'],a['revision'],seed,'synthetic fixture')
app.state.fixture_id=a['id']
@app.get('/api/qa-fixture')
def fixture():return dict(id=app.state.fixture_id)
app.routes.insert(0,app.routes.pop())

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=int(os.environ.get('QA_PORT','8977')),access_log=False)
