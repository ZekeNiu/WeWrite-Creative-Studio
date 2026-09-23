import copy
import asyncio
import pytest
from backend import editorial,store,materials,review_state
from tests.test_research import client
from tests.quality_fixtures import assessment


def source_article():
    a=store.create_article({'topic':'Study conditions'})
    s=materials.source('Study','An observational cohort of 20 adults found an association.','https://example.org')
    a['sources']=[s];a['content']='20名成人的观察研究发现相关性。['+s['id']+']'
    return a,s


def audit_reply(a,s,**changes):
    part=editorial.segments(a['content'])[0]
    fact=dict(quote='20名成人的观察研究发现相关性。',source_id=s['id'],source_quote=s['text'],status='supported',reason='Same design, population and finding',basis='observed',checks=assessment()['support_checks'],boundary='')
    fact.update(changes)
    return [part],dict(segments=[dict(segment_id=part['id'],facts=[fact])])


def test_high_scores_cannot_override_missing_or_wrong_evidence(client):
    a,s=source_article();parts,result=audit_reply(a,s,source_quote='Not present in the study.')
    checked,issues=editorial.audit_findings(a,parts,result)
    report=editorial.gate(dict(decision='pass',issues=[],dimensions=dict.fromkeys(editorial.DIMENSIONS,5)),dict(complete=True,issues=issues))
    assert report['decision']=='revise' and report['issues'][0]['severity']=='blocker'


def test_uncited_fact_and_missing_segment_are_not_passed(client):
    a,s=source_article();a['content']=a['content'].split('[')[0]
    parts,result=audit_reply(a,s)
    _,issues=editorial.audit_findings(a,parts,result)
    assert '未在相邻' in issues[0]['reason']
    checked,issues=editorial.audit_findings(a,parts,dict(segments=[]))
    assert not checked and issues


def test_five_dimensions_are_complete_bounded_and_thresholded():
    review=dict(decision='pass',issues=[],dimensions=dict.fromkeys(editorial.DIMENSIONS,4))
    assert editorial.gate(review,dict(complete=True,issues=[]))['decision']=='pass'
    for change in [dict(voice=2),dict(voice=6),dict(voice=None),dict(voice=3)]:
        revised=copy.deepcopy(review);revised['dimensions'].update(change)
        assert editorial.gate(revised,dict(complete=True,issues=[]))['decision']=='revise'


def test_concurrent_manual_change_keeps_candidate_but_cannot_overwrite(client):
    a,s=source_article()
    a=store.save_article(a['id'],a['revision'],lambda v:v.update(content=a['content'],sources=a['sources']),'fixture')
    base=copy.deepcopy(a)
    a=store.save_article(a['id'],a['revision'],lambda v:v.update(content='人工新稿'),'manual')
    a,candidate=editorial.save_candidate(base,'fixture',dict(content='AI整体编辑稿',explanation='Structure',changes=[]),dict(decision='pass',issues=[]))
    a=editorial.candidate_review(a['id'],candidate['id'],dict(decision='pass',issues=[]))
    assert a['content']=='人工新稿' and candidate['status']=='pending'
    with pytest.raises(store.Conflict):editorial.adopt(a,candidate['id'])
    assert store.get_article(a['id'])['editorial_candidates'][0]['content']=='AI整体编辑稿'


def test_adopting_candidate_keeps_draft_and_verified_review_separate(client):
    a,s=source_article()
    a=store.save_article(a['id'],a['revision'],lambda v:v.update(content=a['content'],sources=a['sources']),'fixture')
    a,c=editorial.save_candidate(a,'job',dict(content='新版正文',explanation='Reordered'),dict(decision='pass',issues=[],dimensions=dict.fromkeys(editorial.DIMENSIONS,4)))
    a=editorial.candidate_review(a['id'],c['id'],dict(decision='pass',issues=[],dimensions=dict.fromkeys(editorial.DIMENSIONS,4)))
    saved=editorial.adopt(a,c['id'])
    assert saved['content']=='新版正文' and saved['draft_versions'][-1]['kind']=='edited'
    assert saved['draft_versions'][-1]['origin']=='ai' and saved['review']['completion']=='ai'
    assert saved['review']['reviewed_key']==review_state.signature(saved)


@pytest.mark.parametrize('new_fact_error',[False,True])
def test_automatic_whole_edit_is_bounded_and_rechecks_facts(client,monkeypatch,new_fact_error):
    from backend import workflow,research
    from backend.models import JobRequest
    a=store.create_article({'topic':'Synthetic editing'})
    def seed(v):v.update(content='原稿');v['auto']['review']=True;v['stages']['write']='done'
    a=store.save_article(a['id'],a['revision'],seed,'fixture');calls=[];edits=[]
    async def gather(a,*args):return a,False
    async def review(job_id,stage,a,request):
        calls.append(a['content'])
        blocker=new_fact_error and len(calls)>1
        return dict(decision='revise',summary='Still needs editing',dimensions=dict.fromkeys(editorial.DIMENSIONS,4),
            issues=[dict(id='r',severity='blocker' if blocker else 'major',quote='',reason='New factual error' if blocker else 'Reorganize reasoning',suggestion='',source_ids=[],status='pending')])
    async def edit(a,*args):
        edits.append(a['content']);return dict(content=a['content']+'修改',explanation='Structural revision',changes=[])
    monkeypatch.setattr(research,'gather',gather);monkeypatch.setattr(workflow,'call',review);monkeypatch.setattr(editorial,'edit',edit)
    j=store.create_job(a['id'],JobRequest(stage='review',revision=a['revision'],chain=False).model_dump())
    asyncio.run(workflow.run(j['id']))
    saved=store.get_article(a['id'])
    assert len(edits)==(1 if new_fact_error else 2)
    assert len(calls)==len(edits)+1
    assert saved['content']==('原稿' if new_fact_error else '原稿修改修改')
    assert saved['editorial_candidates'][-1]['status']==('pending' if new_fact_error else 'adopted')
    assert saved['stages']['review']=='needs_input'


def test_manual_final_records_real_edit_pair_without_changing_ai_verdict(client):
    from tests.test_studio import H,patch
    a=store.create_article({'topic':'Human revision'})
    def seed(v):
        v['content']='AI原稿';editorial.record_draft(v,'initial',v['content'],origin='ai')
    a=store.save_article(a['id'],a['revision'],seed,'fixture');base=a['current_draft_id']
    a=patch(client,a,dict(content='人工作出的修改'),'write')
    r=client.post('/api/articles/'+a['id']+'/drafts/final',headers=H,json=dict(revision=a['revision']))
    assert r.status_code==200,r.text
    final=r.json()['draft_versions'][-1]
    assert final['origin']=='human' and final['human_edit_base']==base
    assert final['review_state']!='AI 审核通过'


def test_review_checks_draft_once_without_restarting_research(client,monkeypatch):
    import json
    from backend import workflow,research,providers
    from backend.models import JobRequest
    a=store.create_article({'topic':'A bounded editorial review'})
    def seed(v):
        v['content']='一段待审稿件';v['auto']['review']=False;v['stages']['write']='done'
    a=store.save_article(a['id'],a['revision'],seed,'fixture');checked=[]
    async def no_research(*args):raise AssertionError('Review must not restart discovery')
    async def audit(article,job):
        checked.append(article['content']);return dict(complete=True,issues=[])
    async def generate(*args):
        return json.dumps(dict(decision='pass',summary='No issues',issues=[],dimensions=dict.fromkeys(editorial.DIMENSIONS,4))),dict(status='completed')
    monkeypatch.setattr(research,'gather',no_research);monkeypatch.setattr(editorial,'audit',audit)
    monkeypatch.setattr(providers,'generate',generate)
    monkeypatch.setattr(providers,'service_for',lambda *args:dict(model='mock',name='mock'))
    j=store.create_job(a['id'],JobRequest(stage='review',revision=a['revision']).model_dump())
    asyncio.run(workflow.run(j['id']))
    assert store.job(j['id'])['status']=='completed'
    assert checked==['一段待审稿件'] and store.get_article(a['id'])['review']['decision']=='pass'


def test_factual_audit_receives_originals_without_prior_self_assessment(client,monkeypatch):
    import json
    from backend import providers
    a,s=source_article();a['evidence']={'claims':[{'claim':'Prior verdict'}]}
    a['argument_synthesis']={'thesis':'Prior reasoning'}
    j=store.create_job(a['id'],dict(stage='review'));sent=[]
    async def generate(service,system,prompt,emit):
        sent.append(json.loads(prompt));return '{"segments":[]}',dict(status='completed')
    monkeypatch.setattr(providers,'generate',generate)
    monkeypatch.setattr(providers,'service_for',lambda *args:dict(model='mock',name='mock'))
    asyncio.run(editorial.generate(a,j['id'],'review','Check facts',editorial.FactAudit,dict(segments=editorial.segments(a['content']))))
    context=sent[0]['context']
    assert context['sources'][0]['text']==s['text'] and context['segments']
    assert not {'evidence','argument_synthesis','issue_decisions','outline'}&context.keys()
