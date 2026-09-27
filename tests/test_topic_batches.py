"""Synthetic batch history, adoption and same-task duplicate repair."""
import copy
import json
import pytest
from backend import agent_transport, creative, native_runtime, providers, store, workflow
from backend.service_errors import ServiceFailure
from tests.test_studio import H, client, model, new, run


def rows(prefix, count=10):
    return [dict(title=f'{prefix} {i}', angle=f'Angle {i}', reason='Synthetic reason', source_ids=[]) for i in range(count)]


def batch(a, prefix):
    return store.save_article(a['id'], a['revision'], lambda v: creative.candidates(v, rows(prefix), prefix), 'Synthetic batch')


def test_all_batches_survive_and_context_only_contains_recent_three(client):
    a = new(client, topic='')
    for i in range(7):
        a = batch(a, f'Batch {i}')
    history = copy.deepcopy(a['creative_intent']['batches'])
    assert len(history) == 7
    assert a['topics'] == history[-1]['topics']
    ctx = creative.context(a)
    assert ctx['batches'] == history[-3:]
    ctx['batches'][0]['topics'][0]['title'] = 'Mutated copy'
    assert store.get_article(a['id'])['creative_intent']['batches'] == history


def test_legacy_candidates_become_first_batch_without_changing_ids(client):
    a = new(client, topic='')
    legacy = [dict(x, id=f'legacy-{i}') for i, x in enumerate(rows('Legacy'))]
    def old(v):
        v['topics'] = copy.deepcopy(legacy)
        v.pop('creative_intent', None)
    a = store.save_article(a['id'], a['revision'], old, 'Synthetic legacy article')
    assert creative.context(a)['batches'][0]['topics'] == legacy
    a = batch(a, 'New')
    assert len(a['creative_intent']['batches']) == 2
    assert a['creative_intent']['batches'][0]['topics'] == legacy
    assert a['topics'] == a['creative_intent']['batches'][1]['topics']


def test_adopt_old_batch_uses_id_and_preserves_latest_and_history(client):
    a = new(client, topic='')
    a = batch(a, 'Original')
    candidate = copy.deepcopy(a['topics'][0])
    for i in range(5):
        a = batch(a, f'New {i}')
    a = store.save_article(a['id'], a['revision'], lambda v: creative.candidates(v, [dict(candidate, angle='Different plan with the same title')]), 'Synthetic duplicate archive')
    before = copy.deepcopy(a)
    result = client.post('/api/articles/'+a['id']+'/topic', headers=H,
                         json=dict(revision=a['revision'], title='Untrusted label', topic_id=candidate['id']))
    assert result.status_code == 200, result.text
    a = result.json()
    assert a['creative_intent']['selected'] == candidate
    assert a['creative_intent']['adopted_plan'] == candidate
    assert a['brief']['topic'] == candidate['title']
    assert a['topics'] == before['topics']
    assert a['creative_intent']['batches'] == before['creative_intent']['batches']
    assert creative.context(a)['selected'] == candidate
    assert len(creative.context(a)['batches']) == 3
    other = batch(new(client, topic=''), 'Other article')
    rejected = client.post('/api/articles/'+other['id']+'/topic', headers=H,
                           json=dict(revision=other['revision'], title=candidate['title'], topic_id=candidate['id']))
    assert rejected.status_code == 400
    assert store.get_article(other['id'])['revision'] == other['revision']


@pytest.mark.parametrize('titles', [
    ['Alpha Method', 'Beta Method'],
    ['Beta Method', 'Alpha Method'],
    ['ＡＬＰＨＡ　ＭＥＴＨＯＤ！', 'beta\nmethod?'],
])
def test_duplicate_batch_cannot_pass_by_changing_ids_order_or_punctuation(client, titles):
    a = new(client, topic='')
    def seed(v):
        creative.candidates(v, [dict(title=t, angle='Old angle', reason='Old reason') for t in ['Alpha Method', 'Beta Method']])
    a = store.save_article(a['id'], a['revision'], seed, 'Synthetic batch')
    result = dict(topics=[dict(id=f'new-{i}', title=t, angle='New explanation', reason='Different reason') for i, t in enumerate(titles)])
    with pytest.raises(ValueError, match='最近三批.*重复'):
        workflow.validate_result('topic', result, a)
    assert store.get_article(a['id']) == a


def test_new_title_and_topics_outside_recent_window_remain_allowed(client):
    a = new(client, topic='')
    for i in range(4):
        a = batch(a, f'Batch {i}')
    workflow.validate_result('topic', dict(topics=rows('Batch 0')), a)
    workflow.validate_result('topic', dict(topics=[*rows('Batch 3'), *rows('New')]), a)


@pytest.mark.anyio
async def test_native_request_uses_bounded_history_without_discarding_archive(client):
    a = new(client, topic='')
    for i in range(5):
        a = batch(a, f'Batch {i}')
    request = dict(stage='topic', instruction='Explore new questions', revision=a['revision'], chain=False)
    job = store.create_job(a['id'], request)
    session = native_runtime.Session(a, job['id'], 'topic', request)
    await session.prepare()
    saved = json.loads((session.home/'request.json').read_text('utf-8'))
    assert saved['creative_intent']['batches'] == a['creative_intent']['batches'][-3:]
    assert saved['instruction'] == request['instruction']
    assert len(store.get_article(a['id'])['creative_intent']['batches']) == 5


@pytest.mark.parametrize('protocol', ['chat', 'responses', 'anthropic'])
@pytest.mark.parametrize('fail_after_rejection', [False, True])
def test_duplicate_finish_repairs_in_same_job_or_preserves_history(client, model, monkeypatch, protocol, fail_after_rejection):
    a = new(client, topic='')
    assert run(client, a, 'topic')['status'] == 'needs_input'
    a = store.get_article(a['id'])
    previous = copy.deepcopy(a)
    service_for = providers.service_for
    monkeypatch.setattr(providers, 'service_for', lambda stage: dict(service_for(stage), protocol=protocol))
    turns = []

    async def turn(service, system, messages, tools):
        index = len(turns)
        turns.append(copy.deepcopy(messages))
        assert store.get_article(a['id']) == previous
        task = json.loads(messages[0]['content'])
        if index:
            assert index == 1
            feedback = json.dumps(messages[-1], ensure_ascii=False)
            assert '最近三批' in feedback and '重复' in feedback
            if fail_after_rejection:
                raise ServiceFailure('Synthetic unavailable service', category='service_error')
            candidates = rows('Actually new')
        else:
            candidates = [dict(x, id=f'new-{i}', reason='Changed description') for i, x in enumerate(reversed(previous['topics']))]
        calls = [dict(id=f'w{index}', name='Write', arguments=json.dumps(dict(path=task['run_dir']+'/topics.yaml', content=json.dumps(dict(topics=candidates))))),
                 dict(id=f'f{index}', name='Finish', arguments='{}')]
        if protocol == 'chat':
            wire = [dict(role='assistant', content=None, tool_calls=[dict(id=c['id'], type='function', function=dict(name=c['name'], arguments=c['arguments'])) for c in calls])]
        elif protocol == 'responses':
            wire = [dict(type='function_call', call_id=c['id'], name=c['name'], arguments=c['arguments']) for c in calls]
        else:
            wire = [dict(role='assistant', content=[dict(type='tool_use', id=c['id'], name=c['name'], input=json.loads(c['arguments'])) for c in calls])]
        return dict(wire=wire, calls=calls, text='', usage=dict(status='completed', estimated_cost=None))

    monkeypatch.setattr(agent_transport, 'turn', turn)
    job = run(client, a, 'topic', instruction='A new batch')
    assert len(turns) == 2
    current = client.get('/api/articles/'+a['id']).json()
    if fail_after_rejection:
        assert job['status'] == 'failed'
        assert current == previous
    else:
        assert job['status'] == 'needs_input', job['message']
        assert len(current['creative_intent']['batches']) == 2
        assert current['creative_intent']['batches'][0] == previous['creative_intent']['batches'][0]
        assert all(x['title'].startswith('Actually new') for x in current['topics'])
        assert current['creative_intent']['batches'][-1]['feedback'] == 'A new batch'
