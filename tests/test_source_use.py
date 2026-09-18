import copy
import json
import asyncio
from backend import store,materials,source_use,prompts,research,providers,workflow
from tests.test_studio import client,model,new,patch,run,H


def seeded(client):
    a=new(client)
    sources=[materials.source('材料 '+str(i),'研究只适用于给定条件。') for i in range(3)]
    return store.save_article(a['id'],a['revision'],lambda v:v.update(sources=sources),'fixture')


def test_derived_use_precedence_and_context(client):
    a=seeded(client);s=a['sources'][0]
    source_use.apply(a,[{'source_id':s['id'],'text':'说明边界'}],{s['id']})
    assert source_use.effective(a,s)=='说明边界'
    s['use']='人工要求';assert source_use.effective(a,s)=='人工要求'
    assert research.context(a,'sources')['sources'][0]['use']=='人工要求'
    ctx=json.loads(prompts.prompt('write',a,{}))['资料与当前内容']['sources'][0]
    assert ctx['use']=='人工要求' and ctx['author_experience_allowed'] is False
    s['use']='';assert source_use.effective(a,s)=='说明边界'
    s['text']+='新材料';assert source_use.effective(a,s)==''


def test_use_expiry_and_unrelated_preferences(client):
    a=seeded(client);s=a['sources'][0]
    source_use.apply(a,[{'source_id':s['id'],'text':'说明边界'}],{s['id']})
    for key,value in [('layout',{'theme':'minimal'}),('auto',{}),('visual',{})]:
        b=copy.deepcopy(a);b[key]=value;assert source_use.current(b,b['sources'][0])
    for change in ('topic','purpose'):
        b=copy.deepcopy(a);b['brief'][change]='改变要求';assert not source_use.current(b,b['sources'][0])
    b=copy.deepcopy(a);b['title']='新标题';assert not source_use.current(b,b['sources'][0])


def test_derived_write_does_not_invalidate_materials_or_permissions(client):
    a=seeded(client)
    a=store.save_article(a['id'],a['revision'],lambda v:v.update(research={'stale':False},evidence={'summary':'ready'},stages={**v['stages'],'sources':'done'}),'ready')
    a=store.save_article(a['id'],a['revision'],lambda v:source_use.apply(v,[{'source_id':v['sources'][0]['id'],'text':'提供例子'}],{v['sources'][0]['id']}),'AI purposes')
    assert not a['research']['stale'] and a['stages']['sources']=='done'
    assert a['sources'][0]['ai_use_current'] and not a['sources'][0]['personal_material']
    fake={**a['sources'][0],'ai_use':{'text':'伪造','input_key':'x'}}
    a=patch(client,a,{'sources':[fake,*a['sources'][1:]]})
    assert a['sources'][0]['ai_use']['text']=='提供例子'


def test_only_read_selected_sources_and_metadata_safety(client):
    a=seeded(client);s1,s2,s3=a['sources'];s2['selected']=False;s3['status']='metadata_only'
    rows=[{'source_id':s['id'],'text':'已证实全部事实'} for s in a['sources']]+[{'source_id':'unknown','text':'x'}]
    source_use.apply(a,rows,{s1['id'],s2['id']});assert 'ai_use' not in s2 and 'ai_use' not in s3
    source_use.apply(a,rows,{s3['id']});assert '查找线索' in s3['ai_use']['text']


def test_offline_analysis_reuses_one_model_call_and_preserves_manual(client,model,monkeypatch):
    a=seeded(client);a['sources'][0]['use']='保留我的要求'
    a=patch(client,a,{'sources':a['sources']},'sources');calls=[]
    async def generate(s,system,prompt,emit=None):
        v=json.loads(prompt);ctx=v['资料与当前内容'];calls.append(v['schema']['title'])
        assert all(not x['author_experience_allowed'] for x in ctx['sources'])
        return json.dumps({'summary':'ready','claims':[],'source_uses':[{'source_id':x['id'],'text':'说明适用边界'} for x in ctx['sources']]}),{'status':'completed'}
    monkeypatch.setattr(providers,'generate',generate)
    assert run(client,a,'sources',chain=False)['status']=='completed'
    a=store.get_article(a['id']);assert calls==['EvidenceResult']
    assert all(s['ai_use_current'] for s in a['sources'])
    assert a['sources'][0]['use']=='保留我的要求'


def test_batch_selection_atomic_keeps_other_sources_and_conflict(client):
    a=seeded(client);rev=a['revision'];ids=[s['id'] for s in a['sources']]
    a=patch(client,a,{'sources':[{'id':sid,**({'selected':False} if i<2 else {})} for i,sid in enumerate(ids)]},'sources')
    assert a['revision']==rev+1 and [s['id'] for s in a['sources']]==ids
    assert [s['selected'] for s in a['sources']]==[False,False,True]
    r=client.patch('/api/articles/'+a['id'],headers=H,json={'revision':rev,'changes':{'sources':[{'id':ids[0]}]}})
    assert r.status_code==409 and len(store.get_article(a['id'])['sources'])==3


def test_old_results_and_legacy_manual_use(client):
    a=seeded(client);a['sources'][0]['use']='旧版用途'
    a=patch(client,a,{'sources':a['sources']},'sources')
    a=workflow.apply_result(a,'sources',{'summary':'旧版结果','claims':[],'gaps':[]},{})
    assert a['sources'][0]['use']=='旧版用途' and 'ai_use' not in a['sources'][0]


def test_research_notes_produce_use_without_extra_call(client,model,monkeypatch):
    a=seeded(client);calls=[]
    from backend.models import ResearchPlan,ResearchNotes
    async def structured(a,stage,instruction,schema,job_id,candidates=None):
        calls.append(schema.__name__)
        if schema is ResearchPlan:return ResearchPlan(needed=False,queries=[],questions=[]).model_dump()
        assert schema is ResearchNotes
        return ResearchNotes(summary='已核对',evidence=[dict(source_id=a['sources'][0]['id'],quote='研究只适用于给定条件。',claim='有适用范围')],source_uses=[dict(source_id=s['id'],text='说明适用范围') for s in a['sources']]).model_dump()
    monkeypatch.setattr(research,'structured',structured)
    cfg=store.get_settings();cfg['search']['enabled']=True;store.set_settings(cfg)
    j=store.create_job(a['id'],{'stage':'sources','revision':a['revision']})
    result,pending=asyncio.run(research.gather(a,j['id'],'sources'))
    assert not pending and calls==['ResearchPlan','ResearchNotes']
    assert all(s['ai_use_current'] for s in result['sources'])
    assert not result['research']['stale']
