"""One current evidence record, scoped dependencies, and a shared material view."""
import copy
import hashlib
import json
import re

SOURCE_IDENTITY_FIELDS=('title','url','original_url','read_url','access_scope','identity_verified','identity_status','metadata_provenance')


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def objective(a):
    from .creative import intent
    return [ {k:a['brief'].get(k) for k in ('topic','column','domain','audience','purpose','include','avoid','recent_days')}, intent(a).get('selected') ]


def source_key(s):
    return digest({k:s.get(k) for k in ('id','selected','text','use','personal_material','bibliography')+SOURCE_IDENTITY_FIELDS})


def selected(a):
    return {s['id']:source_key(s) for s in a['sources'] if s.get('selected',True)}


def dependency(a, issue):
    ids=issue.get('source_ids',[])
    sources=selected(a)
    return digest([objective(a),{sid:sources.get(sid) for sid in ids}])


def normal(text):
    return re.sub(r'\s+','',text).casefold()


def evaluated(e):
    from .research_contract import semantic_valid
    return (semantic_valid(e) and e.get('support') in ('supported','limited','contradicted','unsupported') and
            e.get('quality') in ('suitable','limited','insufficient') and e.get('verification')=='quote_matched' and
            all(str(e.get(k,'')).strip() for k in ('source_type','adoption_reason','use_scope')) and
            (e.get('quality')!='limited' or bool(e.get('boundary','').strip())))


def assessed(e):
    return evaluated(e) and e.get('support') in ('supported','limited') and e.get('quality') in ('suitable','limited')


def span_summary(spans):
    """Summaries preserve verified wording and never silently promote rejected claims."""
    rows=[]
    for e in spans:
        label=('适用性待复核' if not evaluated(e) else '缺少支持' if not assessed(e)
               else '有限支持' if e.get('support')=='limited' or e.get('quality')=='limited' or e.get('boundary') else '已有支持')
        row=label+'：'+e['claim']+('；边界：'+e['boundary'] if e.get('boundary') else '')
        basis={'author_interpretation':'作者解释','external_reference':'转引其他研究'}.get(e.get('support_basis'))
        if basis:row+='；依据类型：'+basis
        if row not in rows:rows.append(row)
    return '\n'.join(rows)


def current_spans(a):
    return [e for c in a.get('evidence',{}).get('claims',[]) if not c.get('stale') for e in c.get('evidence',[])]


def project(a):
    """Current claims own evidence; source details are only a projection."""
    if 'claims' not in a.get('evidence',{}):return
    spans=current_spans(a)
    for c in a['evidence']['claims']:
        evidence=c.get('evidence',[])
        c['status']='unsupported' if not evidence or any(not assessed(e) for e in evidence) else 'bounded' if any(e.get('quality')=='limited' or e.get('boundary') for e in evidence) else 'supported'
        if evidence:c['boundary']='；'.join(dict.fromkeys(e['boundary'] for e in evidence if e.get('boundary')))
        if not c.get('evidence') or any(not evaluated(e) for e in c['evidence']):
            c['status']='unsupported';c['assessment_pending']=True
        else:c.pop('assessment_pending',None)
    pending={c['id'] for c in a['evidence']['claims'] if c.get('assessment_pending')}
    for issue in a.get('research',{}).get('issues',[]):
        if issue.get('status')=='resolved' and (issue.get('claim_id') in pending or any(c['id'] in pending and normal(c['text'])==normal(issue.get('claim','')) for c in a['evidence']['claims'])):
            issue.update(status='open',resolution='原核实记录缺少完整的适用性评估，请复核')
    for source in a['sources']:
        source['evidence_spans']=[copy.deepcopy(e) for e in spans if e['source_id']==source['id']]
        source['summary']=span_summary(source['evidence_spans'])
    summary='\n'.join(('依据待更新' if c.get('stale') else '适用性待复核' if c.get('assessment_pending') else '有限支持' if c.get('status')=='bounded' else '缺少支持' if c.get('status')=='unsupported' else '已有支持')+'：'+c['text']+('；边界：'+c['boundary'] if c.get('boundary') else '') for c in a['evidence']['claims'])
    a['evidence']['summary']=summary
    if a.get('research'):
        a['research']['evidence']=copy.deepcopy(spans)
        a['research']['summary']=summary


def merge_issues(a, notes, requested=()):
    from .flow_state import issues,issue_id
    old=issues(a);lookup={x['id']:x for x in old}; rows={x['id']:copy.deepcopy(x) for x in old}
    for x in rows.values():
        if x.get('status')=='resolved' and (not requested or x['id'] in requested):
            x.update(status='open',resolution='本轮尚未取得新的有效支持')
    seen=set()
    if any(assessed(e) for e in notes.get('evidence',[])):
        for x in rows.values():
            if x.get('system_kind')=='no_evidence': x.update(status='resolved',resolution='已取得可定位的原文支持')
    for raw in notes.get('issues',[]):
        item=dict(raw);iid=item.get('id')
        if iid not in lookup:
            match=next((x for x in old if (item.get('claim_id') and item['claim_id']==x.get('claim_id')) or
                normal(item['text'])==normal(x['text']) or (item.get('claim') and normal(item['claim'])==normal(x.get('claim','')))),None)
            iid=match['id'] if match else item['id'] if item.get('system_kind')=='no_evidence' else issue_id(item['text'],item.get('source_ids',[]))
        if requested and iid in lookup and iid not in requested: continue
        duplicates=[x for x in item.get('merged_ids',[]) if x in lookup and x!=iid and (not requested or x in requested)]
        protected=[x for x in [iid]+duplicates if x in a.get('research_decisions',{})]
        if len(protected)>1:duplicates=[]
        elif protected and protected[0]!=iid:
            duplicates=[x for x in [iid]+duplicates if x!=protected[0]];iid=protected[0]
        for duplicate in duplicates:
            item['source_ids']=list(dict.fromkeys(item.get('source_ids',[])+lookup[duplicate].get('source_ids',[])))
            rows.pop(duplicate,None)
        item['merged_ids']=duplicates
        evidence=[e for e in notes.get('evidence',[]) if assessed(e) and e.get('quality')=='suitable' and
            ((item.get('claim') and normal(item['claim'])==normal(e['claim'])) or
             (not item.get('claim') and item.get('claim_id') and item['claim_id']==e.get('claim_id')))]
        supported=bool(evidence) and bool(item.get('resolution'))
        if item.get('status')=='resolved' and not supported:item['resolution']='本轮尚未取得支持该完整主张的有效证据'
        item.update(id=iid,status='resolved' if item.get('status')=='resolved' and supported else 'open')
        if item['status']=='resolved':item['resolution']=span_summary(evidence)
        rows[iid]={**lookup.get(iid,{}),**item};seen.add(item['text'])
    for kind,key in [('blocking','gaps'),('limitation','conflicts')]:
        for text in notes.get(key,[]):
            if text in seen or any(normal(x['text'])==normal(text) for x in rows.values()): continue
            iid=issue_id(text);rows[iid]=dict(id=iid,text=text,kind=kind,status='open',source_ids=[],claim='')
    return issues(dict(a,research=dict(a.get('research',{}),issues=list(rows.values()))))


def merge_claims(a, spans, requested=()):
    claims=copy.deepcopy(a.get('evidence',{}).get('claims',[]));lookup={c['id']:c for c in claims}
    from .flow_state import issues
    target_claims={q.get('claim_id') for q in issues(a) if q['id'] in requested}
    target_texts={normal(q.get('claim','')) for q in issues(a) if q['id'] in requested}
    discovery=any(not q.get('claim_id') and not q.get('claim') for q in issues(a) if q['id'] in requested)
    for c in lookup.values():
        if not requested or c['id'] in target_claims or normal(c['text']) in target_texts:
            c.update(evidence=[],source_ids=[],status='unsupported',boundary='')
    touched=set()
    for e in spans:
        if requested and not discovery and e.get('claim_id') not in target_claims and normal(e.get('claim','')) not in target_texts:
            continue
        cid=e.get('claim_id')
        if cid not in lookup:
            same=next((c for c in claims if normal(c['text'])==normal(e['claim'])),None)
            cid=same['id'] if same else 'C'+digest(e['claim'])[:12]
        if requested and cid in lookup and cid not in target_claims and normal(lookup[cid]['text']) not in target_texts:
            continue
        if cid not in touched:
            old=lookup.get(cid,{})
            claim=dict(old,id=cid,text=e['claim'],type=e.get('type',old.get('type','fact')),
                source_ids=[],evidence=[],boundary=e.get('boundary',''),status='supported')
            lookup[cid]=claim;touched.add(cid)
        c=lookup[cid];span=dict(e,claim_id=cid)
        c['evidence'].append(span)
        if e['source_id'] not in c['source_ids']: c['source_ids'].append(e['source_id'])
        if not assessed(e): c['status']='unsupported'
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
    from .source_context import POLICY_VERSION
    r=a.get('research',{});rows=issues(a)
    required=[x for x in rows if (x.get('kind')=='blocking' and x.get('status') in ('open','stale')) or x.get('application_state') in ('pending','partial')]
    boundaries=[x for x in rows if x.get('kind')=='limitation' and x.get('status') in ('open','stale') or x.get('status')=='bounded']
    new=r.get('unassessed_source_ids',[])
    claims=a.get('evidence',{}).get('claims',[])
    legacy_ready=not r.get('policy_version') and ((bool(r) and not r.get('pending')) or (a['stages']['sources']=='done' and bool(a.get('evidence'))))
    usable=bool(claims or r.get('evidence') or legacy_ready) and not r.get('stale')
    unassessed=sum(bool(c.get('assessment_pending')) for c in claims)
    policy_changed=bool(r.get('policy_version') and r['policy_version']!=POLICY_VERSION)
    if new: state='new_materials';message=f'{len(new)} 条新采用的材料尚未纳入判断';action='verify_new'
    elif r.get('stale'): state='changed';message='相关依据或文章目标已变化，需要更新对应判断';action='verify'
    elif required: state='gaps';message=f'{len(required)} 项建议或稿件改动待处理，可带限定继续创作';action='continue' if r.get('next_queries') and not r.get('exhausted') else 'supplement'
    elif unassessed: state='gaps';message=f'{unassessed} 项主张适用性待复核，可查找并整理资料或带限定继续创作';action='verify'
    elif policy_changed: state='gaps';message='这份核查使用了旧证据政策，可继续创作，关键依据需要复核';action='verify'
    elif usable: state='ready';message='当前资料可进入大纲，请保留以下写作边界';action='outline'
    else: state='initial';message='先检查已有材料，再按缺口查找资料';action='collect'
    delta=r.get('delta')
    if not isinstance(delta,dict) or not all(isinstance(delta.get(k),int) for k in ('added_sources','resolved','remaining')):delta=None
    application_pending=[x for x in rows if x.get('application_state') in ('pending','partial')]
    pending=sorted([x for x in rows if (x.get('kind')=='blocking' and x.get('status') in ('open','stale')) or x in application_pending],key=lambda x:x.get('priority')!='high')
    return dict(state=state,message=message,action=action,ready=usable,required=required,boundaries=boundaries,pending=pending,
        handled=[x for x in rows if x.get('status') in ('resolved','bounded','excluded','waived') and x not in application_pending],
        application_pending=application_pending,
        new_source_ids=new,delta=delta,delta_job_id=r.get('job_id',''),stop_reason=r.get('stop_reason',''))


def sync(a):
    from .flow_state import issues
    project(a)
    if not a.get('research'):return
    a['research']['issues']=issues(a)
    view=material_view(a)
    a['research']['pending']=bool(view['required'])
    from .research_contract import sufficient,VERSION
    from .source_context import POLICY_VERSION
    a['research']['coverage_sufficient']=sufficient(a['research'].get('coverage',[])) and not a['research'].get('stale',False) and a['research'].get('policy_version')==POLICY_VERSION and a.get('research_contract',{}).get('version')==VERSION
    a['stages']['sources']='stale' if a['research'].get('stale') else 'needs_input' if view['pending'] or view['new_source_ids'] else 'done' if view['ready'] else 'idle'
