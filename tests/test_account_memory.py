"""Representative account-memory boundaries. All model and HTTP traffic is mocked."""
import asyncio
import copy
import hashlib
import json
import sqlite3
from datetime import datetime, timedelta, timezone
import pytest
from backend import account_memory as memory, store, editorial, workflow, providers, research, snapshots
from backend.models import JobRequest, STAGES
from tests.test_studio import client, model, new, patch, run, wait, H


def rule(column='运动科学', **extra):
    return dict(id=store.uid(), category='rhythm', text='长短段落交替', column=column, scope='column', status='soft',
                created=store.now(), updated=store.now(), sources=[dict(id='pair', article_id='source', base_id='ai', final_id='human')], **extra)


def seeded_rule(**extra):
    item = rule(**extra)
    memory.change(memory.get()['revision'], lambda v: v['rules'].append(item), 'fixture')
    return item


def human_pair(c):
    a = new(c)
    def seed(v):
        v['content'] = 'AI原稿。较长的一段。'; editorial.record_draft(v, 'initial', v['content'], origin='ai')
    a = store.save_article(a['id'], a['revision'], seed, 'fixture')
    a = patch(c, a, dict(content='人工改稿。\n\n短段落。'), 'write')
    return c.post('/api/articles/'+a['id']+'/drafts/final', headers=H, json=dict(revision=a['revision'])).json()


def mock_style(monkeypatch):
    calls=[]
    async def generate(service, system, prompt, emit=None):
        calls.append(json.loads(prompt))
        return json.dumps(dict(rules=[dict(category='rhythm', text='长短段落交替')])), dict(status='completed', model='mock')
    monkeypatch.setattr(providers, 'generate', generate)
    monkeypatch.setattr(providers, 'service_for', lambda stage: dict(model='mock', name='mock', route=stage))
    return calls


def test_migration_backup_integrity_and_old_bytes_unchanged(tmp_path, monkeypatch):
    old = tmp_path/'legacy'; old.mkdir(); monkeypatch.setattr(store, 'DATA', old)
    a = dict(id='old', revision=7, created=store.now(), updated=store.now(), title='旧文', brief=dict(column='栏目', topic='主题'),
             content='人工正文[S77]', research_decisions={'old': 'keep'}, sources=[dict(id='S77')])
    raw = json.dumps(a)
    with sqlite3.connect(old/'studio.sqlite') as db:
        db.execute('CREATE TABLE articles(id TEXT PRIMARY KEY,data TEXT)'); db.execute('INSERT INTO articles VALUES(?,?)', ('old', raw))
    store.init()
    with store.connection() as db: assert db.execute('SELECT data FROM articles').fetchone()[0] == raw
    assert memory.history()['items'][0]['topic'] == '主题'
    backup=old/'backups/before-quality-account-v1.sqlite'
    with sqlite3.connect(backup) as db:
        assert db.execute('SELECT data FROM articles').fetchone()[0] == raw
        assert not db.execute("SELECT 1 FROM sqlite_master WHERE name='account_memory'").fetchone()
    backup.write_bytes(b'bad'); snapshots._ready.discard((str(old.resolve()), 'quality-account-v1'))
    with pytest.raises(ValueError, match='校验失败'): store.init()


def test_account_conflict_and_explicit_undo(client):
    a=client.patch('/api/account/profile',headers=H,json=dict(revision=0,profile=dict(audience='通勤读者')))
    assert a.status_code==200
    assert client.patch('/api/account/profile',headers=H,json=dict(revision=0,profile=dict(audience='旧页面'))).status_code==409
    result=client.post('/api/account/undo',headers=H,json=dict(revision=1)).json()
    assert result['revision']==2 and result['profile']['audience']==''


def test_complete_history_index_and_recent_priorities(client):
    for i in range(105): store.create_article(dict(topic='相同主题',column='栏目'+str(i%2)))
    a=store.create_article(dict(topic='相同主题',column='栏目0'))
    assert memory.history()['total']==106 and len(memory.history(page=4)['items'])==16
    a=patch(client,a,dict(history_fields=dict(topic='相同主题',angle='新证据',reader_question='条件改变了吗',takeaway='仍待核实')))
    rows=memory.history(query='新证据')['items']; assert rows[0]['reader_question']=='条件改变了吗'
    ctx=memory.context(a); assert ctx['history_total']==105 and ctx['history_omitted']>=5
    assert sum(len(store.encode(h)) for h in ctx['history'])<=18000
    assert ctx['history'][0]['recency']=='近7天' and '不按题名禁止' in ctx['policy']
    trashed=store.trash_article(a['id'],a['revision']); assert memory.history(query='新证据')['items'][0]['status']=='trash'
    restored=store.trash_article(a['id'],trashed['revision'],True); assert memory.history(query='新证据')['items'][0]['status']=='draft'
    trashed=store.trash_article(a['id'],restored['revision']);store.purge_article(a['id'],trashed['revision'])
    assert not memory.history(query='新证据')['items']


def test_only_real_human_pairs_learn_once_and_keep_column(client,monkeypatch):
    calls=mock_style(monkeypatch); a=human_pair(client); pair=memory.pairs(a)[0]
    response=client.post('/api/account/jobs',headers=H,json=dict(kind='learn',revision=0,article_id=a['id'],pair_id=pair['id']))
    assert response.status_code==200,response.text
    assert wait(client,response.json())['status']=='completed'
    value=memory.get(); r=value['rules'][0]
    assert r['status']=='soft' and r['scope']=='column' and len(r['sources'])==1
    assert calls[0]['context']['ai']!=calls[0]['context']['human']
    assert client.post('/api/account/jobs',headers=H,json=dict(kind='learn',revision=1,article_id=a['id'],pair_id=pair['id'])).status_code==400
    assert memory.context(a)['rules']
    assert not memory.context({**a,'brief':{**a['brief'],'column':'另一栏目'}})['rules']
    # Clicking final without changing AI text, or accepting AI edits, is not a pair.
    plain=new(client)
    def seed(v):
        v['content']='AI稿';editorial.record_draft(v,'edited','AI稿',origin='ai')
    plain=store.save_article(plain['id'],plain['revision'],seed,'AI')
    plain=client.post('/api/articles/'+plain['id']+'/drafts/final',headers=H,json=dict(revision=plain['revision'])).json()
    assert not memory.pairs(plain)
    fake=copy.deepcopy(a); fake['draft_versions'][0]['origin']='human'; assert not memory.pairs(fake)
    same=copy.deepcopy(a); same['draft_versions'][-1]['content']=same['draft_versions'][0]['content']; assert not memory.pairs(same)


def test_rule_confirm_expand_edit_disable_delete_undo_and_decay(client):
    r=seeded_rule();a=new(client,column='另一栏目')
    with pytest.raises(ValueError): memory.item_action(1,'rules',r['id'],'expand')
    memory.item_action(1,'rules',r['id'],'confirm');memory.item_action(2,'rules',r['id'],'expand')
    assert memory.context(a)['rules'][0]['weight']==1
    memory.item_action(3,'rules',r['id'],'edit',dict(category='expression',text='直接进入问题'))
    assert not memory.context(a)['rules'] and memory.get()['rules'][0]['status']=='soft'
    a['brief']['column']='运动科学'
    memory.change(4,lambda v:v['rules'][0].update(updated=(datetime.now(timezone.utc)-timedelta(days=90)).isoformat()),'age')
    assert .49<=memory.context(a)['rules'][0]['weight']<=.5
    memory.item_action(5,'rules',r['id'],'disable');assert not memory.context(a)['rules']
    memory.item_action(6,'rules',r['id'],'delete');assert not memory.get()['rules']
    memory.undo(7);assert memory.get()['rules'][0]['status']=='disabled'


def test_article_restore_does_not_restore_revoked_preferences_or_erase_use_records(client):
    r=seeded_rule();a=new(client);j=store.create_job(a['id'],dict(stage='write'))
    used=memory.capture(a,j['id'],'write');store.update_job(j['id'],status='completed')
    a=patch(client,a,dict(content='人工正文'),'write');version=store.versions(a['id'])[0]
    memory.item_action(1,'rules',r['id'],'revoke')
    store.restore(a['id'],version['id'],a['revision'])
    assert not memory.context(a)['rules'] and memory.uses(a['id'])[0]['id']==used['id']


def test_example_only_abstract_style_reaches_generation(client,monkeypatch):
    mock_style(monkeypatch);a=new(client)
    j=client.post('/api/account/jobs',headers=H,json=dict(kind='example',revision=0,column='运动科学',title='某人的范文',text='我在火星遇见王博士，他给我99颗宝石。')).json()
    assert wait(client,j)['status']=='completed'
    ex=memory.get()['examples'][0]; assert not memory.context(a)['examples']
    memory.item_action(1,'examples',ex['id'],'confirm')
    ctx=memory.context(a);serialized=store.encode(ctx)
    assert ctx['examples'][0]['rules'][0]['text']=='长短段落交替'
    assert '火星' not in serialized and '王博士' not in serialized and '99' not in serialized
    other={**a,'brief':{**a['brief'],'column':'AI'}};assert not memory.context(other)['examples']
    memory.item_action(2,'examples',ex['id'],'revoke');assert not memory.context(a)['examples']


def metric(a,reads=10,days=1):
    return dict(article_id=a['id'],published_at='2025-01-01T00:00:00+00:00',observed_at=f'2025-01-{1+days:02d}T00:00:00+00:00',reads=reads)


def test_metrics_comparable_windows_missing_and_unique_articles(client):
    articles=[new(client) for _ in range(6)]
    value=memory.add_metrics(0,[metric(a) for a in articles[:4]])
    assert not memory.trends(value)[0]['metrics']
    value=memory.add_metrics(1,[metric(articles[4],days=2),metric(articles[5],reads=None)|dict(likes=20)])
    assert not any(t['metrics'] for t in memory.trends(value))
    value=memory.add_metrics(2,[metric(articles[4])])
    result=memory.trends(value)[0]
    assert result['metrics']['reads']['n']==5 and result['metrics']['reads']['mean']==10
    assert 'likes' not in result['metrics'] and '不' in result['note']
    # Another publication/observation for one article cannot inflate sample size.
    value=memory.add_metrics(3,[metric(articles[0])|dict(published_at='2025-02-01T00:00:00Z',observed_at='2025-02-02T00:00:00Z',reads=20)])
    assert memory.trends(value)[0]['metrics']['reads']['n']==5


@pytest.mark.parametrize('bad',[dict(reads=-1),dict(reads='NaN'),dict(observed_at='2024-01-01'),dict(observed_at='2025-01-02T00:01:00Z'),dict(article_id='missing')])
def test_metric_batch_validation_is_atomic(client,bad):
    a,b=new(client),new(client)
    with pytest.raises((ValueError,KeyError)):memory.add_metrics(0,[metric(a),metric(b)|bad])
    assert memory.get()['revision']==0 and memory.get()['metrics']==[]


def test_csv_import_reuses_jobs_and_keeps_unknown_missing(client):
    a=new(client);csv='article_id,published_at,observed_at,reads,likes\n'+a['id']+',2025-01-01,2025-01-02,10,\n'
    j=client.post('/api/account/import',headers=H,data=dict(kind='metrics_csv',revision=0),files={'file':('records.csv',csv.encode(),'text/csv')})
    assert j.status_code==200,j.text
    assert wait(client,j.json())['status']=='completed'
    assert memory.get()['metrics'][0]['likes'] is None
    with pytest.raises(ValueError):memory.add_metrics(1,memory.csv_rows(csv.encode()))
    assert memory.get()['revision']==1


@pytest.mark.parametrize('stage',['topic','outline','write','revise'])
def test_revocation_during_generation_retains_candidate_and_blocks_apply(client,monkeypatch,stage):
    seeded_rule();a=new(client);a=patch(client,a,dict(content='人工原文'),'write')
    async def gather(a,*args):return a,False
    async def synthesize(a,*args):return a
    monkeypatch.setattr(research,'gather',gather);monkeypatch.setattr(editorial,'synthesize',synthesize)
    monkeypatch.setattr(workflow,'prerequisites',lambda *args:None)
    monkeypatch.setattr(providers,'service_for',lambda *args:dict(model='mock',name='mock'))
    async def generate(service,system,prompt,emit=None):
        assert json.loads(prompt)['资料与当前内容']['account_reference']['rules']
        memory.item_action(1,'rules',memory.get()['rules'][0]['id'],'revoke')
        result={'topic':dict(topics=[dict(id='t',title='相同主题的新角度',angle='新证据',reason='新问题')]),
                'outline':dict(thesis='新判断',reader_question='新问题',takeaway='新结论',sections=[dict(id='s',title='结构',purpose='解释')]),
                'write':'旧参考生成的新稿','revise':dict(replacement='旧参考的选段',explanation='修改')}[stage]
        return json.dumps(result,ensure_ascii=False) if isinstance(result,dict) else result,dict(status='completed')
    monkeypatch.setattr(providers,'generate',generate)
    j=store.create_job(a['id'],JobRequest(stage=stage,revision=a['revision'],chain=True).model_dump());asyncio.run(workflow.run(j['id']))
    end=store.job(j['id']);assert end['status']=='needs_input' and end['account_candidate'] and end['result']
    assert store.get_article(a['id'])['content']=='人工原文' and not memory.context(a)['rules']


def test_account_change_between_response_and_save_cannot_win_race(client):
    a=new(client);j=store.create_job(a['id'],dict(stage='write'));used=memory.capture(a,j['id'],'write')
    memory.change(0,lambda v:v['profile'].update(expression='新要求'),'change')
    with pytest.raises(memory.StaleContext):workflow.apply_result(a,'write','旧参考正文',dict(_account_use=used))
    assert store.get_article(a['id'])['content']==''


def test_stale_whole_edit_is_saved_but_not_audited_or_adopted(client,monkeypatch):
    seeded_rule();a=new(client);a=patch(client,a,dict(content='原正文'),'write')
    mock_style(monkeypatch)
    async def generate(service,system,prompt,emit=None):
        assert json.loads(prompt)['context']['account_reference']['rules']
        memory.item_action(1,'rules',memory.get()['rules'][0]['id'],'revoke')
        return json.dumps(dict(content='旧上下文候选',explanation='结构修改')),dict(status='completed')
    monkeypatch.setattr(providers,'generate',generate)
    async def no_audit(*args):raise AssertionError('Stale candidate must stop here')
    monkeypatch.setattr(editorial,'audit',no_audit)
    j=store.create_job(a['id'],JobRequest(stage='edit',revision=a['revision']).model_dump());asyncio.run(workflow.run(j['id']))
    saved=store.get_article(a['id']);candidate=saved['editorial_candidates'][0]
    assert saved['content']=='原正文' and candidate['content']=='旧上下文候选'
    assert store.job(j['id'])['status']=='needs_input'
    with pytest.raises(memory.StaleContext):editorial.adopt(saved,candidate['id'],automatic=True)


def test_cancelled_learning_never_applies_and_external_failure_usage_unknown(client,monkeypatch):
    a=human_pair(client);mock_style(monkeypatch)
    async def hang(*args):await asyncio.sleep(60)
    monkeypatch.setattr(providers,'generate',hang)
    j=client.post('/api/account/jobs',headers=H,json=dict(kind='learn',revision=0,article_id=a['id'],pair_id=memory.pairs(a)[0]['id'])).json()
    client.post('/api/jobs/'+j['id']+'/cancel',headers=H)
    assert wait(client,j)['status']=='cancelled' and not memory.get()['rules']


def test_failed_learning_retains_unknown_usage_and_no_preference(client,monkeypatch):
    a=human_pair(client);mock_style(monkeypatch)
    async def fail(*args):raise ConnectionError('模拟连接中断')
    monkeypatch.setattr(providers,'generate',fail)
    j=client.post('/api/account/jobs',headers=H,json=dict(kind='learn',revision=0,article_id=a['id'],pair_id=memory.pairs(a)[0]['id'])).json()
    assert wait(client,j)['status']=='failed' and not memory.get()['rules']
    usage=store.usage('__account__')[0];assert usage['status']=='unknown' and usage['estimated_cost'] is None


def test_revoked_rule_is_not_reactivated_by_another_human_pair(client,monkeypatch):
    mock_style(monkeypatch)
    first=human_pair(client)
    def learn(a):
        j=client.post('/api/account/jobs',headers=H,json=dict(kind='learn',revision=memory.get()['revision'],article_id=a['id'],pair_id=memory.pairs(a)[0]['id'])).json()
        assert wait(client,j)['status']=='completed'
    learn(first);r=memory.get()['rules'][0];memory.item_action(1,'rules',r['id'],'revoke')
    learn(human_pair(client));assert len(memory.get()['rules'])==1
    assert memory.get()['rules'][0]['status']=='revoked' and len(memory.get()['rules'][0]['sources'])==2
    assert not memory.context(first)['rules']


def test_full_pipeline_uses_memory_without_polluting_fact_audit(client,model,monkeypatch):
    seeded_rule();seen=[];original=providers.generate
    async def spy(service,system,prompt,emit=None):
        value=json.loads(prompt);schema=value.get('schema',{}).get('title','write')
        ctx=value.get('context',value.get('资料与当前内容',{}));seen.append((schema,ctx))
        return await original(service,system,prompt,emit)
    monkeypatch.setattr(providers,'generate',spy)
    a=new(client,topic='');a=patch(client,a,dict(auto={s:True for s in STAGES}))
    a=client.post('/api/articles/'+a['id']+'/sources/text',headers=H,json=dict(revision=a['revision'],title='模拟材料',text='研究只支持关联。')).json()
    j=run(client,a,'topic');assert j['status']=='completed',j
    a=store.get_article(a['id']);assert a['stages']['layout']=='done'
    assert client.get('/api/articles/'+a['id']+'/export/zip').status_code==200
    for schema in ('TopicsResult','OutlineResult','write'):
        assert any(s==schema and c.get('account_reference',{}).get('rules') for s,c in seen)
    assert any(s=='FactAudit' for s,c in seen)
    assert all('account_reference' not in c for s,c in seen if s in ('FactAudit','ReviewResult'))
    j=run(client,a,'edit',chain=False);assert j['status']=='completed',j
    assert any(s=='EditedDraft' and c.get('account_reference') for s,c in seen)
    assert {'topic','outline','write','edit'} <= {u['stage'] for u in memory.uses(a['id'])}
