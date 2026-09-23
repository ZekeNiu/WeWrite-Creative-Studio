"""SQLite account decisions projected into upstream files, without a second learner."""
import hashlib
import json
from datetime import datetime
from . import store


def lesson_rows(value, article):
    from .account_memory import timestamp
    rows = {}
    for rule in value['rules']:
        if rule['status'] not in ('soft', 'confirmed'): continue
        if rule['scope'] != 'account' and rule['column'] != article['brief']['column']: continue
        pattern = dict(rule.get('native_pattern') or {})
        pattern.update(key=pattern.get('key') or hashlib.sha256((rule['category']+rule['text']).encode()).hexdigest()[:20],
                       type=pattern.get('type', 'structure' if rule['category']=='structure' else 'expression'),
                       rule=rule['text'], description=rule['text'], confirmed=rule['status']=='confirmed')
        pattern.setdefault('scope', 'global'); pattern.setdefault('scope_value', '')
        field = {'persona':'persona', 'framework':'framework', 'content_type':'content_type'}.get(pattern['scope'])
        effective={**article.get('native_brief',{}),**article['brief']}
        if field and effective.get(field) != pattern['scope_value']: continue
        # The upstream confidence function expects local, timezone-naive timestamps.
        sources=rule['sources'] or [dict(id=rule['id'],created=rule['updated'])]
        if rule.get('learning_reset_at'):
            sources=[dict(id=rule['id'],created=rule['learning_reset_at']),*[s for s in rule['sources'] if s.get('created','')>rule['learning_reset_at']]]
        for source in sources:
            stamp=timestamp(source.get('created') or rule['updated']).astimezone().replace(tzinfo=None).isoformat()
            row=rows.setdefault(source['id'], dict(date=stamp[:10],timestamp=stamp,patterns=[]))
            if not any(p['key']==pattern['key'] and p['scope']==pattern['scope'] and p['scope_value']==pattern['scope_value'] for p in row['patterns']):
                row['patterns'].append(dict(pattern, studio_rule_id=rule['id']))
    return rows


def references(value, article):
    from wewrite.commands.learn_edits import aggregate_patterns
    lessons=lesson_rows(value, article)
    patterns=aggregate_patterns(list(lessons.values()))
    rules=[]
    for p in patterns:
        if p['confidence']<2 and not p['confirmed']: continue
        ids={r['studio_rule_id'] for l in lessons.values() for r in l['patterns'] if (r['key'],r['scope'],r['scope_value'])==(p['key'],p['scope'],p['scope_value'])}
        original=next(r for r in value['rules'] if r['id'] in ids)
        rules.append({k:original[k] for k in ('id','category','text','status','scope','column')} |
                     dict(weight=p['confidence']/10,confidence=p['confidence'],hard=p['hard'],count=p['occurrences'],
                          native_pattern=p,source_pair_ids=[s['id'] for s in original['sources']]))
    available=[x for x in value['examples'] if x['status']=='confirmed' and (x['scope']=='account' or x['column']==article['brief']['column'])]
    wanted=exemplar(article.get('content') or article['brief'].get('topic',''),'')['category']
    available.sort(key=lambda x:(x.get('native',{}).get('category')!=wanted,x['column']!=article['brief']['column'],x['id']))
    examples=[]
    for x in available[:2]:
        examples.append({k:x[k] for k in ('id','title','rules','scope','column','text','source')} |
                        dict(ownership=x.get('ownership','third_party'),authenticity=x.get('authenticity','unverified'),
                             allowed_uses=['style','structure'],personal_materials_reusable=False))
    return rules,examples,lessons


async def materialize(session):
    from .native_runtime import dump
    c=session.used['context'];b=session.article['brief'];p=c['profile']
    from .native_catalog import persona
    dump(session.home/'personas'/(b['persona']+'.yaml'),persona(b['persona']))
    from .account_memory import get
    value=get()
    for entry in value.get('themes',[]):dump(session.home/'themes'/(entry['id']+'.yaml'),entry['definition'])
    dump(session.home/'style.yaml',dict(name=b['column'],industry=b.get('domain',''),topics=[p['direction']] if p['direction'] else [b.get('domain') or b['column']],
        writing_persona=b['persona'],tone=b['tone'],voice=p['expression'],word_count=str(b['words']),
        target_audience=b['audience'] or p['audience'],blacklist=dict(words=[],topics=[p['avoid']] if p['avoid'] else []),
        theme=session.article['layout']['theme'],author=session.article['layout'].get('author','')))
    from .account_memory import history
    rows=[r for r in history(page_size=1000000)['items'] if (session.stage=='stats' or r['article_id']!=session.article['id']) and r['status']!='trash']
    online=value.get('online_metrics',[])
    history_rows=[]
    for r in rows:
        item=dict(r,date=(r.get('published_at') or r['created'])[:10],run_id=r['article_id'])
        matches=[x for x in online if x['article_id']==r['article_id']]
        if matches:
            last=max(matches,key=lambda x:x['observed_at']);item['stats']=last['stats'];item['stats_observed_at']=last['observed_at']
        manual=[x for x in value['metrics'] if x['article_id']==r['article_id']]
        if manual:
            item['manual_metrics']=manual
            if not matches:
                last=max(manual,key=lambda x:x['observed_at'])
                item['stats']=dict(read_count=last['reads'],share_count=last['shares'],like_count=last['likes'],save_count=last['saves'])
                item['stats_observed_at']=last['observed_at'];item['stats_window_hours']=last['window_hours']
        history_rows.append(item)
    dump(session.home/'history.yaml',dict(version=1,articles=history_rows))
    for key,lesson in c.get('native_lessons',{}).items():dump(session.home/'lessons'/('studio-diff-'+key+'.yaml'),lesson)
    summary=json.loads(await session.cli(['learn-edits','--summarize','--json']))
    dump(session.home/'learning-summary.json',summary)
    playbook=['# 编辑偏好（上游汇总）','本篇明确要求优先。栏目与停用范围已在输入中筛选。']
    for p in summary['patterns']:
        if p['confidence']>=2 or p['confirmed']:
            playbook.append(f"- {'硬规则' if p['hard'] else '软参考'} [{p['scope']}:{p['scope_value'] or '*'}] {p['rule']}（{p['occurrences']} 次，置信度 {p['confidence']}）")
    (session.home/'playbook.md').write_text('\n'.join(playbook),encoding='utf-8')
    for x in c['examples']:
        path='account-inputs/'+x['id']+'.md';(session.home/'account-inputs').mkdir(exist_ok=True)
        (session.home/path).write_text(x['text'],encoding='utf-8')
        args=['exemplar',path,'--source',x['title'],'--json']
        if x['ownership']=='user':args.append('--user-authored')
        await session.cli(args,True)


async def prepare_learning(session):
    from .native_runtime import dump
    source=session.request['_learning_source'];folder=session.home/'account-inputs';folder.mkdir(exist_ok=True)
    for key,text in source.items():(folder/(key+'.md')).write_text(text,encoding='utf-8')
    before=set((session.home/'lessons').glob('*-diff*.yaml'))
    await session.cli(['learn-edits','--draft','account-inputs/ai.md','--final','account-inputs/human.md'],True)
    added=set((session.home/'lessons').glob('*-diff*.yaml'))-before
    if len(added)!=1:raise ValueError('上游没有生成唯一的改稿学习记录')
    session.lesson=added.pop()
    dump(session.home/'learning-task.json',dict(draft='account-inputs/ai.md',final='account-inputs/human.md',lesson=session.lesson.relative_to(session.home).as_posix()))


def learning_result(session):
    from .native_projection import mapping
    from wewrite.commands.learn_edits import PATTERN_TYPES
    lesson=mapping(session.lesson);patterns=lesson.get('patterns')
    if not isinstance(patterns,list):raise ValueError('学习记录须包含 patterns 列表')
    result=[];seen=set()
    for p in patterns:
        if not isinstance(p,dict) or p.get('type') not in PATTERN_TYPES or not all(isinstance(p.get(k),str) and p[k].strip() for k in ('key','description','rule')):raise ValueError('学习条目缺少上游类型、key、描述或规则')
        if p.get('scope') not in ('global','content_type','framework','persona') or not isinstance(p.get('scope_value',''),str):raise ValueError('学习范围无效')
        if p.get('confirmed'):raise ValueError('长期偏好须由用户在界面明确确认')
        key=(p['key'],p['scope'],p.get('scope_value',''))
        if key in seen:raise ValueError('同一次人工改稿不能重复计数')
        seen.add(key)
        result.append(dict(category='structure' if p['type'] in ('structure','title','para_add','para_delete') else 'expression',text=p['rule'],native_pattern=p))
    return dict(rules=result,lesson=lesson)


async def learn(article,jid,value,source):
    from .native_runtime import generate
    packet=await generate(article,jid,'learn',dict(instruction='学习已明确选择的人工改稿对。读取 learning-task.json，完成上游学习与总结。',_learning_source=source))
    return packet['result']


def exemplar(text,source,user_authored=False,edited=False):
    from wewrite.commands.extract_exemplar import extract_exemplar
    return extract_exemplar(text,source=source,ownership='user' if user_authored else 'third_party',
                            authenticity='user_edited' if edited else 'user_authored' if user_authored else 'unverified')
