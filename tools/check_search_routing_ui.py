"""Focused offline UI check for shared search routing; requires the synthetic QA server."""
import asyncio
import json
import os
from datetime import datetime,timezone
from pathlib import Path
from playwright.async_api import async_playwright,expect

BASE=os.environ.get('QA_BASE','http://127.0.0.1:8977')
OUT=Path(__file__).resolve().parents[1]/'output/playwright/v234'
H={'X-Studio-Request':'1'}


async def main():
 OUT.mkdir(parents=True,exist_ok=True)
 async with async_playwright() as p:
  browser=await p.chromium.launch(channel='msedge',headless=True)
  context=await browser.new_context(viewport={'width':1440,'height':960})
  await context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(BASE) else r.abort())
  page=await context.new_page();errors=[]
  page.on('pageerror',lambda e:errors.append(str(e)))
  original=await (await page.request.get(BASE+'/api/settings')).json()
  assert [s['id'] for s in original['services']]==['fixture'],'Synthetic server required'
  cfg=json.loads(json.dumps(original))
  cfg['services'].append(dict(cfg['services'][0],id='search-fixture',name='模拟联网',model='search-only',protocol='anthropic',key='synthetic'))
  cfg['search']['enabled']=True
  response=await page.request.put(BASE+'/api/settings',headers=H,data=cfg);assert response.ok
  a=await (await page.request.post(BASE+'/api/articles',headers=H,data={})).json();aid=a['id']
  try:
   await page.goto(BASE+'/#'+aid)
   await page.get_by_role('button',name='AI 服务与设置',exact=True).click()
   dialog=page.get_by_role('dialog',name='AI 服务与偏好',exact=True)
   await dialog.get_by_role('button',name='节点分工',exact=True).click()
   await expect(dialog.locator('#route-search')).to_be_visible()
   await dialog.get_by_label('联网模型',exact=True).select_option(json.dumps(['search-fixture','search-only'],separators=(',',':')))
   async with page.expect_response(lambda r:r.url==BASE+'/api/settings' and r.request.method=='PUT') as pending:
    await dialog.get_by_role('button',name='保存设置',exact=True).click()
   assert (await pending.value).ok
   await expect(dialog.get_by_role('button',name='保存设置',exact=True)).to_be_enabled()
   saved=await (await page.request.get(BASE+'/api/settings')).json()
   assert saved['routes']==original['routes'] and saved['search']['native_service_id']=='search-fixture'
   assert saved['search']['native_protocol']=='inherit'
   await dialog.get_by_role('button',name='流程偏好',exact=True).click()
   await expect(dialog.get_by_label('联网模型',exact=True)).to_have_value('["search-fixture","search-only"]')
   await dialog.get_by_role('button',name='关闭',exact=True).click()
   await page.reload()
   await expect(page.locator('.stage-service').filter(has_text='联网搜索：')).to_contain_text('模拟联网 · search-only')
   await expect(page.locator('.stage-service').filter(has_text='选题：')).to_contain_text('离线验收 · synthetic')
   stamp=datetime.now(timezone.utc).isoformat()
   job=dict(id='synthetic-search-failure',article_id=aid,stage='topic',status='failed',created=stamp,ended=stamp,
       request={'stage':'topic'},message='模拟联网超时',execution_usage={'requests':1,'unknown':1},
       failure=dict(category='timeout',operation='search',request_sent=True,response_received=False,
           service=dict(id='search-fixture',name='模拟联网',model='search-only',protocol='anthropic')))
   await page.route('**/api/articles/'+aid+'/jobs',lambda route:route.fulfill(json=[job]))
   await page.reload()
   await page.locator('.task-status').get_by_role('button',name='调整联网搜索服务',exact=True).click()
   await expect(dialog.locator('#route-search')).to_have_class('service-card route-highlight')
   await expect(dialog.get_by_label('联网模型',exact=True)).to_have_value('["search-fixture","search-only"]')
   await dialog.screenshot(path=str(OUT/'search-routing-desktop.png'))
   await page.set_viewport_size({'width':390,'height':844})
   await expect(dialog.get_by_label('联网模型',exact=True)).to_be_visible()
   await dialog.screenshot(path=str(OUT/'search-routing-mobile.png'))
   assert not errors,errors
  finally:
   await page.request.put(BASE+'/api/settings',headers=H,data=original)
   await browser.close()
 print('PASS: node search selection, save/reload, shared preferences, independent node routes, failed-search settings target, desktop/mobile; zero paid calls.')


if __name__=='__main__':asyncio.run(main())
