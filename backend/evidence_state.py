"""One current evidence record, scoped dependencies, and a shared material view."""
import copy
import hashlib
import json
import re


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def objective(a):
    from .creative import intent
    return [ {k:a['brief'].get(k) for k in ('topic','column','domain','audience','purpose','include','avoid','recent_days')}, intent(a).get('selected') ]


def source_key(s):
    return digest({k:s.get(k) for k in ('id','selected','text','use','personal_material','bibliography')})


def selected(a):
    return {s['id']:source_key(s) for s in a['sources'] if s.get('selected',True)}


def dependency(a, issue):
    ids=issue.get('source_ids',[])
    sources=selected(a)
    return digest([objective(a),{sid:sources.get(sid) for sid in ids}])


def normal(text):
    return re.sub(r'\s+','',text).casefold()


def merge_issues(a, notes, requested=()):
    from .flow_state import issues,issue_id
    old=issues(a);lookup={x['id']:x for x in old}; rows={x['id']:copy.deepcopy(x) for x in old}
    seen=set()
    if notes.get('evidence'):
        for x in rows.values():
            if x.get('system_kind')=='no_evidence': x.update(status='resolved',resolution='已取得可定位的原文支持')
    for raw in notes.get('issues',[]):
        item=dict(raw);iid=item.get('id')
        if iid not in lookup:
            match=next((x for x in old if (item.get('claim_id') and item['claim_id']==x.get('claim_id')) or
                normal(item['text'])==normal(x['text']) or (item.get('claim') and normal(item['claim'])==normal(x.get('claim','')))),None)
            iid=match['id'] if match else item['id'] if item.get('system_kind')=='no_evidence' else issue_id(item['text'],item.get('source_ids',[]))
        if requested and iid in lookup and iid not in requested: continue
        duplicates=[x for x in item.get('merged_ids',[]) if x in lookup and x!=iid]
        protected=[x for x in [iid]+duplicates if x in a.get('research_decisions',{})]
        if len(protected)>1:duplicates=[]
        elif protected and protected[0]!=iid:
            duplicates=[x for x in [iid]+duplicates if x!=protected[0]];iid=protected[0]
        for duplicate in duplicates:
            item['source_ids']=list(dict.fromkeys(item.get('source_ids',[])+lookup[duplicate].get('source_ids',[])))
            rows.pop(duplicate,None)
        item['merged_ids']=duplicates
        evidence=[e for e in notes.get('evidence',[]) if e.get('quality')!='insufficient' and
            ((item.get('claim_id') and item['claim_id']==e.get('claim_id')) or
             (item.get('claim') and normal(item['claim'])==normal(e['claim'])))]
        supported=bool(evidence) and bool(item.get('resolution'))
        item.update(id=iid,status='resolved' if item.get('status')=='resolved' and supported else 'open')
        rows[iid]=item;seen.add(item['text'])
    for kind,key in ([] if notes.get('issues') else [('blocking','gaps'),('limitation','conflicts')]):
        for text in notes.get(key,[]):
            if text in seen or any(normal(x['text'])==normal(text) for x in rows.values()): continue
            iid=issue_id(text);rows[iid]=dict(id=iid,text=text,kind=kind,status='open',source_ids=[],claim='')
    return issues(dict(a,research=dict(a.get('research',{}),issues=list(rows.values()))))


def merge_claims(a, spans, requested=()):
    claims=copy.deepcopy(a.get('evidence',{}).get('claims',[]));lookup={c['id']:c for c in claims}
    from .flow_state import issues
    target_claims={q.get('claim_id') for q in issues(a) if q['id'] in requested}
    target_texts={normal(q.get('claim','')) for q in issues(a) if q['id'] in requested}
    touched=set()
    for e in spans:
        cid=e.get('claim_id')
        if cid not in lookup:
            same=next((c for c in claims if normal(c['text'])==normal(e['claim'])),None)
            cid=same['id'] if same else 'C'+digest(e['claim'])[:12]
        if requested and cid in lookup and cid not in target_claims and normal(lookup[cid]['text']) not in target_texts and not lookup[cid].get('stale'):
            continue
        if cid not in touched:
            old=lookup.get(cid,{})
            claim=dict(old,id=cid,text=e['claim'],type=e.get('type',old.get('type','fact')),
                source_ids=[],evidence=[],boundary=e.get('boundary',''),status='supported')
            lookup[cid]=claim;touched.add(cid)
        c=lookup[cid];span=dict(e,claim_id=cid)
        c['evidence'].append(span)
        if e['source_id'] not in c['source_ids']: c['source_ids'].append(e['source_id'])
        if e.get('quality')=='insufficient': c['status']='unsupported'
        elif c['status']!='unsupported' and (e.get('boundary') or e.get('quality')=='limited'): c['status']='bounded'
        c.pop('stale',None)
    return list(lookup.values())


def changed(a, before):
    """Invalidate only adopted source dependencies; new material is an incremental queue."""
    old=selected(before);new=selected(a);direction=objective(a)!=objective(before)
    affected={sid for sid in old if old[sid]!=new.get(sid)}
    added=set(new)-set(old)
    if not (direction or affected or added): return False
    r=a.get('research')
    if r:
        r['unassessed_source_ids']=sorted((set(r.get('unassessed_source_ids',[]))|added)&set(new))
        r['stale']=bool(direction or affected)
        from .flow_state import issues
        r['issues']=copy.deepcopy(issues(before))
        for issue in r['issues']:
            if direction or affected.intersection(issue.get('source_ids',[])): issue['status']='stale'
        if direction:
            r.pop('resume_job_id',None);r.pop('resume_stage',None)
    for claim in a.get('evidence',{}).get('claims',[]):
        if direction or affected.intersection(claim.get('source_ids',[])): claim['stale']=True
    if (direction or affected) and (a.get('evidence') or r): a['stages']['sources']='stale'
    return True


def material_view(a):
    from .flow_state import issues
    r=a.get('research',{});rows=issues(a)
    required=[x for x in rows if x.get('kind')=='blocking' and x.get('status') in ('open','stale')]
    boundaries=[x for x in rows if x.get('kind')=='limitation' and x.get('status') in ('open','stale') or x.get('status')=='bounded']
    new=r.get('unassessed_source_ids',[])
    claims=a.get('evidence',{}).get('claims',[])
    legacy_ready=not r.get('policy_version') and ((bool(r) and not r.get('pending')) or (a['stages']['sources']=='done' and bool(a.get('evidence'))))
    usable=bool(claims or r.get('evidence') or legacy_ready) and not r.get('stale')
    if new: state='new_materials';message=f'{len(new)} 条新采用的材料尚未纳入判断';action='verify_new'
    elif r.get('stale'): state='changed';message='相关依据或文章目标已变化，需要更新对应判断';action='verify'
    elif required: state='gaps';message=f'{len(required)} 项高优先级建议待处理，可带限定继续创作';action='continue' if r.get('next_queries') and not r.get('exhausted') else 'supplement'
    elif usable: state='ready';message='当前资料可进入大纲，请保留以下写作边界';action='outline'
    else: state='initial';message='先检查已有材料，再按缺口查找资料';action='collect'
    delta=r.get('delta')
    if not isinstance(delta,dict) or not all(isinstance(delta.get(k),int) for k in ('added_sources','resolved','remaining')):delta=None
    pending=sorted([x for x in rows if x.get('status') in ('open','stale')],key=lambda x:x.get('priority')!='high')
    return dict(state=state,message=message,action=action,ready=usable,required=required,boundaries=boundaries,pending=pending,
        handled=[x for x in rows if x.get('status') in ('resolved','bounded','excluded','waived')],
        new_source_ids=new,delta=delta,delta_job_id=r.get('job_id',''),stop_reason=r.get('stop_reason',''))
