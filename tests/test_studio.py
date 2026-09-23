import asyncio
import base64
import io
import json
import time
import zipfile
from pathlib import Path
import httpx
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from backend.app import app
from backend import store,providers,security,workflow,rendering
from backend.models import Settings,JobRequest,STAGES
from tests.editorial_fixtures import reply as editorial_reply,SCORES

H={'X-Studio-Request':'1'}


@pytest.fixture
def client(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path)
    monkeypatch.setenv('WEWRITE_HOME',str(tmp_path/'wewrite'))
    with TestClient(app) as c: yield c


def new(c,topic='测试主题',column='运动科学'):
    r=c.post('/api/articles',headers=H,json={'topic':topic,'column':column});assert r.status_code==200,r.text
    return r.json()


def patch(c,a,changes,stage='preferences'):
    r=c.patch('/api/articles/'+a['id'],headers=H,json={'revision':a['revision'],'stage':stage,'changes':changes})
    assert r.status_code==200,r.text
    return r.json()


def wait(c,j):
    for _ in range(600):
        row=c.get('/api/jobs/'+j['id']).json()
        if row['status'] not in ('queued','running'): return row
        time.sleep(.025)
    raise AssertionError('job timed out')


def run(c,a,stage,**kwargs):
    r=c.post('/api/articles/'+a['id']+'/jobs',headers=H,json={'stage':stage,'revision':a['revision'],**kwargs})
    assert r.status_code==200,r.text
    return wait(c,r.json())


@pytest.fixture
def model(monkeypatch,client):
    config=Settings.model_validate({'services':[{'id':'test','name':'测试服务','model':'fixture-model','key':'not-a-real-key','image_price':1}],
                                    'search':{'enabled':False},'default_service':'test','routes':{'write':{'service_id':'test','model':'writing-model'}}})
    providers.save_settings(config)
    calls=[]
    async def fake(s,system,prompt,emit=None):
        value=json.loads(prompt); context=value.get('资料与当前内容',value.get('context',{})); schema=value.get('schema',{}).get('title'); ids=[x['id'] for x in context.get('sources',[])]
        calls.append((schema or 'write',s['model']))
        if schema in ('ArgumentSynthesis','FactAudit','EditedDraft'):result=editorial_reply(schema,context)
        elif schema=='TopicsResult': result={'topics':[{'title':f'可靠的选题 {i+1}','angle':'从证据边界出发','reason':'明确回答读者的问题','source_ids':ids[:1]} for i in range(10)]}
        elif schema=='EvidenceResult': result={'summary':'只采用给定材料','claims':[{'id':'C1','text':'研究仅能支持限定条件下的结论','type':'fact','source_ids':ids[:1],'status':'supported','boundary':'不能扩大因果解释'}],'gaps':[]}
        elif schema=='OutlineResult': result={'thesis':'证据需要结合条件理解','reader_question':'如何理解研究结论','takeaway':'先看条件再做判断','counterpoint':'仍有其他解释','boundary':'仅适用于研究范围','sections':[{'id':'sec1','title':'先看证据','purpose':'交代事实','points':['说明条件'],'claim_ids':[c['id'] for c in context.get('evidence',{}).get('claims',[])][:1]},{'id':'sec2','title':'再看应用','purpose':'划定边界','points':['不夸大结论'],'claim_ids':[c['id'] for c in context.get('evidence',{}).get('claims',[])][:1]}]}
        elif schema=='ReviewResult': result={'decision':'pass','summary':'所给资料内未发现明显矛盾，请人工核对','issues':[],'dimensions':SCORES,'digest':'阅读研究，先看证据与边界','title':'理解证据的边界','tags':['研究']}
        elif schema=='RevisionResult': result={'replacement':'只在这些条件下，才能得出这个判断。','explanation':'补充适用条件'}
        elif schema=='VisualResult': result={'images':[{'id':'cover','role':'cover','prompt':'绿色植物，简洁插画','caption':'示意图'}]}
        else: result='## 先看证据\n\n研究结论需要结合条件理解。'+('['+ids[0]+']' if ids else '')+'\n\n## 再看应用\n\n这些材料不支持把相关性等同于因果。'
        text=json.dumps(result,ensure_ascii=False) if isinstance(result,dict) else result
        if emit: await emit(text[:10]);await emit(text[10:])
        return text,{'model':s['model'],'service':s['name'],'input_tokens':100,'output_tokens':300,'seconds':.01,'estimated_cost':None,'status':'completed'}
    monkeypatch.setattr(providers,'generate',fake)
    from tests.native_fixtures import install
    install(monkeypatch)
    return calls


def test_access_control_and_masked_secrets(client):
    assert client.post('/api/articles',json={}).status_code==403
    assert client.post('/api/articles',headers={**H,'Origin':'https://outside.example'},json={}).status_code==403
    assert client.get('/api/health',headers={'Host':'evil.example'}).status_code==403
    cfg={'services':[{'id':'localtest','key':'not-a-real-secret','model':'m'}],'default_service':'localtest'}
    r=client.put('/api/settings',headers=H,json=cfg)
    assert r.status_code==200
    assert 'not-a-real-secret' not in r.text
    assert r.json()['services'][0]['key_set']
    assert security.key('localtest')=='not-a-real-secret'
    assert b'not-a-real-secret' not in (store.DATA/'studio.sqlite').read_bytes()
    client.put('/api/settings',headers=H,json=r.json())
    assert security.key('localtest')=='not-a-real-secret'


def test_revisions_invalidation_and_restore(client):
    a=new(client);a=patch(client,a,{'content':'手工写下的原稿'},'write')
    old=a.copy();a=patch(client,a,{'content':'最新人工修改'},'write')
    conflict=client.patch('/api/articles/'+a['id'],headers=H,json={'revision':old['revision'],'stage':'write','changes':{'content':'过期结果'}})
    assert conflict.status_code==409
    assert client.get('/api/articles/'+a['id']).json()['content']=='最新人工修改'
    versions=client.get('/api/articles/'+a['id']+'/versions').json()
    r=client.post('/api/articles/'+a['id']+'/restore',headers=H,json={'revision':a['revision'],'version':versions[0]['id']})
    assert r.json()['content']=='手工写下的原稿'
    assert r.json()['revision']>a['revision']


@pytest.mark.parametrize('column',['运动科学','运动健康','AI'])
def test_full_pipeline_three_columns(client,model,column):
    a=new(client,topic='',column=column)
    a=patch(client,a,{'auto':{s:True for s in STAGES},'brief':{**a['brief'],'domain':'任意自定义领域'}})
    a=client.post('/api/articles/'+a['id']+'/sources/text',headers=H,json={'revision':a['revision'],'title':'测试参考材料','text':'这是一份用于验证流程的材料。研究只支持限定范围的解释，不能把相关性当作因果。'}).json()
    j=run(client,a,'topic');assert j['status']=='completed',j
    a=client.get('/api/articles/'+a['id']).json()
    assert len(a['topics'])==10
    assert a['title']=='可靠的选题 1'
    assert a['stages']['review']=='done' and a['stages']['layout']=='done'
    assert a['current_stage']=='layout'
    assert a['stages']['visual']=='idle' and not a['images']
    assert ('write','writing-model') in model
    assert not any(k=='VisualResult' for k,m in model)
    assert a['sources'][0]['id'] in a['content']
    r=client.get('/api/articles/'+a['id']+'/export/zip');assert r.status_code==200
    z=zipfile.ZipFile(io.BytesIO(r.content));assert {'文章.md','排版.html','来源清单.json'}<=set(z.namelist())
    before=a['content'];a=patch(client,a,{'brief':{**a['brief'],'words':2500}},'setup')
    assert a['content']==before and a['stages']['review']=='stale'


def test_manual_topic_selection_and_auto_boundary(client,model):
    a=new(client,topic='');j=run(client,a,'topic')
    assert j['status']=='needs_input'
    a=client.get('/api/articles/'+a['id']).json();assert a['stages']['topic']=='needs_input' and not a['content']
    a=client.post('/api/articles/'+a['id']+'/topic',headers=H,json={'revision':a['revision'],'title':a['topics'][2]['title']}).json()
    assert a['brief']['topic']=='可靠的选题 3'
    a=patch(client,a,{'auto':{**a['auto'],'sources':True,'outline':False}})
    j=run(client,a,'sources');assert j['status']=='completed',j
    a=client.get('/api/articles/'+a['id']).json()
    assert a['outline'] and not a['content']


def test_generation_does_not_overwrite_edit(client,model,monkeypatch):
    a=new(client);a=patch(client,a,{'content':'最初的正文'},'write')
    original=providers.generate
    async def slow(*args,**kwargs):
        await asyncio.sleep(.15);return await original(*args,**kwargs)
    monkeypatch.setattr(providers,'generate',slow)
    j=client.post('/api/articles/'+a['id']+'/jobs',headers=H,json={'revision':a['revision'],'stage':'revise','selected_text':'最初的正文','chain':False}).json()
    a=patch(client,a,{'content':'生成期间的人工修改'},'write')
    j=wait(client,j);assert j['status']=='conflict',j
    assert client.get('/api/articles/'+a['id']).json()['content']=='生成期间的人工修改'
    assert j['result']


def test_single_task_cancel_and_restart(client,model,monkeypatch):
    a=new(client)
    async def slow(*args,**kwargs): await asyncio.sleep(5)
    monkeypatch.setattr(providers,'generate',slow)
    j=client.post('/api/articles/'+a['id']+'/jobs',headers=H,json={'revision':a['revision'],'stage':'topic'}).json()
    r=client.post('/api/articles/'+a['id']+'/jobs',headers=H,json={'revision':a['revision'],'stage':'topic'})
    assert r.status_code==200 and r.json()['id']==j['id']
    different=client.post('/api/articles/'+a['id']+'/jobs',headers=H,json={'revision':a['revision'],'stage':'topic','instruction':'不同要求'})
    assert different.status_code==409
    assert client.post('/api/jobs/'+j['id']+'/cancel',headers=H).json()['status']=='cancelled'
    pending=store.create_job(a['id'],{'stage':'topic'})
    store.init()
    assert store.job(pending['id'])['status']=='interrupted'


def test_suggestions_and_review_changes(client,model):
    a=new(client);a=patch(client,a,{'content':'原文这一段。\n\n另一段不改变。'},'write')
    assert run(client,a,'revise',selected_text='原文这一段。',chain=False)['status']=='completed'
    a=client.get('/api/articles/'+a['id']).json();s=a['suggestions'][0]
    a=client.post(f'/api/articles/{a["id"]}/suggestions/{s["id"]}',headers=H,json={'revision':a['revision'],'action':'accept'}).json()
    assert '另一段不改变。' in a['content'] and not a['suggestions']
    def review(v):
        v['review']={'issues':[{'id':'i1','quote':'另一段不改变。','suggestion':'另一段更清楚。','severity':'major','reason':'表达','status':'pending'}]};v['stages']['review']='done'
    a=store.save_article(a['id'],a['revision'],review,'test')
    a=client.post(f'/api/articles/{a["id"]}/review/i1',headers=H,json={'revision':a['revision'],'action':'accept'}).json()
    assert '另一段更清楚。' in a['content'] and a['stages']['review']=='done' and a['review']['completion']=='human'


def test_import_pdf_docx_and_reject_scanned(client):
    from docx import Document
    from pypdf import PdfWriter
    a=new(client)
    doc=Document();doc.add_paragraph('中文资料，文件导入后可追溯。');blob=io.BytesIO();doc.save(blob)
    r=client.post(f'/api/articles/{a["id"]}/sources/file',headers=H,data={'revision':a['revision']},files={'file':('中文资料.docx',blob.getvalue())})
    assert r.status_code==200,r.text
    a=r.json();assert '中文资料' in a['sources'][0]['text']
    writer=PdfWriter();writer.add_blank_page(width=100,height=100);pdf=io.BytesIO();writer.write(pdf)
    r=client.post(f'/api/articles/{a["id"]}/sources/file',headers=H,data={'revision':a['revision']},files={'file':('扫描件.pdf',pdf.getvalue())})
    assert r.status_code==400 and '扫描' in r.text


def test_image_failure_no_budget_gate_and_export(client,model,monkeypatch):
    a=new(client);a=patch(client,a,{'content':'## 小节\n\n这里是正文','visual':{'enabled':True,'count':1,'size':'1024x1024','budget':1},'image_plans':[{'id':'cover','role':'cover','prompt':'test'}]},'write')
    calls=[]
    async def fail(*args,**kwargs):
        calls.append(1);raise ValueError('图片生成超时')
    monkeypatch.setattr(providers,'image_generate',fail)
    assert run(client,a,'image',image_id='cover')['status']=='failed'
    assert store.usage(a['id'])[0]['status']=='unknown' and len(calls)==1
    assert '图片生成超时' in run(client,a,'image',image_id='cover')['message']
    assert len(calls)==2
    blob=io.BytesIO();Image.new('RGB',(64,64),'green').save(blob,'PNG')
    r=client.post(f'/api/articles/{a["id"]}/images/upload',headers=H,data={'revision':a['revision'],'role':'cover'},files={'file':('cover.png',blob.getvalue())})
    assert r.status_code==200;a=r.json()
    preview=client.post(f'/api/articles/{a["id"]}/preview',headers=H).json()
    assert '/assets/' not in preview['body']  # independent cover
    z=zipfile.ZipFile(io.BytesIO(client.get(f'/api/articles/{a["id"]}/export/zip').content))
    assert any(n.startswith('images/') for n in z.namelist())
    assert 'images/' not in z.read('排版.html').decode()  # cover is independent
    assert any(n.startswith('images/') for n in z.namelist())


def test_all_themes_and_html_sanitization(client):
    a=new(client);a['content']='## 标题\n\n**加粗** 正文。<script>alert(1)</script>\n\n- 第一项\n- 第二项\n\n|列|列|\n|--|--|\n|甲|乙|'
    for theme in rendering.themes():
        a['layout']['theme']=theme['id'];result=rendering.render(a)
        assert '<script' not in result['html'] and '<h2' in result['html']
        assert '实测验证' not in result['html']
        assert 'style=' in result['body']


@pytest.mark.parametrize('protocol',['chat','responses','anthropic'])
def test_protocol_streams(monkeypatch,protocol):
    streams={
      'chat':[{'choices':[{'delta':{'content':'连接成功'},'finish_reason':None}]},{'choices':[{'delta':{},'finish_reason':'stop'}],'usage':{'prompt_tokens':3,'completion_tokens':4}}],
      'responses':[{'type':'response.output_text.delta','delta':'连接成功'},{'type':'response.completed','response':{'usage':{'input_tokens':3,'output_tokens':4}}}],
      'anthropic':[{'type':'message_start','message':{'usage':{'input_tokens':3}}},{'type':'content_block_delta','delta':{'type':'text_delta','text':'连接成功'}},{'type':'message_delta','delta':{'stop_reason':'end_turn'},'usage':{'output_tokens':4}},{'type':'message_stop'}]}
    real=httpx.AsyncClient
    def handler(req):
        body=json.loads(req.content);assert body['stream']
        return httpx.Response(200,headers={'content-type':'text/event-stream'},text=''.join('data: '+json.dumps(x,ensure_ascii=False)+'\n\n' for x in streams[protocol]))
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    s={'model':'m','protocol':protocol,'secret':'dummy','base_url':'https://api.example','name':'test','input_price':1,'output_price':1}
    text,usage=asyncio.run(providers.generate(s,'系统','输入'))
    assert text=='连接成功' and usage['input_tokens']==3 and usage['output_tokens']==4


@pytest.mark.parametrize('status',[401,403,404,429,500])
def test_provider_errors_no_secret_leak(monkeypatch,status):
    real=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(lambda r:httpx.Response(status,json={'error':'dummy-key-value'})),**kw))
    s={'model':'m','protocol':'chat','secret':'dummy-key-value','base_url':'https://api.example','name':'test'}
    with pytest.raises(ValueError) as e: asyncio.run(providers.generate(s,'s','u'))
    assert 'dummy-key-value' not in str(e.value)


def test_stream_without_completion_fails(monkeypatch):
    real=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(lambda r:httpx.Response(200,headers={'content-type':'text/event-stream'},text='data: {"choices":[{"delta":{"content":"partial"}}]}\n\n')),**kw))
    s={'model':'m','protocol':'chat','secret':'dummy','base_url':'https://api.example','name':'test'}
    with pytest.raises(ValueError,match='提前结束'): asyncio.run(providers.generate(s,'s','u'))


def test_unconfigured_services_and_public_source_boundary(client):
    a=new(client)
    assert '配置' in run(client,a,'topic')['message']
    r=client.post(f'/api/articles/{a["id"]}/sources/url',headers=H,json={'revision':a['revision'],'url':'http://127.0.0.1:8765/api/settings'})
    assert r.status_code==400
    r=client.post(f'/api/articles/{a["id"]}/sources/search',headers=H,json={'revision':a['revision'],'query':'研究'})
    assert r.status_code==200
    assert wait(client,r.json())['status']=='failed'


def test_source_change_keeps_warning_without_blocking_outline(client,model):
    a=new(client)
    a=client.post('/api/articles/'+a['id']+'/sources/text',headers=H,json={'revision':a['revision'],'text':'可供分析的原始资料'}).json()
    assert run(client,a,'sources')['status']=='completed'
    a=client.get('/api/articles/'+a['id']).json()
    a=patch(client,a,{'sources':[{**a['sources'][0],'selected':False}]},'sources')
    assert a['stages']['sources']=='stale'
    r=client.post('/api/articles/'+a['id']+'/jobs',headers=H,json={'revision':a['revision'],'stage':'outline'})
    assert r.status_code==200 and wait(client,r.json())['status']=='completed'


def test_native_review_does_not_start_extra_editing_passes(client,model,monkeypatch):
    a=new(client);a=patch(client,a,{'content':'不可靠的断言','auto':{s:True for s in STAGES}},'write')
    counter=[]
    async def always_bad(s,system,prompt,emit=None):
        value=json.loads(prompt);schema=value.get('schema',{}).get('title');ctx=value.get('资料与当前内容',value.get('context',{}))
        if schema in ('FactAudit','EditedDraft'):result=editorial_reply(schema,ctx)
        else:
            counter.append(1);content=ctx['article']
            result={'decision':'revise','summary':'仍然缺乏证据','issues':[{'id':'one','severity':'blocker','quote':content,'reason':'缺少支持','suggestion':'缩小后的判断'}],'dimensions':SCORES}
        text=json.dumps(result,ensure_ascii=False)
        return text,{'model':'qa','status':'completed','estimated_cost':None}
    monkeypatch.setattr(providers,'generate',always_bad)
    j=run(client,a,'review')
    assert j['status']=='needs_input' and len(counter)==1
    a=client.get('/api/articles/'+a['id']).json()
    assert a['stages']['review']=='needs_input' and a['stages']['layout']=='idle'


@pytest.mark.parametrize('protocol',['chat','responses','anthropic'])
def test_nonstream_json_supported(monkeypatch,protocol):
    data={'chat':{'choices':[{'message':{'content':'响应正文'}}]},'responses':{'status':'completed','output':[{'content':[{'type':'output_text','text':'响应正文'}]}]},'anthropic':{'content':[{'type':'text','text':'响应正文'}]}}[protocol]
    real=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(lambda r:httpx.Response(200,json=data)),**kw))
    text,_=asyncio.run(providers.generate({'protocol':protocol,'secret':'dummy','model':'m','name':'qa','base_url':'https://api.example'},'s','u'))
    assert text=='响应正文'


@pytest.mark.parametrize('stream',[False,True])
def test_image_json_and_sse(monkeypatch,stream):
    b=io.BytesIO();Image.new('RGB',(4,4)).save(b,'PNG')
    payload={'data':[{'b64_json':base64.b64encode(b.getvalue()).decode()}]}
    if stream: payload['type']='image_generation.completed'
    real=httpx.AsyncClient
    response=httpx.Response(200,headers={'content-type':'text/event-stream'},text='data: '+json.dumps(payload)+'\n\n') if stream else httpx.Response(200,json=payload)
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:real(transport=httpx.MockTransport(lambda r:response),**kw))
    blob=asyncio.run(providers.image_generate({'protocol':'chat','secret':'dummy','model':'m','base_url':'https://api.example'},'image','1024x1024'))
    assert blob==b.getvalue()


def test_late_image_is_retained_unselected(client,model,monkeypatch):
    a=new(client);a=patch(client,a,{'content':'旧的正文','visual':{'enabled':True,'count':1,'size':'1024x1024','budget':2},'image_plans':[{'id':'cover','role':'cover','prompt':'test'}]},'write')
    blob=io.BytesIO();Image.new('RGB',(64,64),'green').save(blob,'PNG')
    async def image(*args,**kwargs): await asyncio.sleep(.2);return blob.getvalue()
    monkeypatch.setattr(providers,'image_generate',image)
    j=client.post('/api/articles/'+a['id']+'/jobs',headers=H,json={'revision':a['revision'],'stage':'image','image_id':'cover'}).json()
    a=patch(client,a,{'content':'生图期间的新正文'},'write')
    j=wait(client,j);assert j['status']=='conflict',j
    a=client.get('/api/articles/'+a['id']).json()
    assert a['content']=='生图期间的新正文' and len(a['images'])==1 and not a['images'][0]['selected']
    assert client.get(f'/api/articles/{a["id"]}/assets/{a["images"][0]["filename"]}').status_code==200


def test_imported_text_is_not_automatically_personal_experience(client):
    a=new(client)
    a=client.post('/api/articles/'+a['id']+'/sources/text',headers=H,json={'revision':a['revision'],'text':'别人的文章中记录了第一人称故事'}).json()
    sid=a['sources'][0]['id']
    result={'claims':[{'id':'c1','type':'user_experience','text':'我亲身经历过','source_ids':[sid],'status':'supported'}]}
    workflow.validate_result('sources',result,a)
    assert result['claims'][0]['status']=='unsupported'
