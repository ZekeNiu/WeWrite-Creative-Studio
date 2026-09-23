"""Assess a bounded collection batch without skipping evidence or page limits."""
import asyncio
import pytest
from backend import research
from tests.test_quality_discovery import worker


@pytest.mark.parametrize('call_limit,expected_reads',[(6,3),(2,2)])
def test_questions_share_one_assessment_before_another_search_turn(monkeypatch,call_limit,expected_reads):
    w=worker();w.cfg['max_calls']=call_limit;events=[];complete=False
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
    assert [event for event in events if event[0]=='assess']==[('assess',expected_reads)]
    assert w.calls==expected_reads and events[-1][0]=='assess'


@pytest.mark.parametrize('page_limit,expected_checks,remaining',[(5,[2,4,5],0),(3,[2,3],2)])
def test_deferred_reads_assess_in_pairs_and_respect_page_limit(monkeypatch,page_limit,expected_checks,remaining):
    w=worker();w.cfg['max_pages']=page_limit;checks=[]
    w.deferred=[dict(title=str(i),url=f'https://example.org/{i}') for i in range(5)]
    async def collect(*args,**kwargs):w.pages+=1;return 1
    async def assess():checks.append(w.pages)
    monkeypatch.setattr(w,'collect',collect);monkeypatch.setattr(w,'assess',assess)
    monkeypatch.setattr(w,'sufficient',lambda:False)
    asyncio.run(w.drain_candidates())
    assert checks==expected_checks and len(w.deferred)==remaining


def test_cancel_during_collection_never_starts_assessment(monkeypatch):
    w=worker();w.deferred=[dict(url='https://example.org/one')]
    async def collect(*args,**kwargs):raise asyncio.CancelledError()
    async def assess():raise AssertionError('Cancelled collection must stop')
    monkeypatch.setattr(w,'collect',collect);monkeypatch.setattr(w,'assess',assess)
    with pytest.raises(asyncio.CancelledError):asyncio.run(w.drain_candidates())
