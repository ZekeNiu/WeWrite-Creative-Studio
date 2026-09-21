import asyncio
import json
from types import SimpleNamespace
import pytest
from tools.benchmark_support import identity,manifest_once,Capture


def test_effective_route_inheritance_and_configuration_changes():
    cfg=dict(services=[dict(id='a',model='model-a',protocol='chat',max_tokens=8000,key='private')],default_service='a',
             routes={'sources':dict(service_id='a',model='source-model'),'research':dict(service_id='',model='')},
             search=dict(native_protocol='responses'),model_connections=[])
    value=identity(cfg)
    assert value['routes']['research']['model']=='source-model'
    assert value['routes']['write']['model']=='model-a'
    assert value['routes']['search']['protocol']=='responses'
    assert 'private' not in json.dumps(value)
    cfg['services'][0]['max_tokens']=9000
    assert identity(cfg)['settings_sha256']!=value['settings_sha256']


def test_changed_inputs_cannot_overwrite_completed_records(tmp_path):
    output=tmp_path/'run';manifest_once(output,dict(model='a'))
    (output/'case.json').write_text('original')
    manifest_once(output,dict(model='a'))
    with pytest.raises(ValueError,match='inputs changed'):manifest_once(output,dict(model='b'))
    assert json.loads((output/'manifest.json').read_text())==dict(model='a')
    assert (output/'case.json').read_text()=='original'


def test_capture_preserves_failed_stream_without_changing_behavior(tmp_path):
    async def frames(response):
        yield '{"error":{"message":"synthetic upstream failure"}}'
    async def generate(service,system,prompt,emit):
        await emit('partial')
        async for frame in provider.frames(None):pass
        raise ValueError('stream failed')
    provider=SimpleNamespace(generate=generate,frames=frames)
    capture=Capture(provider,tmp_path);capture.case.set('case');seen=[]
    async def receive(delta):seen.append(delta)
    with pytest.raises(ValueError,match='stream failed'):
        asyncio.run(provider.generate(dict(id='test',secret='private'),'system','prompt',receive))
    result=json.loads((tmp_path/'raw/case/0001.json').read_text())
    assert result['partial']=='partial' and result['status']=='incomplete' and seen==['partial']
    assert 'private' not in json.dumps(result)
    assert 'synthetic upstream failure' in (tmp_path/'raw/case/0001.frames.jsonl').read_text()
