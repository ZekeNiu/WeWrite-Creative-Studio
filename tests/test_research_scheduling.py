"""Assess collection batches without cumulative request or page limits."""
import asyncio
import pytest
from backend import research
from tests.test_quality_discovery import worker


@pytest.mark.parametrize('legacy_limit',[6,2])
def test_questions_share_one_assessment_before_another_search_turn(monkeypatch,legacy_limit):
    w=worker();w.cfg['max_calls']=legacy_limit;events=[];complete=False
    monkeypatch.setattr(research.search_plan,'channels',lambda *args:['native','tavily'])
    monkeypatch.setattr(w,'sufficient',lambda:complete)
    async def channel(name,query):
        w.calls+=1;events.append(('search',query));return [dict(title=query,url='https://example.org/'+query)]
    async def collect(rows,*args,**kwargs):
        w.pages+=1;events.append(('read',rows[0]['title']));return 1
    async def assess():
        nonlocal complete
        events.append(('assess',w.pages));complete=True
    monkeypatch.setattr(w,'channel',channel);monkeypatch.setattr(w,'collect',collect);monkeypatch.setattr(w,'assess',assess)
    asyncio.run(w.discover(['one','two','three']))
    assert [event for event in events if event[0]=='assess']==[('assess',3)]
    assert w.calls==3 and events[-1][0]=='assess'


@pytest.mark.parametrize('legacy_limit',[5,3])
def test_deferred_reads_assess_in_pairs_without_legacy_page_cap(monkeypatch,legacy_limit):
    w=worker();w.cfg['max_pages']=legacy_limit;checks=[]
    w.deferred=[dict(title=str(i),url=f'https://example.org/{i}') for i in range(5)]
    async def collect(*args,**kwargs):w.pages+=1;return 1
    async def assess():checks.append(w.pages)
    monkeypatch.setattr(w,'collect',collect);monkeypatch.setattr(w,'assess',assess)
    monkeypatch.setattr(w,'sufficient',lambda:False)
    asyncio.run(w.drain_candidates())
    assert checks==[2,4,5] and not w.deferred


def test_cancel_during_collection_never_starts_assessment(monkeypatch):
    w=worker();w.deferred=[dict(url='https://example.org/one')]
    async def collect(*args,**kwargs):raise asyncio.CancelledError()
    async def assess():raise AssertionError('Cancelled collection must stop')
    monkeypatch.setattr(w,'collect',collect);monkeypatch.setattr(w,'assess',assess)
    with pytest.raises(asyncio.CancelledError):asyncio.run(w.drain_candidates())
