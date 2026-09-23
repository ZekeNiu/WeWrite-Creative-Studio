"""Synthetic model only. The production tool loop, files and upstream CLI run normally.

The legacy fixture responder supplies deterministic sample prose/objects; it is
never used by production and does not replace native execution or validation.
"""
import copy
import json
from backend import store,providers,prompts,agent_transport,native_projection,account_memory


def install(monkeypatch,responder=None):
    turns={}
    async def turn(service,system,messages,tools):
        task=json.loads(messages[0]['content']);run_id=task['run_id'];directory=task['run_dir']
        key=run_id;index=turns.get(key,0);turns[key]=index+1
        native=next(j for j in all_jobs() if j.get('native',{}).get('run_id')==run_id)
        req=native['request'];stage='learn' if req.get('kind')=='learn' else native['stage']
        a=store.get_article(req['article_id'] if stage=='learn' else native['article_id'])
        req={**req,'_account_use':dict(context=account_memory.context(a))}
        calls=[]
        def call(name,**args):calls.append(dict(id=str(index)+'-'+str(len(calls)),name=name,arguments=json.dumps(args,ensure_ascii=False)))
        def write(name,value):call('Write',path=directory+'/'+name,content=value if isinstance(value,str) else json.dumps(value,ensure_ascii=False))
        if stage=='learn':
            import yaml
            home=store.DATA/'native'/native['native']['id'];task=json.loads((home/'learning-task.json').read_text('utf-8'))
            if index==0:
                for path in (task['draft'],task['final'],task['lesson']):call('Read',path=path)
            elif index==1:
                raw,_=await providers.generate(service,system,json.dumps(dict(context=dict(ai=(home/task['draft']).read_text('utf-8'),human=(home/task['final']).read_text('utf-8')),schema=dict(title='StyleResult'))))
                lesson=yaml.safe_load((home/task['lesson']).read_text('utf-8'));lesson['patterns']=[]
                for r in json.loads(raw)['rules']:
                    p=dict(type='structure' if r['category']=='structure' else 'expression',key=r['text'],rule=r['text'],description=r['text'],scope='global',scope_value='',confirmed=False)
                    if p not in lesson['patterns']:lesson['patterns'].append(p)
                call('Write',path=task['lesson'],content=yaml.safe_dump(lesson,allow_unicode=True))
                call('WeWrite',args=['learn-edits','--summarize','--json'])
            else:call('Finish')
            return dict(wire=[dict(role='assistant',content=None,tool_calls=[dict(id=c['id'],type='function',function=dict(name=c['name'],arguments=c['arguments'])) for c in calls])],calls=calls,text='',usage=dict(status='completed',model=service['model'],estimated_cost=None))
        if index==0:
            for name in ('request.json','account-reference.yaml',directory+'/brief.yaml',directory+'/claims.yaml',directory+'/sources.yaml'):call('Read',path=name)
        elif index==1:
            if responder:result=await responder(stage,a,req,service)
            else:
                raw,usage=await providers.generate(service,system,prompts.prompt('review' if stage=='edit' else stage,a,req))
                result=json.loads(raw) if stage!='write' else raw
            if stage=='topic':write('topics.yaml',result)
            elif stage=='sources':write('claims.yaml',dict(version=1,**result))
            elif stage=='outline':
                brief=native_projection.brief_from_article(a)
                brief['thesis'].update(statement=result['thesis'],boundary=result.get('boundary',''),counterpoint=result.get('counterpoint',''))
                brief['audience']['question']=result['reader_question'];brief['goal']['takeaway']=result['takeaway'];brief['sections']=result['sections'];write('brief.yaml',brief)
            elif stage=='write':write('draft.md',result)
            elif stage=='revise':write('replacement.md',result['replacement'])
            elif stage=='visual':write('images.json',result)
            elif stage in ('review','edit'):
                final=result.get('content',a['content']+('\n\n## 理解边界\n\n先辨清证据能够回答什么，再决定如何应用。' if stage=='edit' else ''))
                write('article.md',final)
                assessment=dict(decision=result['decision'],pass_number=result.get('pass_number',1),dimensions=result['dimensions'],notes=result['summary'],blockers=[i for i in result['issues'] if i['severity']=='blocker'],major_issues=[i for i in result['issues'] if i['severity']=='major'],minor_issues=[i for i in result['issues'] if i['severity']=='minor'])
                write('assessment.yaml',assessment)
                call('WeWrite',args=['content-eval','--draft',directory+'/draft.md','--final',directory+'/article.md','--assessment',directory+'/assessment.yaml','--output',directory+'/review-report.json','--json'])
        else:call('Finish')
        return dict(wire=[dict(role='assistant',content=None,tool_calls=[dict(id=c['id'],type='function',function=dict(name=c['name'],arguments=c['arguments'])) for c in calls])],calls=calls,text='',usage=dict(status='completed',model=service['model'],estimated_cost=None))
    monkeypatch.setattr(agent_transport,'turn',turn)
    return turns


def all_jobs():
    with store.connection() as db:return [json.loads(row[0]) for row in db.execute('SELECT data FROM jobs')]
