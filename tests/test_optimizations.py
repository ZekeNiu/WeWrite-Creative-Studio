import copy
import asyncio
import io
import json
import zipfile

import pytest
from PIL import Image

from backend import academic, bibliography, flow_state, materials, prompts, providers, rendering, research, source_context, store, workflow
from backend.models import Settings, VisualSettings
from tests.test_studio import client, model, new, patch, run, H


def review_round(client):
    a=patch(client,new(client),{'content':'原文甲。\n\n原文乙。'},'write')
    j=store.create_job(a['id'],{'stage':'review','revision':a['revision'],'chain':True})
    result=dict(decision='revise',summary='请核对两处表达',dimensions={'准确':4},issues=[
        dict(id='i1',quote='原文甲。',suggestion='修改甲。',reason='表达',severity='major',status='pending'),
        dict(id='i2',quote='原文乙。',suggestion='修改乙。',reason='表达',severity='minor',status='pending')])
    a=workflow.apply_result(a,'review',result,{'_job_id':j['id']})
    store.update_job(j['id'],status='needs_input',current_step='generation',generation_revision=a['review']['content_revision'],
                     review_round_id=a['review']['round_id'],message='需要你确认当前结果')
    return a,j


def decide(client,a,i,action='reject',**extra):
    r=client.post(f'/api/articles/{a["id"]}/review/{i}',headers=H,json={'revision':a['revision'],'action':action,**extra})
    assert r.status_code==200,r.text
    return r.json()


@pytest.mark.parametrize('actions',[('accept','accept'),('reject','reject'),('accept','reject')])
def test_manual_review_finishes_only_its_round(client,actions):
    a,j=review_round(client)
    unrelated=store.create_job(a['id'],{'stage':'research','revision':a['revision']})
    store.update_job(unrelated['id'],status='needs_input',message='资料待核实')
    a=decide(client,a,'i1',actions[0])
    assert a['stages']['review']=='needs_input' and store.job(j['id'])['status']=='needs_input'
    a=decide(client,a,'i2',actions[1])
    assert a['stages']['review']=='done' and a['review']['completion']=='human'
    assert a['review']['decision']=='revise'
    assert store.job(j['id'])['status']=='completed'
    assert store.job(unrelated['id'])['status']=='needs_input'
    assert client.get('/api/jobs/'+j['id']).json()['message']=='本轮意见已处理'
    assert client.get('/api/articles/'+a['id']).json()['review']['completion']=='human'
    assert len(store.jobs(a['id']))==2  # No automatic re-review or next stage.
    repeated=client.post(f'/api/articles/{a["id"]}/review/i2',headers=H,json={'revision':a['revision'],'action':'reject'})
    assert repeated.status_code==400
    result=patch(client,a,{'content':a['content']+'后来新增的内容。'},'write')
    assert result['stages']['review']=='stale' and 'completion' not in result['review']


def test_review_conflict_and_non_unique_quote_preserve_content(client):
    a,j=review_round(client)
    changed=patch(client,a,{'content':a['content']+'原文甲。'},'write')
    url=f'/api/articles/{a["id"]}/review/i1'
    assert client.post(url,headers=H,json={'revision':a['revision'],'action':'accept'}).status_code==409
    assert client.post(url,headers=H,json={'revision':changed['revision'],'action':'accept'}).status_code==400
    assert store.get_article(a['id'])['content']==changed['content']
    assert store.job(j['id'])['status']=='needs_input'


def test_review_completion_invalidated_by_sources_and_restore(client):
    a,j=review_round(client)
    a=decide(client,decide(client,a,'i1'),'i2')
    r=client.post(f'/api/articles/{a["id"]}/sources/text',headers=H,json={'revision':a['revision'],'title':'新增依据','text':'新材料'})
    assert r.status_code==200
    a=r.json()
    assert a['stages']['review']=='stale'
    versions=store.versions(a['id'])
    restored=store.restore(a['id'],versions[0]['id'],a['revision'])
    assert restored['stages']['review']=='done' and restored['review']['completion']=='human'


def test_legacy_handled_review_requires_matching_snapshot(client):
    a,j=review_round(client)
    # Simulate old records, including the pre-decision snapshots in versions.
    with store.connection() as db:
        row=json.loads(db.execute('SELECT data FROM articles WHERE id=?',(a['id'],)).fetchone()[0])
        for key in ('round_id','job_id','reviewed_key'): row['review'].pop(key,None)
        db.execute('UPDATE articles SET data=? WHERE id=?',(store.encode(row),a['id']))
    for iid in ('i1','i2'):
        a=store.get_article(a['id'])
        def old_action(v):
            next(i for i in v['review']['issues'] if i['id']==iid)['status']='rejected'
        a=store.save_article(a['id'],a['revision'],old_action,'拒绝审核意见')
    assert a['stages']['review']=='needs_input'  # Stored legacy state.
    reread=store.get_article(a['id'])
    assert reread['stages']['review']=='done'
    assert client.get('/api/jobs/'+j['id']).json()['status']=='completed'
    a=patch(client,reread,{'content':'后来完全改写。'},'write')
    assert store.get_article(a['id'])['stages']['review']=='stale'


@pytest.mark.parametrize('price,currency',[(None,'CNY'),(0,'CNY'),(3.5,'USD')])
def test_image_generation_ignores_legacy_budget_and_optional_price(client,model,monkeypatch,price,currency):
    cfg=providers.settings();cfg['services'][0].update(image_price=price,currency=currency)
    cfg['search']['budget']=0
    providers.save_settings(Settings.model_validate(cfg))
    assert 'budget' not in providers.settings()['search']
    assert 'budget' not in VisualSettings.model_validate({'budget':0}).model_dump()
    a=patch(client,new(client),{'content':'图片测试','visual':{'enabled':True,'count':1,'size':'1024x1024','budget':0},
                              'image_plans':[dict(id='cover',role='cover',prompt='测试图')]},'write')
    blob=io.BytesIO();Image.new('RGB',(16,16),'green').save(blob,'PNG');calls=[]
    async def image(*args): calls.append(1);return blob.getvalue()
    monkeypatch.setattr(providers,'image_generate',image)
    assert run(client,a,'image',image_id='cover')['status']=='completed'
    assert len(calls)==1 and len(store.get_article(a['id'])['images'])==1
    assert store.usage(a['id'])[-1]['currency']==currency


def test_layout_progress_uses_chinese(client,model,monkeypatch):
    a=patch(client,new(client),{'content':'排版内容'},'write');seen=[]
    original=store.update_job
    def update(id,**value): seen.append(value.get('message',''));return original(id,**value)
    monkeypatch.setattr(store,'update_job',update)
    assert run(client,a,'layout_advice',chain=False)['status']=='completed'
    assert '正在生成阅读与结构建议' in seen
    assert not any('layout_advice' in text for text in seen)


def test_export_no_generated_disclosure_and_preserves_manual_text(client):
    a=new(client);a['content']='正文';a['layout']['author']='测试署名'
    a['images']=[dict(filename='test.png',prompt='测试',selected=True,role='cover',caption='图例')]
    store.add_usage(a['id'],stage='write',status='completed')
    result=rendering.render(a,True)
    for value in (result['html'],result['body'],result['plaintext'],result['markdown']):
        assert '本文使用 AI 辅助创作或编辑' not in value and '部分配图由 AI 生成' not in value
        assert '测试署名' in value
    with zipfile.ZipFile(io.BytesIO(rendering.export_zip(a))) as z:
        assert '部分配图由 AI 生成' not in z.read('文章.md').decode()
    a['content']+='\n\n本文使用 AI 辅助创作或编辑。'
    assert '本文使用 AI 辅助创作或编辑。' in rendering.markdown(a)


def test_long_source_evidence_and_tail_survive_context_without_duplication(client):
    a=new(client,topic='末尾肌力结论');quote='末尾肌力结论只适用于成年受试者。'
    text='无关背景。'*8000+quote+'\n研究局限：缺少儿童数据。'
    s=materials.source('长篇书籍',text);a['sources']=[s]
    span=dict(source_id=s['id'],quote=quote,claim='仅限成人',boundary='不适用儿童',source_type='专业书籍',adoption_reason='本章对应实验',use_scope='成人')
    a['evidence']={'claims':[dict(id='C1',text='仅限成人',source_ids=[s['id']],evidence=[span])]}
    a['research']={'evidence':[span],'log':[{'message':'不应重复进入写作上下文'}]}
    a['outline']={'sections':[dict(id='one',title='肌力的边界',claim_ids=['C1'])]}
    before=copy.deepcopy(a)
    ctx=json.loads(prompts.prompt('write',a,{}))['资料与当前内容']
    assert quote in ctx['sources'][0]['text'] and '缺少儿童数据' in ctx['sources'][0]['text']
    assert ctx['sources'][0]['excerpt_only'] and 'log' not in ctx['research']
    assert json.dumps(ctx,ensure_ascii=False).count(quote)==1
    assert a==before and len(s['text'])>40000
    spans=ctx['sources'][0]['excerpts']
    assert all(x['end']<y['start'] for x,y in zip(spans,spans[1:]))
    a['research']={};a['evidence']={}
    assert quote in research.context(a,'sources')['sources'][0]['text']


def test_quality_insufficient_core_claim_blocks_and_records_provenance(client):
    s=materials.source('博客','某产品能显著改善表现。')
    e=dict(source_id=s['id'],quote=s['text'],claim='产品有效',quality='insufficient',core_claim=True,
           source_type='营销博客',adoption_reason='没有原始实验',use_scope='仅可作为观点线索')
    notes=research.validate_spans(dict(summary='核对',evidence=[e],gaps=[],issues=[]),[s])
    assert notes['issues'][0]['kind']=='blocking' and notes['gaps']
    assert notes['evidence'][0]['source_type']=='营销博客'
    assert notes['evidence'][0]['verification']=='quote_matched'  # Matching a quote is not proof.
    e['core_claim']=False
    notes=research.validate_spans(dict(summary='核对',evidence=[e],gaps=[],issues=[]),[s])
    assert not notes['gaps'] and notes['issues'][0]['kind']=='limitation'


def test_quality_policy_reaches_all_editorial_stages(client):
    a=new(client)
    for stage in ('sources','write','review'):
        system=prompts.system(stage,a['brief'])
        for term in ('维基百科','专业博客','专业书籍','预印本','原始出处','不能仅凭域名'):
            assert term in system and term in research.SYSTEM


def test_updated_policy_reuses_completed_assessment_but_not_legacy(client,model,monkeypatch):
    from tests.quality_fixtures import judgements,notes as quality_notes
    a=new(client);source=materials.source('原文','可定位证据。')
    a=store.save_article(a['id'],a['revision'],lambda v:v.update(sources=[source],research={'stale':False,'gaps':[],'conflicts':[]}), 'fixture')
    cfg=providers.settings();cfg['search']['enabled']=True;providers.save_settings(Settings.model_validate(cfg))
    calls=[]
    async def structured(a,stage,instruction,schema,job_id,candidates=None,questions=()):
        calls.append(schema.__name__)
        if schema.__name__=='ResearchPlan':return {'needed':False,'queries':[],'questions':[],'academic':False}
        if schema.__name__=='CoverageAudit':
            from tests.quality_fixtures import coverage_audit
            return coverage_audit(candidates)
        if schema.__name__=='EvidenceJudgements':return judgements(candidates,a['research_contract'])
        return quality_notes(a,{'summary':'已核对','evidence':[dict(source_id=source['id'],quote=source['text'],claim='证据',quality='suitable')],'gaps':[],'conflicts':[],'followup_queries':[],'issues':[]})
    monkeypatch.setattr(research,'structured',structured)
    j=store.create_job(a['id'],{'stage':'outline'})
    a,pending=asyncio.run(research.gather(a,j['id'],'outline'))
    assert not pending and calls==['ResearchPlan','ResearchNotes','EvidenceJudgements','CoverageAudit']
    assert a['research']['policy_version']==source_context.POLICY_VERSION
    before=len(calls)
    a,pending=asyncio.run(research.gather(a,j['id'],'outline'))
    assert not pending and len(calls)==before
    # Same-stage non-outline reuse checks the key after collecting the new material.
    a,pending=asyncio.run(research.gather(a,j['id'],'sources'))
    before=len(calls)
    a,pending=asyncio.run(research.gather(a,j['id'],'sources'))
    assert not pending and len(calls)==before


def test_empty_nonpassing_review_does_not_create_unactionable_pause(client):
    with pytest.raises(ValueError,match='可处理的审核意见'):
        workflow.validate_result('review',dict(decision='revise',issues=[]),new(client))


def test_distinct_studies_and_versions_not_deduplicated():
    a=materials.source('同标题论文','内容相似'*100,'https://example.org/one','web')
    b=materials.source('同标题论文','内容相似'*100,'https://example.org/two','web')
    assert not research.duplicate(a,[b]) and not academic.same(a,b)
    a.update(doi='10.1/example',bibliography={'document_type':'PP','version':'v1'})
    b.update(doi='10.1/example',bibliography={'document_type':'J','version':'v1'})
    assert not research.duplicate(a,[b]) and not academic.same(a,b)
    b['bibliography']={'document_type':'PP','version':'v2'}
    assert len(academic.merge_records([a,b]))==2
    b['bibliography']['version']='v1'
    assert len(academic.merge_records([a,b]))==1


@pytest.mark.parametrize('filename,text',[
    ('book.bib','@book{x,title={训练科学},author={张三},publisher={科学出版社},address={北京},year={2024},edition={第2版},pages={30--35}}'),
    ('book.ris','TY  - BOOK\nTI  - 训练科学\nAU  - 张三\nPB  - 科学出版社\nCY  - 北京\nPY  - 2024\nET  - 第2版\nSP  - 30\nEP  - 35\nER  - \n')])
def test_books_import_edit_and_export(client,filename,text):
    source=bibliography.import_records(filename,text.encode())[0]
    assert source['status']=='metadata_only'
    result=bibliography.format_reference(source)
    assert result['complete'] and '[M]' in result['text'] and '北京: 科学出版社, 2024: 30-35' in result['text']
    assert '第2版' in result['text']
    a=new(client)
    r=client.post(f'/api/articles/{a["id"]}/sources/file',headers=H,data={'revision':a['revision']},files={'file':(filename,text.encode())})
    assert r.status_code==200,r.text
    a=r.json();source=a['sources'][0]
    a=patch(client,a,{'sources':[source],'content':f'引用[{source["id"]}]'},'write')
    assert a['sources'][0]['bibliography']['publisher']=='科学出版社'
    assert '[M]' in rendering.render(a)['plaintext']
    source['bibliography'].pop('publisher')
    assert '出版社' in bibliography.format_reference(source)['missing']
