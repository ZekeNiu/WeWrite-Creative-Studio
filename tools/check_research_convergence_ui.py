"""Convergence and material handoff UI; only the isolated offline QA server."""
import asyncio
import json
import os
from pathlib import Path
from playwright.async_api import async_playwright,expect

BASE=os.environ.get('QA_BASE','http://127.0.0.1:8977')
OUT=Path(__file__).resolve().parents[1]/'output/playwright/v237'
H={'X-Studio-Request':'1'}


async def main():
    OUT.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='msedge',headless=True)
        context=await browser.new_context(viewport=dict(width=1440,height=1000))
        await context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(BASE) else r.abort())
        page=await context.new_page();page.set_default_timeout(20000);errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        try:
            fixture=await page.request.get(BASE+'/api/qa-fixture')
            assert fixture.ok,'Use qa_reliability_app; never run against personal data'
            a=await (await page.request.post(BASE+'/api/articles',headers=H,data=dict(topic='模拟：证据能回答什么'))).json();aid=a['id']
            await page.goto(BASE+'/#'+aid)
            await page.locator('.stage-nav').filter(has=page.locator('strong',has_text='素材')).click()
            await page.get_by_role('button',name='深入核实',exact=True).click()
            panel=page.get_by_label('资料核实进展',exact=True)
            await expect(panel).to_contain_text('已保存核实成果，剩余问题待你处理')
            jobs=await (await page.request.get(BASE+'/api/articles/'+aid+'/jobs')).json()
            assert jobs[0]['status']=='needs_input'
            current=await (await page.request.get(BASE+'/api/articles/'+aid)).json()
            assert current['research']['pending'] and current['stages']['outline']=='idle' and not current['content']
            await panel.get_by_text('尚未解决的问题',exact=False).click()
            await expect(panel).to_contain_text(a['brief']['topic'])
            await page.evaluate('window.scrollTo(0,0)');await page.wait_for_timeout(100)
            await page.screenshot(path=str(OUT/'pending-desktop.png'),full_page=True)
            await page.set_viewport_size(dict(width=390,height=844))
            await expect(panel).to_be_visible()
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            await page.evaluate('window.scrollTo(0,0)');await page.wait_for_timeout(100)
            await page.screenshot(path=str(OUT/'pending-mobile.png'),full_page=True)
            await page.set_viewport_size(dict(width=1440,height=1000))
            await page.locator('.source-actions').get_by_role('button',name='粘贴文字',exact=True).click()
            await page.get_by_label('素材名称',exact=True).fill('模拟补充原文')
            await page.get_by_label('素材正文',exact=True).fill('研究只支持关联。')
            await page.get_by_role('button',name='添加素材',exact=True).click()
            await page.get_by_role('button',name='深入核实',exact=True).click()
            await expect(panel).to_contain_text('本篇核心问题已回答，资料整理已收尾')
            current=await (await page.request.get(BASE+'/api/articles/'+aid)).json()
            assert not current['research']['pending'] and current['stages']['sources']=='done'
            assert current['stages']['outline']=='idle'
            await page.evaluate('window.scrollTo(0,0)');await page.wait_for_timeout(100)
            await page.screenshot(path=str(OUT/'ready-desktop.png'),full_page=True)
            # A running state uses the job's checkpoint, not the previous result.
            active=dict(jobs[0],status='running',message='模拟等待',research=dict(convergence=dict(state='working',reason='核实新提供的结果',question_ids=['Q1'],questions=['新增结果是否回答本篇问题？'])))
            async def active_jobs(route):await route.fulfill(json=[active])
            await page.route('**/api/articles/'+aid+'/jobs',active_jobs)
            await page.reload()
            await expect(panel).to_contain_text('正在按具体问题核实')
            await panel.get_by_text('当前核实的问题',exact=False).click()
            await expect(panel).to_contain_text('新增结果是否回答本篇问题？')
            await page.evaluate('window.scrollTo(0,0)');await page.wait_for_timeout(100)
            await page.screenshot(path=str(OUT/'working-desktop.png'),full_page=True)
            assert not errors,errors
            print(json.dumps(dict(pending_handoff=True,supplement_then_ready=True,automatic_outline=False,working_question=True,desktop=True,mobile=True,console_errors=errors)))
        finally:await browser.close()


asyncio.run(main())
