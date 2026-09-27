"""Batch pagination acceptance, using only the isolated synthetic QA server."""
import asyncio
import copy
import json
import os
from pathlib import Path
from playwright.async_api import async_playwright, expect

BASE=os.environ.get('QA_BASE','http://127.0.0.1:8977')
OUT=Path(__file__).resolve().parents[1]/'output/playwright/topic-batches'
H={'X-Studio-Request':'1'}


async def check(page,base,out):
    aid=page.url.split('#')[1]
    url=base+'/api/articles/'+aid
    picker=page.get_by_label('选题批次',exact=True)
    async def article():return await (await page.request.get(url)).json()
    async def topic():
        await page.locator('.stage-nav').filter(has=page.locator('strong',has_text='选题')).click()
        await expect(page.locator('.workspace-title h1')).to_have_text('选题')
    async def selected(number,total):
        await expect(picker.locator('option:checked')).to_have_text(f'第 {number} 批 / 共 {total} 批')
    started=[]
    def request(req):
        if req.method=='POST' and req.url.endswith('/jobs'):started.append(req.url)
    page.on('request',request)
    try:
        # Generate while viewing an older batch; newest completion must become visible.
        for number in (4,5):
            await picker.select_option(index=0)
            await page.get_by_role('button',name='换一批选题',exact=True).click()
            await selected(number,number)
            await expect(page.locator('.topic-card h3').first).to_have_text(f'模拟选题 1（第 {number} 批）')
            await expect(page.locator('.topic-batches')).to_be_in_viewport()
        saved=await article();history=copy.deepcopy(saved['creative_intent']['batches'])
        assert len(history)==5
        await expect(page.get_by_role('button',name='下一批',exact=True)).to_be_disabled()
        count=len(started)
        await page.get_by_role('button',name='上一批',exact=True).click();await selected(4,5)
        await expect(page.locator('.topic-card h3').first).to_have_text('模拟选题 1（第 4 批）')
        await picker.select_option(index=0);await selected(1,5)
        await expect(page.get_by_role('button',name='上一批',exact=True)).to_be_disabled()
        await expect(page.locator('.topic-card h3').first).to_have_text('模拟选题 1')
        assert (await article())==saved and len(started)==count

        # Failure does not insert a page, change the viewed batch or erase history.
        jobs=await (await page.request.get(url+'/jobs')).json()
        failed={**jobs[0],'id':'synthetic-topic-failure','status':'failed','message':'模拟生成失败','failure':dict(category='service_error')}
        async def fail(route):
            if route.request.method=='POST':await route.fulfill(json=failed)
            else:await route.continue_()
        await page.route(url+'/jobs',fail)
        await page.get_by_role('button',name='换一批选题',exact=True).click()
        await expect(page.locator('.task-status')).to_contain_text('模拟生成失败')
        await selected(1,5)
        assert (await article())==saved
        await page.unroute(url+'/jobs',fail)
        await page.reload();await selected(5,5)

        # Historical adoption keeps the latest projection and every saved batch.
        await picker.select_option(index=0)
        await page.get_by_role('button',name='就写这个',exact=True).first.click()
        await expect(page.locator('.topic-card.selected')).to_have_count(1)
        adopted=await article()
        assert adopted['creative_intent']['selected']['id']==history[0]['topics'][0]['id']
        assert adopted['topics']==saved['topics']
        assert adopted['creative_intent']['batches']==history
        await page.reload();await topic();await selected(5,5)
        await expect(page.locator('.topic-card.selected')).to_have_count(0)

        # Existing duplicate archives identify the adopted plan by ID, never title.
        duplicate=copy.deepcopy(adopted)
        for index,row in enumerate(duplicate['creative_intent']['batches'][-1]['topics']):
            row['title']=history[0]['topics'][index]['title']
        duplicate['topics']=copy.deepcopy(duplicate['creative_intent']['batches'][-1]['topics'])
        async def duplicate_read(route):await route.fulfill(json=duplicate)
        await page.route(url,duplicate_read)
        await page.reload();await topic();await selected(5,5)
        await expect(page.locator('.topic-card h3').first).to_have_text('模拟选题 1')
        await expect(page.locator('.topic-card.selected')).to_have_count(0)
        await picker.select_option(index=0)
        await expect(page.locator('.topic-card.selected')).to_have_count(1)
        await page.unroute(url,duplicate_read)

        # Old articles with no batch array still show the existing candidates.
        legacy=copy.deepcopy(adopted);legacy['creative_intent'].pop('batches')
        async def legacy_read(route):await route.fulfill(json=legacy)
        await page.route(url,legacy_read)
        await page.reload();await topic();await selected(1,1)
        await expect(page.locator('.topic-card')).to_have_count(len(saved['topics']))
        await page.unroute(url,legacy_read)

        other=await (await page.request.post(base+'/api/articles',headers=H,data=dict(topic='批次隔离文章'))).json()
        await page.evaluate('(id)=>location.hash=id',other['id'])
        await expect(page.locator('.header-center')).to_contain_text('批次隔离文章')
        await topic();await expect(picker).to_have_count(0)
        await expect(page.locator('.topic-card')).to_have_count(0)
        await page.evaluate('(id)=>location.hash=id',aid)
        await expect(page.locator('.header-center')).to_contain_text(adopted['title'])
        await topic();await selected(5,5)
        await picker.select_option(index=1);await selected(2,5)
        await page.reload();await topic();await selected(5,5)
        out.mkdir(parents=True,exist_ok=True)
        for width,height in ((1440,1000),(390,844)):
            await page.set_viewport_size(dict(width=width,height=height))
            await page.locator('.topic-batches').scroll_into_view_if_needed()
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            await expect(page.get_by_role('button',name='上一批',exact=True)).to_be_in_viewport()
            await expect(picker).to_be_in_viewport()
            await page.screenshot(path=str(out/f'topic-batches-{width}.png'),full_page=True)
        await page.set_viewport_size(dict(width=1440,height=1000))
        assert (await article())==adopted
        print('PASS topic batches: five pages, history adoption, duplicate IDs, failure, legacy, reload, article isolation and mobile')
    finally:
        page.remove_listener('request',request)


async def main():
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='msedge',headless=True)
        context=await browser.new_context(viewport=dict(width=1440,height=1000))
        await context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(BASE) else r.abort())
        page=await context.new_page();page.set_default_timeout(20000)
        errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        try:
            # This endpoint exists only in the isolated fixture server.
            assert (await page.request.get(BASE+'/api/qa-fixture')).ok
            a=await (await page.request.post(BASE+'/api/articles',headers=H,data=dict(topic=''))).json()
            await page.goto(BASE+'/#'+a['id'])
            for number in (1,2,3):
                await page.get_by_role('button',name='寻找选题灵感' if number==1 else '换一批选题',exact=True).click()
                await expect(page.get_by_label('选题批次',exact=True).locator('option:checked')).to_have_text(f'第 {number} 批 / 共 {number} 批')
            await check(page,BASE,OUT)
            assert not errors,errors
        except BaseException:
            OUT.mkdir(parents=True,exist_ok=True)
            await page.screenshot(path=str(OUT/'failure.png'),full_page=True)
            raise
        finally:await browser.close()


if __name__=='__main__':asyncio.run(main())
