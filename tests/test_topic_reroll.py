"""Synthetic rerolls exercise real artifacts, tool correction and article commits."""
import copy
import json
import pytest
from backend import agent_transport, native_projection, providers, store
from backend.service_errors import ServiceFailure
from tests.test_studio import client, model, new, patch, run


BROKEN = "topics:\n  - title: 'A 'quoted' question'\n    angle: Synthetic angle\n    reason: Synthetic reason\n"


@pytest.mark.parametrize('content', [BROKEN, 'topics:\n\t- title: Question', 'topics: !unknown []'])
def test_invalid_topic_file_reports_repairable_error_and_preserves_file(tmp_path, content):
    path = tmp_path / 'topics.yaml'
    path.write_text(content, encoding='utf-8')
    with pytest.raises(ValueError, match=r'topics\.yaml.*YAML.*第 \d+ 行.*第 \d+ 列'):
        native_projection.project('topic', tmp_path, {})
    assert path.read_text('utf-8') == content


def test_json_topic_artifact_preserves_quotes_and_newlines(tmp_path):
    row = dict(title='Why "ready" is not \'recovered\': a question', angle='Line one\nLine two', reason='Synthetic reason')
    (tmp_path / 'topics.yaml').write_text(json.dumps(dict(topics=[row])), encoding='utf-8')
    result = native_projection.project('topic', tmp_path, {})
    assert all(result['topics'][0][key] == value for key, value in row.items())


@pytest.mark.parametrize('protocol', ['chat', 'responses', 'anthropic'])
def test_reroll_repairs_malformed_artifact_before_replacing_previous_batch(client, model, monkeypatch, protocol):
    a = new(client, topic='')
    assert run(client, a, 'topic')['status'] == 'needs_input'
    a = store.get_article(a['id'])
    previous = copy.deepcopy(a['topics'])
    a = patch(client, a, {'input_drafts': {'topic_feedback': 'Explore a different angle'}})
    fixture_turn = agent_transport.turn
    service_for = providers.service_for
    monkeypatch.setattr(providers, 'service_for', lambda stage: dict(service_for(stage), protocol=protocol))
    turns = []
    expected = dict(title='A "new" question: reader\'s perspective', angle='Different angle', reason='Synthetic reason')

    async def turn(service, system, messages, tools):
        index = len(turns)
        turns.append(copy.deepcopy(messages))
        task = json.loads(messages[0]['content'])
        assert store.get_article(a['id'])['topics'] == previous
        if index == 0:
            content = BROKEN
        else:
            assert index == 1, 'A repaired artifact must finish without another model request'
            feedback = json.dumps(messages[-1], ensure_ascii=False)
            assert 'topics.yaml' in feedback and 'YAML' in feedback and '第 2 行' in feedback
            content = json.dumps(dict(topics=[expected]))
        calls = [dict(id=f'w{index}', name='Write', arguments=json.dumps(dict(path=task['run_dir']+'/topics.yaml', content=content))),
                 dict(id=f'f{index}', name='Finish', arguments='{}')]
        if protocol == 'chat':
            wire = [dict(role='assistant', content=None, tool_calls=[dict(id=c['id'], type='function', function=dict(name=c['name'], arguments=c['arguments'])) for c in calls])]
        elif protocol == 'responses':
            wire = [dict(type='function_call', call_id=c['id'], name=c['name'], arguments=c['arguments']) for c in calls]
        else:
            wire = [dict(role='assistant', content=[dict(type='tool_use', id=c['id'], name=c['name'], input=json.loads(c['arguments'])) for c in calls])]
        return dict(wire=wire, calls=calls, text='', usage=dict(status='completed', estimated_cost=None))

    monkeypatch.setattr(agent_transport, 'turn', turn)
    job = run(client, a, 'topic', instruction='Explore a different angle')
    assert job['status'] == 'needs_input', job['message']
    assert len(turns) == 2
    a = client.get('/api/articles/'+a['id']).json()
    assert len(a['topics']) == 1 and a['topics'][0]['title'] == expected['title']
    assert a['creative_intent']['batches'][-2]['topics'] == previous
    assert a['creative_intent']['batches'][-1]['feedback'] == 'Explore a different angle'
    assert not a['brief']['topic'] and not a['content']
    # A third batch still replaces the visible list and remains available for adoption.
    monkeypatch.setattr(agent_transport, 'turn', fixture_turn)
    monkeypatch.setattr(providers, 'service_for', service_for)
    assert run(client, a, 'topic')['status'] == 'needs_input'
    final = client.get('/api/articles/'+a['id']).json()
    assert len(final['topics']) == 10 and len(final['creative_intent']['batches']) == 3


def test_failed_reroll_keeps_previous_candidates(client, model, monkeypatch):
    a = new(client, topic='')
    assert run(client, a, 'topic')['status'] == 'needs_input'
    previous = store.get_article(a['id'])

    async def failed(*args):
        raise ServiceFailure('Synthetic unavailable service', category='service_error')

    monkeypatch.setattr(agent_transport, 'turn', failed)
    assert run(client, previous, 'topic')['status'] == 'failed'
    current = client.get('/api/articles/'+a['id']).json()
    assert current['topics'] == previous['topics']
    assert current['creative_intent'] == previous['creative_intent']
    assert current['revision'] == previous['revision']
