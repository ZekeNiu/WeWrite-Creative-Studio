"""Stable reader questions and evidence coverage, independent of permission to write."""
import copy
from . import creative,evidence_state

VERSION=1
CHECKS=('population','design','quantity','outcome','causality','scope')


def objective(a):
    selected=creative.intent(a).get('selected',{})
    return dict(brief={k:a['brief'].get(k,'') for k in ('topic','purpose','include','avoid','domain','column','audience')},
                selected={k:selected.get(k,'') for k in ('id','angle','reader_question','novelty','takeaway','key_claims','questions')})


def ensure(a,questions=()):
    key=evidence_state.digest(objective(a));old=a.get('research_contract',{})
    if old.get('objective_key')==key:return old
    intent=creative.intent(a);selected=intent.get('selected',{})
    # The user's original demand is always a question, even if the planner omits it.
    original='；'.join(str(a['brief'].get(k,'')) for k in ('topic','purpose','include') if a['brief'].get(k))
    texts=[(original or intent.get('original_request') or a['brief'].get('column',''),True)]
    texts += [(x,True) for x in [selected.get('reader_question','')]+list(selected.get('key_claims') or [])+list(selected.get('questions') or [])]
    texts += [(x,False) for x in questions]
    seen=set();rows=[]
    for text,required in texts:
        text=str(text).strip();normal=evidence_state.normal(text)
        if text and normal not in seen:
            seen.add(normal);rows.append(dict(id='Q'+evidence_state.digest(text)[:12],text=text,required=required))
    value=dict(version=VERSION,objective_key=key,original_request=intent.get('original_request') or original,
               reader_value=selected.get('takeaway') or selected.get('novelty',''),questions=rows[:16])
    a['research_contract']=value
    return value


def semantic_valid(e):
    checks=e.get('support_checks',{})
    return (e.get('assessment_version')==1 and e.get('support_basis') in ('observed','author_interpretation','external_reference','not_applicable')
            and bool(e.get('support_reason')) and all(k in checks for k in CHECKS))


def apply_judgements(spans,rows):
    by_id={};duplicates=set()
    for row in rows:
        key=row['evidence_id']
        if key in by_id:duplicates.add(key)
        by_id[key]=row
    for e in spans:
        row=by_id.get(e['evidence_id'])
        if not row or e['evidence_id'] in duplicates:continue
        checks=row.get('checks',{})
        complete=all(k in checks for k in CHECKS)
        support=row['support'] if complete and row.get('reason') else 'unsupported'
        if support in ('supported','limited') and any(checks.get(k) in ('mismatch','unknown') for k in CHECKS):support='unsupported'
        if support=='limited' and not e.get('boundary'):support='unsupported'
        basis=row.get('basis','unassessed')
        if basis=='unassessed':support='unsupported'
        if basis in ('author_interpretation','external_reference') and support in ('supported','limited'):
            support='limited';e['type']='inference'
            e['boundary']='；'.join(x for x in [e.get('boundary'), '这是作者的解释或转引，不能当作本研究直接验证的结果'] if x)
        e.update(support=support,support_basis=basis,support_reason=row.get('reason') or '独立核查未提供完整判断',
                 support_checks=checks,question_ids=row.get('question_ids',[]),assessment_version=1)
        if support=='limited' and e.get('quality')=='suitable':e['quality']='limited'
        if support in ('unsupported','contradicted'):e['quality']='insufficient'
    return spans


def coverage(a,notes,previous=(),requested=()):
    questions=ensure(a)['questions'];verdicts={x['question_id']:x for x in notes.get('coverage',[])}
    old={x['question_id']:copy.deepcopy(x) for x in previous}
    target_ids={x.get('question_id') for x in a.get('research',{}).get('issues',[]) if x['id'] in requested}
    target_ids.discard(None);target_ids.discard('')
    rows=[]
    for q in questions:
        qid=q['id']
        if requested and target_ids and qid not in target_ids and qid in old:
            rows.append(old[qid]);continue
        v=verdicts.get(qid,{})
        spans=[e for e in notes.get('evidence',[]) if qid in e.get('question_ids',[]) and semantic_valid(e)
               and (evidence_state.assessed(e) or e.get('support')=='contradicted')]
        status=v.get('status','unresolved') if spans and v.get('reason') else 'unresolved'
        if status=='supported' and not any(e.get('support')=='supported' and evidence_state.assessed(e) for e in spans):status='limited' if any(evidence_state.assessed(e) for e in spans) else 'unresolved'
        rows.append(dict(question_id=qid,question=q['text'],required=q['required'],status=status,
            reason=v.get('reason') or '尚无能回答此问题的独立核查依据',
            evidence_ids=[e['evidence_id'] for e in spans],source_ids=list(dict.fromkeys(e['source_id'] for e in spans))))
    return rows


def sufficient(rows):
    return bool(rows) and all(x['status'] in ('supported','limited','contradicted') and x.get('evidence_ids') for x in rows if x.get('required',True))


def issues(rows):
    return [dict(id=x['question_id'],question_id=x['question_id'],text='核心问题尚未解决：'+x['question'],
                 kind='blocking',priority='high',source_ids=x['source_ids'],claim='',status='open',system_kind='coverage')
            for x in rows if x['required'] and x['status']=='unresolved']


def resolve_issues(rows,coverage):
    for item in rows:
        if item.get('system_kind')=='coverage':
            covered=next((x for x in coverage if x['question_id']==item.get('question_id',item['id'])),None)
            if covered and covered['status']!='unresolved' and covered['evidence_ids'] and item['status'] not in ('bounded','excluded','waived'):
                item.update(status='resolved',resolution=covered['reason'],source_ids=covered['source_ids'])
    return rows
