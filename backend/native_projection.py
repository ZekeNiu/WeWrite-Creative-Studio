"""Lossless native artifacts -> existing editable workbench fields."""
import re
import yaml
from .models import SCHEMAS


def mapping(path):
    value=yaml.safe_load(path.read_text('utf-8'))
    if not isinstance(value,dict):raise ValueError('上游产物不是有效对象：'+path.name)
    return value


def body(text):
    return re.sub(r'\A\s*# [^\n]+\n+', '', text).strip()


def brief_from_article(a):
    b=a['brief']; o=a.get('outline',{}); plan=a.get('creative_intent',{}).get('selected',{})
    native=a.get('native_brief',{})
    result=dict(version=1,audience=dict(who=b['audience'],context=b.get('purpose',''),question=o.get('reader_question') or plan.get('reader_question') or b['topic']),
        goal=dict(takeaway=o.get('takeaway') or plan.get('takeaway',''),action=plan.get('takeaway','')),
        thesis=dict(statement=o.get('thesis',b['topic']),novelty=plan.get('novelty',''),boundary=o.get('boundary',''),counterpoint=o.get('counterpoint','')),
        personal_materials=dict(available=any(s.get('personal_material') and s.get('selected') for s in a['sources']),items=[s['id'] for s in a['sources'] if s.get('personal_material') and s.get('selected')]),
        framework=a.get('native_brief',{}).get('framework',''),sections=o.get('sections',[]),
        constraints=dict(desired_length=str(b['words'])+'字',must_include=[b['include']] if b.get('include') else [],must_avoid=[b['avoid']] if b.get('avoid') else []))
    # Keep native fields without letting them supersede later human edits.
    for key in ('audience','goal','thesis'):
        result[key]={**native.get(key,{}),**{k:v for k,v in result[key].items() if v}}
    result['sections']=o.get('sections') or native.get('sections',[])
    return {**native,**result}


def project(stage,directory,state,review_final=None):
    if stage in ('write','revise'):
        text=body((directory/('draft.md' if stage=='write' else 'replacement.md')).read_text('utf-8'))
        if not text:raise ValueError('正文产物为空，未应用')
        return text
    if stage=='topic':
        raw=mapping(directory/'topics.yaml').get('topics',[])
        result=dict(topics=[dict(id=x.get('id',''),title=x['title'],angle=x.get('angle') or x.get('framework') or x['title'],
            reason=x.get('reason') or str(x.get('score','')),**{k:v for k,v in x.items() if k in ('audience','source_ids','reader_question','novelty','takeaway','questions','key_claims')}) for x in raw])
    elif stage=='sources':
        brief=mapping(directory/'brief.yaml');claims=mapping(directory/'claims.yaml')
        result=dict(summary=claims.get('summary') or brief['thesis']['statement'],claims=claims['claims'],gaps=claims.get('gaps',[]))
    elif stage=='outline':
        brief=mapping(directory/'brief.yaml')
        result=dict(thesis=brief['thesis']['statement'],reader_question=brief['audience']['question'],takeaway=brief['goal']['takeaway'],
            counterpoint=brief['thesis'].get('counterpoint',''),boundary=brief['thesis'].get('boundary',''),
            sections=[dict(id=s.get('id') or 'section-'+str(i+1),title=s.get('title') or s['purpose'],purpose=s['purpose'],
                points=s.get('points',[]),claim_ids=s.get('claim_ids',[])) for i,s in enumerate(brief['sections'])])
    elif stage in ('review','edit'):
        from wewrite.commands.content_eval import build_report
        assessment=mapping(directory/'assessment.yaml')
        draft=(directory/'draft.md').read_text('utf-8')
        final=(review_final or directory/'article.md').read_text('utf-8')
        report=build_report(draft,final,assessment)
        saved=mapping(directory/'review-report.json')
        if saved!=report:raise ValueError('报告与当前稿件不一致，请对当前稿件执行 content-eval')
        if report['publishable'] and (not (directory/'article.md').exists() or (directory/'article.md').read_text('utf-8')!=final):raise ValueError('通过审稿后须保存对应 article.md')
        # Recompute from real artifacts; never trust a model-written publishable flag.
        issues=[]
        for severity, key in [('blocker','blockers'),('major','major_issues'),('minor','minor_issues')]:
            for i,x in enumerate(assessment.get(key,[])):
                detail=x if isinstance(x,dict) else dict(reason=str(x))
                issues.append(dict(id=f'{key}-{i}',severity=severity,quote=detail.get('quote',''),reason=detail.get('reason') or str(x),suggestion=detail.get('suggestion',''),source_ids=detail.get('source_ids',[]),status='pending'))
        seo=state.get('seo',{})
        result=dict(decision='pass' if report['publishable'] else assessment['decision'] if assessment['decision']!='pass' else 'revise',
            summary=assessment.get('notes') or ('编辑已通过' if report['publishable'] else '稿件仍需修改'),issues=issues,dimensions=assessment['dimensions'],
            title=seo.get('title',''),alt_titles=seo.get('alt_titles',[]),digest=seo.get('digest',''),tags=seo.get('tags',[]),
            _content=body(final),_report=report)
        return result
    elif stage=='visual':
        value=yaml.safe_load((directory/'images.json').read_text('utf-8'))
        rows=value.get('images',[]) if isinstance(value,dict) else value
        result=dict(images=[dict(id=x.get('id') or 'image-'+str(i+1),role=x.get('role','cover' if i==0 else 'article'),
            prompt=x['prompt'],caption=x.get('caption',''),after_heading=x.get('after_heading','')) for i,x in enumerate(rows)])
    else:raise ValueError('此阶段尚无原生投影')
    return SCHEMAS[stage].model_validate(result).model_dump()
