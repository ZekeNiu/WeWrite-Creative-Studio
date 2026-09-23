"""Commit native artifacts through the same human-state transaction as the UI."""
import copy
from . import store, editorial, review_state, creative


def apply(article,stage,packet,request):
    result=packet['result'];used=packet['account_use']
    def change(v):
        if stage=='layout_advice':
            v['layout_advice']=result;v.setdefault('native_executions',[]).append(packet['native']);return
        v['sources']=packet['sources'];v['native_brief']=packet['brief']
        if 'claims' in packet and stage in ('sources','outline','write','review','edit'):
            v['evidence']={**v.get('evidence',{}),**packet['claims'],'engine':'wewrite-native'}
        if 'ledger' in packet:v['native_sources']=packet['ledger']
        v.setdefault('native_executions',[]).append(packet['native'])
        v['execution_engine']='wewrite-native'
        target='write' if stage=='revise' else 'review' if stage=='edit' else stage
        v['current_stage']=target;v['stages'][target]='done'
        if stage=='topic':
            creative.candidates(v,result['topics'],request.get('instruction',''))
            if v['auto']['topic']:creative.adopt(v,result['topics'][0]['title'],result['topics'][0]['id'])
            else:v['stages']['topic']='needs_input'
        elif stage=='sources':v['evidence']=dict(result,engine='wewrite-native')
        elif stage=='outline':
            if request.get('section_id') and v.get('outline'):
                section=next((s for s in result['sections'] if s['id']==request['section_id']),None)
                if not section:raise ValueError('结果未包含指定章节；大纲保持不变')
                v['outline']['sections']=[section if s['id']==section['id'] else s for s in v['outline']['sections']]
            else:v['outline']=result
        elif stage=='write':
            v['content']=result;editorial.record_draft(v,'initial',result,origin='ai')
        elif stage=='revise':
            v['suggestions'].append(dict(id=store.uid(),original=request.get('selected_text') or article['content'],replacement=result,
                explanation='按当前要求生成的上游写作候选',base_revision=article['revision'],account_use=used))
        elif stage in ('review','edit'):
            content=result['_content'];report={k:val for k,val in result.items() if not k.startswith('_')}
            report['native_report']=result['_report'];report['quality_version']='wewrite-4.2.1'
            if content!=v['content']:
                candidate=dict(id=store.uid(),base_key=review_state.signature(v),base_revision=v['revision'],base_content=v['content'],content=content,
                    explanation=report['summary'],changes=[],unresolved=[],review=copy.deepcopy(report),diff=editorial.diff(v['content'],content),
                    status='pending',checked=True,created=store.now(),job_id=request['_job_id'],account_use=used,engine='wewrite-native')
                v.setdefault('editorial_candidates',[]).append(candidate)
                if stage=='review' and v['auto']['review'] and report['decision']=='pass':
                    v['content']=content;candidate.update(status='adopted',adopted_by='auto')
                    editorial.record_draft(v,'edited',content,candidate_id=candidate['id'],origin='ai')
                else:
                    # The verdict describes the candidate, not the untouched original.
                    if stage=='edit':
                        v['stages']['review']=article['stages']['review']
                        return
                    v['stages']['review']='needs_input'
                    v['review']=dict(decision='revise',summary='上游编辑候选已保存，请查看差异后采用或拒绝。',issues=[],candidate_id=candidate['id'],job_id=request['_job_id'])
                    return
            report.update(round_id=store.uid(),job_id=request['_job_id'],reviewed_key=review_state.signature(v),content_revision=v['revision'])
            if report['decision']=='pass':report['completion']='ai'
            else:v['stages']['review']='needs_input'
            v['review']=report
        elif stage=='visual':v['image_plans']=result['images'][:v['visual']['count']]
    invalidate='review' if stage=='edit' else None if stage in ('revise','layout_advice') else stage
    return store.save_article(article['id'],article['revision'],change,'完成上游创作环节',invalidate=invalidate,account_use=used)
