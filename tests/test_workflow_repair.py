import asyncio
import pytest
from backend import store,workflow,research,flow_state
from tests.test_studio import client,model,new,patch,run,H


def test_outline_uses_existing_material_without_restarting_research(client,model,monkeypatch):
    a=new(client)
    assert client.post('/api/articles/'+a['id']+'/confirm/outline',headers=H,json={'revision':a['revision']}).status_code==400
    async def unexpected(*args):raise AssertionError('Outline must not restart research')
    monkeypatch.setattr(research,'gather',unexpected)
    j=run(client,a,'outline',chain=False)
    assert j['status']=='completed'
    a=client.get('/api/articles/'+a['id']).json()
    assert a['outline']['sections'] and a['workflow']['write']['allowed']


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
    actual=research.validate_spans({'gaps':[],'evidence':[{'source_id':'S1','quote':'The study found anassociation.','claim':'different words'}]},[src])
    assert not actual['evidence']


def paused_article(client):
    a=new(client);j=store.create_job(a['id'],{'stage':'outline','revision':a['revision'],'chain':False})
    store.update_job(j['id'],status='needs_input',stage='outline')
    return store.save_article(a['id'],a['revision'],lambda v:v.update(research={'stage':'outline','pending':True,'stale':False,'job_id':j['id'],'gaps':['缺少核心依据'],'conflicts':[]},stages={**v['stages'],'outline':'needs_input'}),'fixture')


def act_issue(client,a,action,action_id='one'):
    return client.post('/api/articles/'+a['id']+'/research/issues/actions',headers=H,json={
        'revision':a['revision'],'issue_ids':[a['research']['issues'][0]['id']],'action':action,'action_id':action_id,'wording':'仅讨论已提供的条件，不给出未核实数字'})


def test_waive_undo_staleness_and_nonmaterial_preferences(client):
    a=paused_article(client)
    r=act_issue(client,a,'waive');assert r.status_code==200,r.text
    a=r.json()['article'];assert a['workflow']['outline']['allowed'] and not a['research']['pending']
    assert a['research']['issues'][0]['status']=='bounded'
    a=patch(client,a,{'auto':{**a['auto'],'layout':True}},'preferences')
    assert a['research']['issues'][0]['status']=='bounded' and not a['research']['stale']
    r=act_issue(client,a,'undo');a=r.json()['article'];assert a['workflow']['outline']['allowed'] and a['research']['issues'][0]['status']=='open'
    a=act_issue(client,a,'waive').json()['article']
    a=patch(client,a,{'brief':{**a['brief'],'purpose':'新的写作目标'}},'setup')
    assert a['research']['stale'] and a['research']['issues'][0]['status']=='stale'
    assert a['research_decisions']


def test_attachment_keeps_issue_pending_and_links_new_material(client):
    a=paused_article(client);a=act_issue(client,a,'attach').json()['article']
    a=client.post('/api/articles/'+a['id']+'/sources/text',headers=H,json={'revision':a['revision'],'text':'待核实的补充资料','issue_ids':[a['research']['issues'][0]['id']]}).json()
    assert a['sources'][0]['issue_ids']==[a['research']['issues'][0]['id']]
    assert a['research']['pending'] and not a['research']['stale'] and a['research']['unassessed_source_ids']


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


def test_selective_verification_cannot_silently_drop_other_blockers(client):
    a=paused_article(client)
    j=store.create_job(a['id'],{'stage':'research','issue_ids':[a['research']['issues'][0]['id']]})
    w=research.Research(a,j['id'],'research')
    w.notes={'summary':'model omitted issue','issues':[],'evidence':[],'gaps':[],'conflicts':[]}
    assert not w.sufficient()
    old=a['research']['issues'][0]
    w.notes['issues']=[dict(old,status='resolved',resolution='claimed success',source_ids=['S1'])]
    assert not w.sufficient()  # No located original evidence.
    w.notes['issues'][0]['claim']='范围已明确'
    w.notes['evidence']=[{'source_id':'S1','claim':'范围已明确','quality':'suitable','verification':'quote_matched','source_type':'original','adoption_reason':'direct','use_scope':'study'}]
    from tests.quality_fixtures import assessment
    w.notes['evidence'][0].update(assessment())
    assert w.sufficient()


def test_statistics_keep_previous_stage_and_count_existing_only(client):
    a=new(client);j=store.create_job(a['id'],{'stage':'research'})
    store.update_job(j['id'],research={'stats':{'version':1,'search_requests':3,'page_attempts':4},'calls':5,'pages':4})
    w=research.Research(a,j['id'],'sources')
    assert w.stats['search_requests']==3 and w.stats['page_attempts']==4
    assert w.stats['metadata_requests']==0 and w.stats['existing_checked']==0


def test_verify_action_is_idempotent_and_cancel_preserves_article(client,model,monkeypatch):
    async def waiting(*args): await asyncio.sleep(30)
    monkeypatch.setattr(research,'gather',waiting)
    a=paused_article(client)
    first=act_issue(client,a,'verify','same-click');second=act_issue(client,a,'verify','same-click')
    assert first.status_code==second.status_code==200
    assert first.json()['job']['id']==second.json()['job']['id']
    jid=first.json()['job']['id']
    client.post('/api/jobs/'+jid+'/cancel',headers=H)
    from tests.test_studio import wait
    assert wait(client,first.json()['job'])['status']=='cancelled'
    assert store.get_article(a['id'])['revision']==a['revision']


def test_single_structured_result_accepts_preamble_but_not_ambiguity():
    import json
    value=json.dumps({'topics':[{'title':'示例选题','angle':'角度','reason':'原因'}]})
    assert workflow.parse('topic','Model output follows:\n```json\n'+value+'\n```')['topics'][0]['title']=='示例选题'
    with pytest.raises(ValueError): workflow.parse('topic',value+'\n'+value)
    with pytest.raises(ValueError): workflow.parse('topic',value[:-3])
    with pytest.raises(ValueError): workflow.parse('topic','{"unrelated":"object"}')


def test_bounded_continue_resumes_original_auto_chain(client,model):
    a=paused_article(client);jid=a['research']['job_id']
    store.update_job(jid,request={**store.job(jid)['request'],'chain':True})
    a=patch(client,a,{'auto':{**a['auto'],'outline':True,'write':False}},'preferences')
    result=act_issue(client,a,'waive');assert result.status_code==200,result.text
    from tests.test_studio import wait
    assert wait(client,result.json()['job'])['status']=='completed'
    a=store.get_article(a['id'])
    assert a['outline']['sections'] and a['content'] and not a['review']


def test_continuation_cannot_use_another_article(client,model):
    first=paused_article(client);second=new(client)
    r=client.post('/api/articles/'+second['id']+'/jobs',headers=H,json={'revision':second['revision'],'stage':'research','continuation_job_id':first['research']['job_id']})
    assert r.status_code==400


def test_scope_and_evidence_share_intent_without_second_classifier(client,monkeypatch):
    a=new(client);j=store.create_job(a['id'],{'stage':'sources'})
    w=research.Research(a,j['id'],'sources')
    w.notes={'summary':'资料已读','gaps':[],'conflicts':[],
        'evidence':[{'source_id':'S1','claim':'核对来源有帮助'}],
        'issues':[dict(id='L1',text='没有核对顺序最优的研究',kind='limitation',status='open',source_ids=[],claim='')]}
    assert not w.sufficient()  # A background claim alone no longer establishes coverage.
    w.coverage=[dict(question_id='Q1',required=True,status='supported',evidence_ids=['E1'])]
    assert w.sufficient() and w.issues()[0]['status']=='open'
    w.notes['evidence']=[];w.notes['gaps']=['没有任何可定位依据']
    assert not w.sufficient()
