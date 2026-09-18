"""Explicit billable acceptance, isolated credentials/data, resumable only by phase."""
import argparse
import asyncio
import json
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from backend import store,providers,capabilities,workflow,outputs,materials
from backend.models import CapabilityTest,JobRequest
from tools.verify_v141_live import integrity


async def probe():
    production=store.DATA;before=integrity(production/'studio.sqlite')
    folder=store.ROOT/'output/test-workspaces/live-v150'
    if not folder.exists():
        folder.mkdir(parents=True)
        with sqlite3.connect(production/'studio.sqlite') as src,sqlite3.connect(folder/'studio.sqlite') as dst: src.backup(dst)
    marker=folder/'probe-started.json'
    if marker.exists(): raise ValueError('Probe already attempted; inspect saved results, never replay unknown paid requests')
    marker.write_text(json.dumps({'started':store.now()}),'utf-8')
    store.DATA=folder;store.init();report={'simulated':False,'capabilities':[]}
    try:
        for kind in ('vision','search'):
            s=providers.effective_service('search') if kind=='search' else providers.service_for('vision')
            print('Testing '+kind+' actual relay capability',flush=True)
            try:
                result=await capabilities.test(s['id'],CapabilityTest(model=s['model'],kind=kind,protocol=s['protocol'] if kind=='search' else None))
                report['capabilities'].append(dict(kind=kind,status=result['status'],message=result['message'],usage=result.get('usage')))
            except Exception as exc:
                report['capabilities'].append(dict(kind=kind,status='failed',message=str(exc)))
            (folder/'probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    finally:
        report['production_unchanged']=before==integrity(production/'studio.sqlite')
        (folder/'probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
        print(json.dumps(report,ensure_ascii=True),flush=True)


async def case(name):
    production=store.DATA;before=integrity(production/'studio.sqlite')
    store.DATA=store.ROOT/'output/test-workspaces/live-v150'
    report_path=store.DATA/('case-'+name+'.json')
    if report_path.exists(): raise ValueError('Case already attempted; inspect artifacts before a separate follow-up')
    cfg=store.get_settings()
    # Public group price verified at the user's supplied page. Only the isolated copy changes.
    for s in cfg['services']:
        if s['model']=='gemini-3.8-flash': s.update(input_price=.75,output_price=3.75,currency='CNY')
    store.set_settings(cfg)
    title,body=(('夜跑之前先看清环境','## 看清脚下的路\n\n选择照明充分、路面连续且人车冲突较少的路线。这里讨论出发前的环境检查，不评价具体运动姿势。\n\n## 出发前检查装备\n\n把鞋、手机与反光配件放好，确认需要的物品可以随手拿到。配图只展示一般场景，不虚构实际赛事或人物。') if name=='scene' else
                ('读懂腘绳肌示意图的边界','## 从后侧视图认识位置\n\n腘绳肌解剖图用于认识大腿后侧结构，应保留原图中的方向和标注，不能用发光皮肤叠加效果代替解剖示意。\n\n## 图片不是诊断\n\n示意图不能确定个人疼痛来源，也不构成训练动作教学。配图只解释位置，不能凭图给出损伤或治疗结论。'))
    a=store.create_article(dict(topic=title,purpose='配图真实验收；围绕具体章节选图，封面自然克制，不作医疗建议'),diagnostic=True)
    a=store.save_article(a['id'],a['revision'],lambda v:v.update(content=body,current_stage='visual',visual=dict(enabled=True,count=2,size='1536x1024',budget=8)),'Isolated visual live case')
    report=dict(simulated=False,article_id=a['id'],case=name,steps=[],passed=False,pricing_source='https://apikey.fun/pricing',image_price_note='Retained existing conservative estimate; not a billing receipt')
    def save():report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    save()
    async def run(stage,**kw):
        nonlocal a
        j=workflow.start(a['id'],JobRequest(stage=stage,revision=a['revision'],chain=False,**kw));print('Running '+name+' '+stage,flush=True)
        while j['id'] in workflow.TASKS:await asyncio.sleep(2)
        j=store.job(j['id']);report['steps'].append({k:j.get(k) for k in ('id','stage','status','message','visual_log')});a=store.get_article(a['id']);save()
        if j['status'] in ('failed','conflict','cancelled'):raise ValueError(j['message'])
    try:
        await run('visual')
        report['plans']=a['image_plans'];save()
        for plan in a['image_plans']:await run('image',image_id=plan['id'])
        report['images']=[{k:i.get(k) for k in ('id','filename','role','origin','caption','after_heading','selected','check','source_url','rights')} for i in a['images']]
        if any(i.get('selected') for i in a['images']):report['archive']=outputs.archive(a)['path']
        report['passed']=any(i.get('selected') and i['role']=='cover' for i in a['images'])
    except Exception as exc:report['error']=str(exc);raise
    finally:
        report['usage']=store.usage(a['id']);report['production_unchanged']=integrity(production/'studio.sqlite')==before;save()
        print(json.dumps({k:report.get(k) for k in ('case','passed','production_unchanged','error','archive')},ensure_ascii=True),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--probe',action='store_true');parser.add_argument('--case',choices=['scene','anatomy']);args=parser.parse_args()
    if args.probe: asyncio.run(probe())
    elif args.case: asyncio.run(case(args.case))
