"""Original-home and UI presentation acceptance. Synthetic QA server only, no model calls."""
import asyncio
import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from playwright.async_api import async_playwright, expect

BASE=os.environ.get('QA_BASE','http://127.0.0.1:8977')
OUT=Path(__file__).resolve().parents[1]/'output/playwright/v231'
LABELS=('选题','素材','大纲','写作','审核修改','配图','排版导出')


async def main():
 OUT.mkdir(parents=True,exist_ok=True)
 async with async_playwright() as p:
  browser=await p.chromium.launch(channel='msedge',headless=True)
  context=await browser.new_context(viewport=dict(width=1440,height=1000))
  await context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(BASE) else route.abort())
  page=await context.new_page();page.set_default_timeout(15000)
  fixture=await page.request.get(BASE+'/api/qa-fixture')
  assert fixture.ok,'Run only against qa_reliability_app.py'
  aid=(await fixture.json())['id']
  a=await (await page.request.get(BASE+'/api/articles/'+aid)).json()
  a.update(title='把恢复写进训练计划：跑得更好，也要休息得更好',current_stage='topic',word_count=219)
  a['brief'].update(topic=a['title'],domain='训练与恢复',words=2500,audience='大众科普')
  a['input_drafts']=dict(topic=a['title'],topic_feedback='面向业余跑者，从常见误区切入，保留研究的适用边界。')
  titles=['休息也是训练的一部分：如何读懂身体的恢复信号','跑量之外，哪些习惯会影响你的训练状态？','别急着加量：让训练与恢复形成自己的节奏','从疲劳到适应，中间发生了什么？']
  a['topics']=[dict(id='T'+str(i),title=t,angle='从日常观察出发，解释训练与恢复之间的关系。',reason='让读者建立可实践的观察方法。',novelty='结合训练日记，识别值得关注的变化。',reader_question='怎样理解自己的恢复状态？',takeaway='找到适合自己的训练节奏',source_ids=[]) for i,t in enumerate(titles)]
  a['outline']=dict(thesis='训练的效果，来自负荷与恢复的共同作用。',reader_question='如何为自己安排恢复？',takeaway='建立可持续的训练习惯',counterpoint='',boundary='保留研究适用条件',sections=[dict(id='intro',title='先理解疲劳，再安排下一次训练',purpose='从熟悉的训练体验切入',points=['观察主观疲劳与睡眠','避免用单一指标判断状态'],claim_ids=[]),dict(id='practice',title='把观察变成可执行的安排',purpose='给出具体的调整思路',points=['记录而不急于判断','在持续变化中寻找规律'],claim_ids=[])])
  a['content']='## 先理解疲劳，再安排下一次训练\n\n一次训练结束后，我们往往习惯问：今天跑了多少公里，配速又快了多少？但还有一个同样值得记录的问题：身体为这次训练付出了多少，又需要多久才能恢复？\n\n训练计划里的空白，并不意味着没有进步。休息让我们有机会观察变化，也让下一次训练有更好的起点。\n\n## 把观察变成可执行的安排\n\n先从简单的训练日记开始：记下睡眠、主观疲劳和训练感受。连续几天的变化，通常比某一天的数字更值得留意。\n\n这是一份用于界面验收的示例稿。'
  for stage in a['stages']:a['stages'][stage]='done'
  for gate in a['workflow'].values():gate.update(allowed=True,reason='')
  a['research']['pending']=False
  a['review'].update(summary='表达清晰，部分论述仍需补充适用条件。',issues=[dict(id='R1',status='pending',severity='major',reason='补充建议的适用条件，让读者更容易理解边界。',quote='休息让我们有机会观察变化',suggestion='适当休息也提供了观察训练状态的机会。',source_ids=[]),dict(id='R2',status='rejected',severity='minor',reason='这条表达意见已处理。',quote='',suggestion='',source_ids=[])])
  a['visual'].update(enabled=True)
  a['image_plans']=[dict(id='cover',role='cover',prompt='清晨的公园与慢跑步道，柔和自然光，留出标题空间。',caption='给训练，也给恢复留一点时间。')]
  a['images']=[];a['editorial_candidates']=[];a['draft_versions']=[]
  a['latest_job']=dict(id='old-topic',stage='topic',status='needs_input',message='选择一个候选主题')
  stamp=datetime.now(timezone.utc).isoformat()
  old_job=dict(id='old-topic',article_id=aid,stage='topic',status='needs_input',message='选择一个候选主题',request=dict(stage='topic',chain=False),created=stamp)
  jobs=[old_job]
  failed=copy.deepcopy(a);failed.update(id='synthetic-failure-card',title='当训练节奏被打乱，怎样重新找到适合自己的起点？',current_stage='topic',latest_job=dict(id='failed-card',stage='topic',status='failed',message='连接中断'))
  rows=[];errors=[]
  page.on('pageerror',lambda e:errors.append(str(e)))
  async def library(route):
   query=parse_qs(urlparse(route.request.url).query).get('query',[''])[0]
   filtered=[r for r in rows if not query or query in r['title']]
   await route.fulfill(json=dict(items=filtered,total=len(filtered),page=1,page_size=20))
  async def article(route):
   assert route.request.method=='GET','Visual acceptance must not modify an article'
   await route.fulfill(json=a)
  async def job_list(route):
   assert route.request.method=='GET','Visual acceptance must not start jobs'
   await route.fulfill(json=jobs)
  async def job_detail(route):await route.fulfill(json=jobs[0])
  async def preview(route):
   html='<html><body style="font:16px/1.8 sans-serif;color:#25372f;padding:16px"><h2 style="font-size:21px;color:#266447">先理解疲劳，再安排下一次训练</h2><p>一次训练结束后，我们往往习惯问：今天跑了多少公里，配速又快了多少？</p><p>训练计划里的空白，并不意味着没有进步。休息让我们有机会观察变化，也让下一次训练有更好的起点。</p><h2 style="font-size:21px;color:#266447">把观察变成可执行的安排</h2><p>先从简单的训练日记开始，记下睡眠、主观疲劳和训练感受。</p></body></html>'
   await route.fulfill(json=dict(html=html,body=html,plaintext=a['content'],references=[],compatibility=[]))
  await page.route('**/api/articles?*',library)
  await page.route('**/api/articles/'+aid,article)
  await page.route('**/api/articles/'+aid+'/jobs',job_list)
  await page.route('**/api/jobs/visual-task',job_detail)
  await page.route('**/api/articles/'+aid+'/preview',preview)
  async def shot(name):
   await page.evaluate('window.scrollTo(0,0)')
   await page.screenshot(path=str(OUT/(name+'.png')),full_page=not bool(await page.locator('dialog[open],.context-drawer').count()))
  async def fits():
   assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),'Page overflows horizontally'
   for dialog in await page.locator('dialog[open]').all():
    assert await dialog.evaluate('(e)=>e.scrollWidth<=e.clientWidth+1'),'Dialog overflows horizontally'
  async def nav(label):
   await page.locator('.stage-nav').filter(has=page.locator('strong',has_text=label)).click()
   await expect(page.locator('.workspace-title h1')).to_have_text(label)
  try:
   for width in (1440,1100,390):
    await page.set_viewport_size(dict(width=width,height=1000))
    rows=[];await page.goto(BASE,wait_until='networkidle')
    await expect(page.get_by_text('这里，留给你的下一篇作品',exact=True)).to_be_visible()
    before=await page.locator('.home-top').bounding_box()
    await shot(f'home-empty-{width}')
    rows=[a,failed];await page.reload(wait_until='networkidle')
    await expect(page.locator('.library-card')).to_have_count(2)
    after=await page.locator('.home-top').bounding_box()
    assert before==after,'Article count changed the home hero layout'
    assert await page.locator('.home-intro h1').evaluate('(e)=>getComputedStyle(e).fontSize')=={1440:'36px',1100:'33px',390:'31px'}[width]
    await expect(page.locator('.home-intro>p')).to_be_visible()
    await expect(page.locator('.home-process')).to_be_visible()
    if width>760:await expect(page.locator('.home-illustration')).to_be_visible()
    else:await expect(page.locator('.home-illustration')).to_be_hidden()
    await expect(page.locator('.library-card').first.locator('.library-task')).to_have_count(0)
    await expect(page.locator('.library-failure')).to_contain_text('运行失败')
    await fits();await shot(f'home-{width}')
    create=page.get_by_role('button',name='开始一篇新文章',exact=True)
    await create.click();await expect(page.get_by_role('dialog',name='开始一篇新文章')).to_be_visible()
    await fits();await shot(f'new-article-{width}');await page.keyboard.press('Escape');await expect(create).to_be_focused()
    await page.get_by_label('搜索文章标题或主题',exact=True).fill('没有匹配的关键词')
    await expect(page.get_by_text('没有匹配的文章',exact=True)).to_be_visible();await shot(f'home-search-empty-{width}')
    await page.goto(BASE+'/#'+aid,wait_until='networkidle')
    await expect(page.locator('.stage-nav .nav-task')).to_have_count(0)
    await expect(page.locator('.topic-explore .primary')).to_have_count(1)
    await expect(page.locator('.workspace-title .primary')).to_have_count(0)
    for label in LABELS:
     await nav(label);await fits()
     if width==390:
      current=page.locator('.stage-nav[aria-current="step"]')
      assert await current.evaluate('(e)=>{const b=e.getBoundingClientRect();return b.left>=0&&b.right<=innerWidth}'),'Current stage is not visible'
      assert all(await page.locator('.stage-body .button:visible,.workspace-title .icon-button:visible').evaluate_all('(els)=>els.map(e=>e.getBoundingClientRect().height>=44)')),'Touch target too small'
     if label in ('写作','审核修改'):
      await expect(page.locator('.prose-editor')).to_be_visible()
     if width==390 and await page.locator('.workspace-title .primary').count():
      assert (await page.locator('.workspace-title .primary').bounding_box())['height']<=48,'Primary action wraps inside a word'
     if label=='写作':
      assert (await page.locator('.editorial-actions').bounding_box())['height']<=(160 if width==390 else 80)
     if label=='排版导出':
      await expect(page.get_by_label('排版主题',exact=True)).to_be_visible()
      await expect(page.locator('.phone-frame')).to_be_visible()
      await expect(page.get_by_title('公众号排版预览',exact=True)).to_be_visible()
     await shot(f'{label}-{width}')
    await nav('选题')
    await expect(page.get_by_text('配置来源',exact=True)).to_have_count(0)
    await page.get_by_role('button',name='调整选题服务',exact=True).click()
    settings=page.get_by_role('dialog',name='AI 服务与偏好',exact=True)
    await expect(settings.locator('#route-topic')).to_be_visible();await fits();await shot(f'settings-routes-{width}')
    await settings.get_by_role('button',name='模型服务',exact=True).click();await fits();await shot(f'settings-services-{width}')
    await page.keyboard.press('Escape');await expect(page.get_by_role('button',name='调整选题服务',exact=True)).to_be_focused()
    if width==390:
     await page.get_by_text('更多',exact=True).click();await shot('mobile-menu')
     await page.locator('.mobile-menu').get_by_role('button',name='账号与学习',exact=True).click()
    else:await page.locator('.desktop-extras').get_by_role('button',name='账号与学习',exact=True).click()
    await expect(page.get_by_label('账号受众',exact=True)).to_be_visible();await fits();await shot(f'account-{width}');await page.keyboard.press('Escape')
    if width==390:
     await page.get_by_text('更多',exact=True).click();await page.locator('.mobile-menu').get_by_role('button',name='扩展',exact=True).click()
    else:await page.locator('.desktop-extras').get_by_role('button',name='扩展',exact=True).click()
    await expect(page.get_by_role('button',name='生成独立平台稿',exact=True)).to_be_visible();await fits();await shot(f'extensions-{width}');await page.keyboard.press('Escape')
    if width<1200:
     await page.get_by_role('button',name='展开侧栏',exact=True).click()
     await expect(page.get_by_role('button',name='关闭侧栏',exact=True)).to_be_focused();await shot(f'drawer-{width}')
     await page.keyboard.press('Escape');await expect(page.get_by_role('button',name='展开侧栏',exact=True)).to_be_focused()
   # Current alerts are scoped; an adopted topic does not keep a stale confirmation label.
   for width in (1440,390):
    await page.set_viewport_size(dict(width=width,height=1000))
    for state in ('running','failed'):
     jobs=[dict(old_job,id='visual-task',status=state,message='正在对照写作要求，梳理候选角度。' if state=='running' else '连接中断，请检查当前选题服务。',activity='正在梳理候选角度',execution_usage=dict(requests=3,unknown=2),active_request_started_at=stamp,active_request_label='模型调用',last_progress_at=stamp,service=dict(name='离线验收',model='synthetic'),failure=dict(category='connection',http_status=None,service=dict(name='离线验收',model='synthetic')) if state=='failed' else None)]
     await page.reload(wait_until='networkidle');await nav('选题')
     await expect(page.locator('.task-status')).to_be_visible();await fits();await shot(f'topic-{state}-{width}')
     await expect(page.locator('.task-status')).not_to_contain_text('费用未知')
     if state=='running':
      await expect(page.locator('.task-status')).to_contain_text('本次模型调用已进行')
      assert await page.locator('.task-status').evaluate('(el)=>getComputedStyle(el).borderTopWidth')=='1px'
     await nav('素材');await expect(page.locator('.task-status')).to_have_count(0);await expect(page.locator('.task-brief')).to_be_visible()
   jobs=[dict(old_job,id='completed-action',status='running',message='正在整理结果',execution_usage=dict(requests=1,unknown=2),last_completed_at=stamp,last_completed_label='模型回复已收到',native=dict(id='synthetic',run_id='synthetic-run',upstream_revision='abcdef123456',reads=[]),search_diagnostic=dict(request_count=1,tool_calls=1,result_blocks=1,source_count=1,warnings=['DeepSeek 官方内部检索次数由服务端决定；实际检索可能产生额外费用。','搜索回复不完整；来源仍需核实。']))]
   await page.reload(wait_until='networkidle');await nav('选题')
   await expect(page.locator('.task-status')).to_contain_text('最近完成：模型回复已收到')
   await expect(page.locator('.search-diagnostic')).to_contain_text('搜索回复不完整')
   await expect(page.locator('.search-diagnostic')).not_to_contain_text('DeepSeek 官方内部检索次数')
   await expect(page.locator('.task-history')).not_to_contain_text('费用未知')
   jobs=[old_job]
   a['brief']['topic']='';a['stages']['topic']='needs_input'
   await page.reload(wait_until='networkidle');await nav('选题')
   await expect(page.locator('.stage-nav.active .nav-task')).to_have_text('待你确认')
   await shot('topic-awaiting-adoption-390')
   a['stages']['write']='stale';a['workflow']['write'].update(allowed=False,target='outline',reason='请先确认当前大纲')
   await page.reload(wait_until='networkidle');await nav('写作')
   await expect(page.locator('.stage-guidance')).to_have_count(1)
   await expect(page.locator('.stage-guidance')).to_contain_text('请先确认当前大纲')
   await expect(page.locator('.stage-guidance').get_by_role('button',name='前往大纲')).to_be_visible()
   await shot('write-prerequisite-390')
   assert not errors,errors
   print('v2.3.1 visual acceptance passed: original home for empty/populated libraries, 3 widths, 7 stages, dialogs, focus, scoped alerts and adopted-topic status')
  except Exception:
   await shot('failure');raise
  finally:await browser.close()


if __name__=='__main__':asyncio.run(main())
