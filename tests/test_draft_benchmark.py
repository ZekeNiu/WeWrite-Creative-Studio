import asyncio
import copy
import pytest
from backend import store,workflow
from tools import draft_quality_benchmark as benchmark
from tests.test_studio import client,model


def test_output_cannot_overlap_production(tmp_path):
    root=tmp_path/'studio'
    for output in (root,root/'data',root/'data'/'run',tmp_path):
        with pytest.raises(ValueError):benchmark.isolated_output(output,root)
    assert benchmark.isolated_output(root/'output'/'comparison',root)==root/'output'/'comparison'


@pytest.mark.parametrize('variant',['baseline','candidate'])
def test_native_benchmark_uses_production_stages_and_keeps_original(client,model,monkeypatch,tmp_path,variant):
    original=store.create_article(dict(topic='监测数据如何帮助决策'))
    before=copy.deepcopy(original)
    async def no_legacy(*args,**kwargs):raise AssertionError('Legacy workflow must not stand in for native writing')
    monkeypatch.setattr(workflow,'call',no_legacy)
    result=asyncio.run(benchmark.native_case(dict(case='sample',article=original),variant,tmp_path,120))
    assert result['status']=='completed',result.get('error')
    assert len(result['jobs'])==3
    assert [store.job(j)['stage'] for j in result['jobs']]==['outline','write','review']
    assert len(result['native_executions'])==3
    assert result['initial_content'] and result['content'] and result['review']
    assert store.get_article(original['id'])==before
