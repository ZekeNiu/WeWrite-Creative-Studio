"""Research checkpoints and semantic progress; source counts are not progress."""
import copy
from . import evidence_state, research_contract, source_notebook


def source_versions(a):
    result={}
    for s in a['sources']:
        if not s.get('selected'):continue
        ranges=[]
        for r in sorted([*s.get('notebook',{}).get('read_ranges',[]),*s.get('_requested_sections',[])],key=lambda r:r['start']):
            if ranges and r['start']<=ranges[-1][1]:ranges[-1][1]=max(ranges[-1][1],r['end'])
            else:ranges.append([r['start'],r['end']])
        result[s['id']]=evidence_state.digest([evidence_state.source_key(s),s.get('status'),ranges])
    return result


def demand(a,requirements):
    return evidence_state.digest([research_contract.objective(a),requirements])


def progress(a,coverage,issues,question_ids=()):
    required={q['id']:q for q in research_contract.ensure(a)['questions'] if q['required']}
    required.update({t['id']:t for t in a['research_contract'].get('source_targets',[])})
    if question_ids:required={k:v for k,v in required.items() if k in question_ids}
    rows={r['question_id']:r for r in coverage}
    values=[]
    for qid in sorted(required):
        r=rows.get(qid,{})
        status=r.get('status','unresolved') if r.get('evidence_ids') else 'unresolved'
        parts=sorted({p['request_quote'] for p in (r.get('answer_scope') or {}).get('parts',[])
                      if p.get('status')=='answered' and p.get('evidence_ids')})
        values.append((qid,status,parts))
    resolved=sorted(i['id'] for i in issues if i['status'] in ('resolved','bounded','excluded')
                    and (not question_ids or i.get('question_id') in question_ids))
    return evidence_state.digest([values,resolved])


def bind_query(a,item,coverage,requested=()):
    item=copy.deepcopy(item);contract=research_contract.ensure(a)
    required={q['id']:q['text'] for q in contract['questions'] if q['required']}
    required.update({t['id']:t['value'] for t in contract.get('source_targets',[])})
    supplied=item.get('question_ids',[])
    if supplied and (set(supplied)-required.keys()):return None
    ids=list(dict.fromkeys(supplied))
    quote=item.get('request_quote','').strip()
    if quote and not ids:
        quoted=[qid for qid,text in required.items() if quote in text]
        if quoted:ids=quoted
        else:
            clues=contract.get('research_clues',[])+[q['text'] for q in contract['questions'] if not q['required']]
            if not any(quote in text for text in clues):return None
            # A known adopted clue may locate an answer to the reader question.
            # It must not become a new mandatory fact or numerical promise.
    if not ids:ids=[qid for qid,text in required.items() if text==item.get('question')]
    if not ids:
        open_ids={r['question_id'] for r in coverage if r.get('required') and r['status']=='unresolved'}
        ids=[qid for qid in required if not open_ids or qid in open_ids]
    if requested:
        targets={i.get('question_id') for i in a.get('research',{}).get('issues',[]) if i['id'] in requested}-{None,''}
        if targets:ids=[qid for qid in ids if qid in targets]
    if not ids:return None
    item['question_ids']=sorted(ids)
    item['expected_gain']=item.get('expected_gain') or '核对：'+'；'.join(required[qid] for qid in ids)
    return item


def retain_evidence(old,new,source_keys,previous_keys):
    """Preserve unchanged candidates verbatim; explicit revisions never reuse verdicts."""
    replacements={e.get('replaces_evidence_id') for e in new}-{None,''}
    revised={(e['source_id'],e['claim']) for e in new}
    retained=[copy.deepcopy(e) for e in old if source_keys.get(e['source_id'])==previous_keys.get(e['source_id'])
              and e['source_id'] in source_keys and e.get('evidence_id') not in replacements
              and (e['source_id'],e['claim']) not in revised]
    return retained+new


def scoped_article(a,ids):
    value=copy.deepcopy(a)
    value['sources']=[s for s in value['sources'] if s['id'] in ids]
    # Prior verdicts are reference wording, never a second copy of the evidence pool.
    value['evidence']={**value.get('evidence',{}),'claims':[]}
    value['research']={**value.get('research',{}),'evidence':[]}
    return value


def request_reads(a,requests,attempted):
    fresh=[]
    for r in requests:
        source=next((s for s in a['sources'] if s.get('selected') and s['id']==r['source_id']),None)
        if not source:continue
        key=evidence_state.digest([evidence_state.source_key(source),r['section_id']])
        if key in attempted:continue
        attempted.add(key);fresh.append(r)
    return source_notebook.request_reads(a,fresh)
