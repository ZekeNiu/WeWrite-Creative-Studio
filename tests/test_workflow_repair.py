import asyncio
import pytest
from backend import store,workflow,research,flow_state
from tests.test_studio import client,model,new,patch,run,H


def test_pause_is_not_completed_or_empty_outline_confirmed(client,model,monkeypatch):
    a=new(client)
    a=store.save_article(a['id'],a['revision'],lambda v:v.update(evidence={'summary':'ready'},stages={**v['stages'],'sources':'done'}),'fixture')
    async def pause(a,job,stage,*args):
        a=store.save_article(a['id'],a['revision'],lambda v:v.update(research={'pending':True,'gaps':['核心依据不足'],'conflicts':[]},stages={**v['stages'],stage:'needs_input'}),'pause')
        return a,True
    monkeypatch.setattr(research,'gather',pause)
    j=run(client,a,'outline',chain=False)
    assert j['status']=='needs_input' and '资料核对暂停' in j['message']
    a=client.get('/api/articles/'+a['id']).json()
    assert not a['outline'] and not a['workflow']['write']['allowed']
    assert client.post('/api/articles/'+a['id']+'/confirm/outline',headers=H,json={'revision':a['revision']}).status_code==400


def test_readiness_allows_manual_draft_without_outline(client):
    a=patch(client,new(client),{'content':'手写正文'},'write')
    assert not a['workflow']['write']['allowed']
    assert a['workflow']['review']['allowed'] and a['workflow']['layout']['allowed']


def test_legacy_pause_projection_preserves_record():
    j={'status':'completed','stage':'outline','result':None,'research':{'notes':{'gaps':['gap']}}}
    assert flow_state.job_view(j)['status']=='needs_input'
    assert j['status']=='completed'


def test_web_whitespace_match_is_original_not_paraphrase():
    src={'id':'S1','selected':True,'status':'retrieved','text':'The study\n found   an association.','pages':[]}
    notes={'gaps':[],'evidence':[{'source_id':'S1','quote':'The study found an association.','claim':'association'}]}
    actual=research.validate_spans(notes,[src])
    assert actual['evidence'][0]['quote']==src['text']
    assert actual['evidence'][0]['offset']==0
    actual=research.validate_spans({'gaps':[],'evidence':[{'source_id':'S1','quote':'The study proved causality.','claim':'causal'}]},[src])
    assert not actual['evidence']


def paused_article(client):
    a=new(client);j=store.create_job(a['id'],{'stage':'outline','revision':a['revision'],'chain':False})
    store.update_job(j['id'],status='needs_input',stage='outline')
    return store.save_article(a['id'],a['revision'],lambda v:v.update(research={'stage':'outline','pending':True,'stale':False,'job_id':j['id'],'gaps':['缺少核心依据'],'conflicts':[]},stages={**v['stages'],'outline':'needs_input'}),'fixture')


def act_issue(client,a,action,action_id='one'):
    return client.post('/api/articles/'+a['id']+'/research/issues/actions',headers=H,json={
        'revision':a['revision'],'issue_ids':[a['research']['issues'][0]['id']],'action':action,'action_id':action_id})


def test_waive_undo_staleness_and_nonmaterial_preferences(client):
    a=paused_article(client)
    r=act_issue(client,a,'waive');assert r.status_code==200,r.text
    a=r.json()['article'];assert a['workflow']['outline']['allowed'] and not a['research']['pending']
    assert a['research']['issues'][0]['status']=='waived'
    a=patch(client,a,{'auto':{**a['auto'],'layout':True}},'preferences')
    assert a['research']['issues'][0]['status']=='waived' and not a['research']['stale']
    r=act_issue(client,a,'undo');a=r.json()['article'];assert not a['workflow']['outline']['allowed']
    a=act_issue(client,a,'waive').json()['article']
    a=patch(client,a,{'brief':{**a['brief'],'purpose':'新的写作目标'}},'setup')
    assert a['research']['stale'] and a['research']['issues'][0]['status']=='open'
    assert act_issue(client,a,'waive').status_code==400


def test_attachment_keeps_issue_pending_and_links_new_material(client):
    a=paused_article(client);a=act_issue(client,a,'attach').json()['article']
    a=client.post('/api/articles/'+a['id']+'/sources/text',headers=H,json={'revision':a['revision'],'text':'待核实的补充资料'}).json()
    assert a['sources'][0]['issue_ids']==[a['research']['issues'][0]['id']]
    assert a['research']['pending'] and a['research']['stale']


def test_resume_is_idempotent_and_preserves_manual_mode(client,model):
    a=paused_article(client);parent=a['research']['job_id'];a=act_issue(client,a,'waive').json()['article']
    body={'stage':'outline','revision':a['revision'],'resume_job_id':parent,'chain':False}
    first=client.post('/api/articles/'+a['id']+'/jobs',headers=H,json=body)
    second=client.post('/api/articles/'+a['id']+'/jobs',headers=H,json=body)
    assert first.status_code==second.status_code==200
    assert first.json()['id']==second.json()['id']
    from tests.test_studio import wait
    assert wait(client,first.json())['status']=='completed'
    a=client.get('/api/articles/'+a['id']).json()
    assert a['outline']['sections'] and not a['content']


def test_limitation_does_not_block_or_count_as_verified(client):
    a=new(client)
    a=store.save_article(a['id'],a['revision'],lambda v:v.update(research={'pending':False,'stale':False,'gaps':[],'conflicts':['样本较小，不能泛化']}),'fixture')
    assert a['workflow']['outline']['allowed']
    assert a['research']['issues'][0]['kind']=='limitation'
    assert a['research']['issues'][0]['status']=='open'


def test_new_success_not_relabelled_due_to_limitations():
    j={'status':'completed','result':None,'research':{'stats':{'version':1},'notes':{'conflicts':['limit']}}}
    assert flow_state.job_view(j)['status']=='completed'
