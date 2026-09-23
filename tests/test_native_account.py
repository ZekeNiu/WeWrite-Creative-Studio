import asyncio
import json
import yaml
import pytest
from backend import account_memory as memory, native_account, native_runtime, store, rendering
from tests.test_studio import client,new
from tests.test_account_memory import rule


def test_upstream_aggregation_and_materialized_files(client):
    a=new(client);r=rule();r['sources']=[dict(id='one',created=store.now()),dict(id='two',created=store.now())]
    r['native_pattern']=dict(key='rhythm',type='expression',scope='global',scope_value='')
    def seed(v):
        v['rules'].append(r);v['profile'].update(expression='自然语气',direction='读书与思考')
        for i in range(3):
            text='开头真实表达。\n\n转折：不过事情没有这么简单。\n\n结尾留一个问题。'
            v['examples'].append(dict(id='example'+str(i),title='范文'+str(i),source='测试',text=text,column=a['brief']['column'],scope='column',status='confirmed',rules=[],ownership='third_party',created=store.now(),updated=store.now()))
    memory.change(0,seed,'fixture');ctx=memory.context(a)
    assert ctx['rules'][0]['count']==2 and ctx['rules'][0]['confidence']==5.5 and ctx['rules'][0]['hard']
    assert len(ctx['examples'])==2
    job=store.create_job(a['id'],dict(stage='write'));session=native_runtime.Session(a,job['id'],'write',{})
    asyncio.run(session.prepare())
    style=yaml.safe_load((session.home/'style.yaml').read_text('utf-8'))
    assert style['voice']=='自然语气' and style['topics']==['读书与思考']
    summary=json.loads((session.home/'learning-summary.json').read_text('utf-8'))
    assert summary['patterns'][0]['confidence']==ctx['rules'][0]['confidence']
    index=yaml.safe_load((session.home/'exemplars/index.yaml').read_text('utf-8'))
    assert len(index)==2
    for x in index:
        content=(session.home/'exemplars'/x['file']).read_text('utf-8')
        assert '开头真实表达' in content and 'third_party' in content and 'personal_materials_reusable: false' in content
    memory.item_action(1,'rules',r['id'],'revoke')
    assert not native_account.references(memory.get(),a)[2]


def test_learning_cannot_confirm_or_overwrite_pair(client):
    a=new(client);j=store.create_job('__account__',dict(stage='account_memory'))
    s=native_runtime.Session(a,j['id'],'learn',dict(_learning_source=dict(ai='原稿。',human='改稿。')))
    asyncio.run(s.prepare())
    with pytest.raises(ValueError):s.path('account-inputs/human.md',True)
    lesson=yaml.safe_load(s.lesson.read_text('utf-8'))
    lesson['patterns']=[dict(type='tone',key='gentle',description='语气变化',rule='温和表达',scope='global',scope_value='',confirmed=True)]
    s.lesson.write_text(yaml.safe_dump(lesson,allow_unicode=True),'utf-8')
    with pytest.raises(ValueError,match='用户'):native_account.learning_result(s)


def test_paste_safe_keeps_leaf_and_cover_separate(client):
    a=new(client);a['content']='## 标题\n\n正文内容。';a['images']=[dict(id='cover',role='cover',filename='cover.png',selected=True)]
    result=rendering.render(a)
    assert 'leaf=""' in result['body'] and 'cover.png' not in result['markdown']
    assert not [x for x in result['compatibility'] if x['level']=='ERROR']
    assert 'onclick' not in rendering.safe_html('<span leaf="" onclick="alert(1)">安全文本</span>')
