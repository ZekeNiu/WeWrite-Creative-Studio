"""Synthetic settings and error presentation acceptance; QA server only."""
import asyncio
import json
import os
from datetime import datetime,timezone
from pathlib import Path
from playwright.async_api import async_playwright,expect

BASE=os.environ.get('QA_BASE','http://127.0.0.1:8977')
OUT=Path(__file__).resolve().parents[1]/'output/playwright/v232'
H={'X-Studio-Request':'1'}


async def main():
 OUT.mkdir(parents=True,exist_ok=True)
 async with async_playwright() as p:
  browser=await p.chromium.launch(channel='msedge',headless=True)
  context=await browser.new_context(viewport={'width':1440,'height':1000})
  await context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(BASE) else r.abort())
  page=await context.new_page();page.set_default_timeout(15000);errors=[]
  page.on('pageerror',lambda e:errors.append(str(e)))
  original=await (await page.request.get(BASE+'/api/settings')).json()
  assert all(s['id']=='fixture' for s in original['services']),'Synthetic QA configuration required'
  a=await (await page.request.post(BASE+'/api/articles',headers=H,data={})).json();aid=a['id']
  try:
   await page.goto(BASE+'/#'+aid)
   await page.get_by_role('button',name='AI 服务与设置',exact=True).click()
   dialog=page.get_by_role('dialog',name='AI 服务与偏好',exact=True)
   async def save_settings():
    async with page.expect_response(lambda r:r.url==BASE+'/api/settings' and r.request.method=='PUT') as pending:
     await dialog.get_by_role('button',name='保存设置',exact=True).click()
    assert (await pending.value).ok
    await expect(dialog.get_by_role('button',name='保存设置',exact=True)).to_be_enabled()
   await expect(dialog.get_by_label('文本与工具接口',exact=True)).to_have_count(1)
   await expect(dialog.get_by_label('接口协议',exact=True)).to_have_count(0)
   await expect(dialog.get_by_label('接入预设',exact=True)).to_have_count(0)
   labels=await dialog.get_by_label('文本与工具接口',exact=True).locator('option').all_text_contents()
   assert labels==['OpenAI 兼容对话（Chat Completions）','OpenAI 响应（Responses）','Anthropic 消息（Messages）']
   await dialog.get_by_text('高级设置：输出参数与价格',exact=True).click()
   await dialog.get_by_label('单次回复上限（Token）',exact=True).fill('48000')
   await save_settings()
   await expect(dialog.get_by_text('设置已保存',exact=True).first).to_be_visible()
   cfg=await (await page.request.get(BASE+'/api/settings')).json()
   assert cfg['services'][0]['max_tokens']==48000
   assert cfg['routes']==original['routes'] and cfg['search']==original['search']
   await expect(dialog.get_by_text('单次回复上限限制一次响应',exact=False)).to_be_visible()
   await dialog.screenshot(path=str(OUT/'settings-desktop.png'))
   await dialog.get_by_role('button',name='能力测试',exact=True).click()
   await expect(dialog.get_by_text('基础测试通过不代表完整选题流程已通过。',exact=False)).to_be_visible()
   card=dialog.locator('.model-test-card').first
   await expect(card.get_by_label('离线验收 · synthetic 模型原生联网接口',exact=True)).to_have_value('inherit')
   async def slow_test(route):
    await asyncio.sleep(.5)
    await route.continue_()
   await page.route('**/api/services/fixture/capability-tests',slow_test)
   await card.get_by_role('button',name='测试联网搜索',exact=True).click()
   await expect(card.get_by_label('离线验收 · synthetic 模型原生联网接口',exact=True)).to_be_disabled()
   await dialog.get_by_role('button',name='关闭',exact=True).click()
   await expect(dialog).to_be_visible()
   await expect(card.get_by_label('离线验收 · synthetic 模型原生联网接口',exact=True)).to_be_disabled()
   await expect(card.get_by_role('button',name='测试联网搜索',exact=True)).to_be_enabled()
   await expect(card.get_by_text('尚未发送搜索请求：',exact=False)).to_be_visible()
   await page.unroute('**/api/services/fixture/capability-tests',slow_test)
   cfg=await (await page.request.get(BASE+'/api/settings')).json()
   assert cfg['routes']==original['routes'] and cfg['search']==original['search']
   await card.get_by_label('离线验收 · synthetic 模型原生联网接口',exact=True).select_option('anthropic')
   await save_settings()
   await expect(dialog.get_by_text('设置已保存',exact=True).first).to_be_visible()
   cfg=await (await page.request.get(BASE+'/api/settings')).json()
   assert cfg['services'][0]['protocol']=='chat'
   profile=next(c for c in cfg['model_connections'] if c['service_id']=='fixture' and c['model']=='synthetic')
   assert profile['search_protocol']=='anthropic'
   assert cfg['routes']==original['routes'] and cfg['search']==original['search']
   await dialog.screenshot(path=str(OUT/'capabilities-desktop.png'))
   await page.set_viewport_size({'width':390,'height':844})
   await expect(card.get_by_label('离线验收 · synthetic 模型原生联网接口',exact=True)).to_be_visible()
   assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
   await page.screenshot(path=str(OUT/'capabilities-mobile.png'),full_page=True)
   await dialog.get_by_role('button',name='关闭',exact=True).click()
   await page.set_viewport_size({'width':1440,'height':1000})
   stamp=datetime.now(timezone.utc).isoformat()
   job=dict(id='synthetic-empty',article_id=aid,stage='topic',status='failed',created=stamp,ended=stamp,
     request={'stage':'topic'},message='已纠正一次，模型仍未返回工具调用；任务文件已保留',
     tool_corrections=1,execution_usage={'requests':2},failure=dict(category='empty_response',http_status=200,
      response_received=True,finish_reason='stop',tool_count=0,text_chars=0,parameters={'max_tokens':48000,'temperature':None}))
   async def failed(route):await route.fulfill(json=[job])
   await page.route('**/api/articles/'+aid+'/jobs',failed)
   await page.reload()
   await page.get_by_text('查看错误详情',exact=True).click()
   await expect(page.get_by_text('接口返回空结果',exact=True)).to_be_visible()
   await expect(page.locator('.failure-details')).to_contain_text(['200','stop'])
   await expect(page.get_by_text('未收到响应',exact=True)).to_have_count(0)
   await expect(page.get_by_text('已尝试 1 次工具调用纠正',exact=False)).to_be_visible()
   await page.screenshot(path=str(OUT/'empty-response-diagnostic.png'),full_page=True)
   job['failure'].pop('http_status');await page.reload();await page.get_by_text('查看错误详情',exact=True).click()
   await expect(page.get_by_text('已收到响应，状态未记录',exact=True)).to_be_visible()
   await page.unroute('**/api/articles/'+aid+'/jobs',failed)
   await page.reload();await page.get_by_role('button',name='寻找选题灵感',exact=True).click()
   await expect(page.locator('.topic-card')).to_have_count(6)
   await page.get_by_role('button',name='就写这个',exact=True).first.click()
   await expect(page.get_by_role('button',name='已采用',exact=True)).to_be_visible()
   adopted=await (await page.request.get(BASE+'/api/articles/'+aid)).json()
   assert adopted['brief']['topic'] and adopted['topics']
   assert not errors,errors
  finally:
   await page.request.put(BASE+'/api/settings',headers=H,data=original)
   await browser.close()
 print('PASS: protocol/token settings, save isolation, unsent search, mobile, response diagnostics and topic adoption; zero external requests.')


if __name__=='__main__':asyncio.run(main())
