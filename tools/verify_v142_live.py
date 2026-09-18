"""Billable isolated acceptance: one analysis call also generates source purposes."""
import asyncio
import json
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import store,providers,materials,workflow,source_use
from backend.models import JobRequest
from tools.verify_v141_live import integrity


async def main():
    production=store.DATA;before=integrity(production/'studio.sqlite')
    folder=store.ROOT/'output/test-workspaces/live-v142'
    if folder.exists(): raise ValueError('Inspect the existing paid result before creating another test workspace')
    folder.mkdir(parents=True)
    with sqlite3.connect(production/'studio.sqlite') as src,sqlite3.connect(folder/'studio.sqlite') as dst:src.backup(dst)
    store.DATA=folder;store.init()
    cfg=store.get_settings();cfg['search']['enabled']=False;store.set_settings(cfg)
    a=store.create_article(dict(topic='怎样把阅读材料整理成有依据的写作提纲',purpose='基于所给编辑规范提供步骤，不声称实证效果',words=600),diagnostic=True)
    sources=[materials.source('编辑规范：事实与建议','规范说明：先记录来源中的具体判断，再注明适用范围。事实、推断和编辑建议应分别标记。资料本身不能支持的数字不写成确定结论。'),
             materials.source('写作提纲检查表','检查表：每节说明要回答的问题，关联支持该判断的素材，注明材料未覆盖的范围。上传的范文或他人叙述不得直接写成作者个人经历。')]
    sources[0]['use']='用于说明事实、推断与建议的区别，保留材料边界。'
    a=store.save_article(a['id'],a['revision'],lambda v:v.update(sources=sources),'Isolated live fixture')
    report=dict(simulated=False,article_id=a['id'],calls=[],steps=[],passed=False)
    original=providers.generate
    async def capture(s,system,prompt,emit=None):
        v=json.loads(prompt);ctx=v.get('资料与当前内容',{})
        report['calls'].append(dict(schema=v.get('schema',{}).get('title','write'),uses=[x['use'] for x in ctx.get('sources',[])],experience_flags=[x['author_experience_allowed'] for x in ctx.get('sources',[])]))
        return await original(s,system,prompt,emit)
    providers.generate=capture
    try:
        for stage in ('sources','outline','write'):
            j=workflow.start(a['id'],JobRequest(stage=stage,revision=a['revision'],chain=False))
            print('Running '+stage,flush=True)
            while j['id'] in workflow.TASKS: await asyncio.sleep(2)
            j=store.job(j['id']);report['steps'].append(dict(stage=stage,status=j['status'],message=j['message']))
            if j['status']!='completed':raise ValueError(j['message'])
            a=store.get_article(a['id'])
            if stage=='sources':
                assert all(source_use.current(a,s) for s in a['sources']), 'Model omitted source purposes'
                assert a['sources'][0]['use']==sources[0]['use']
        assert len(report['calls'])==3 and report['calls'][0]['schema']=='EvidenceResult'
        assert report['calls'][1]['uses'][0]==sources[0]['use'] and report['calls'][1]['uses'][1]
        assert not any(flag for call in report['calls'] for flag in call['experience_flags'])
        assert a['outline']['sections'] and a['content'].strip()
        report.update(passed=True,source_count=len(a['sources']),content_characters=len(a['content']))
    except Exception as exc:report['error']=str(exc);raise
    finally:
        report['production_unchanged']=integrity(production/'studio.sqlite')==before
        report['usage']=store.usage(a['id'])
        p=store.ROOT/'output/diagnostics/live-v142.json';p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
        print(json.dumps({k:report.get(k) for k in ('passed','production_unchanged','error')}),flush=True)


if __name__=='__main__':asyncio.run(main())
