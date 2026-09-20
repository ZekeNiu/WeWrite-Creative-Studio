"""Offline import/advice fixtures. Never loads production credentials or articles."""
import asyncio
import json
from tools.qa_sidebar_app import app
from backend import materials,providers,store
original_generate=providers.generate


async def read(url):
    await asyncio.sleep(.7)
    if 'failure' in url:raise ValueError('模拟：网页需要验证，公开副本暂不可用')
    if 'slow' in url:await asyncio.sleep(30)
    src=materials.source('模拟公开论文：运动与适用条件','研究只适用于给定条件。\n补充原文。',url,'web')
    src.update(access_scope='fulltext',doi='10.1234/mock',identity_verified=True,identity_status='identified',bibliography=dict(title=src['title'],year='2024',venue='模拟期刊',authors=['模拟作者'],doi='10.1234/mock',document_type='J'))
    return src


async def generate(s,system,prompt,emit=None):
    value=json.loads(prompt) if prompt.startswith('{') else {}
    if value.get('schema',{}).get('title')=='Result':
        issues=json.loads(value['task'].split('只处理这些建议：',1)[1].split('. 依据',1)[0])
        result=dict(decisions=[dict(issue_id=i['id'],wording='研究只支持限定条件下的关联，不能证明因果。',explanation='模拟定向限定，不联网。',edits=[dict(target='content',original='待改写的段落。',replacement='这是限定条件下的观察结果，不能证明因果。')]) for i in issues])
        await asyncio.sleep(.3)
        return json.dumps(result,ensure_ascii=False),dict(model='fixture',service='offline',estimated_cost=0,status='completed')
    return await original_generate(s,system,prompt,emit)


materials.from_url=read
providers.generate=generate
fixtures=json.loads((store.DATA/'fixtures.json').read_text('utf-8'))
template=store.get_article(fixtures['full'])
a=store.create_article({'topic':'导入与建议离线验收'})
def fill(v):
    for k in ('sources','evidence','research','outline','content','stages','current_stage'):v[k]=template[k]
a=store.save_article(a['id'],a['revision'],fill,'offline fixture')
(store.DATA/'import-fixture.json').write_text(json.dumps({'id':a['id']}),encoding='utf-8')
