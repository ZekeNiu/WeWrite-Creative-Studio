"""Real browser acceptance against qa_reader_app only; no external IO."""
import asyncio
import os
from pathlib import Path
from playwright.async_api import async_playwright,expect

BASE=os.environ.get('QA_BASE','http://127.0.0.1:8978')
OUT=Path(__file__).resolve().parents[1]/'output/playwright/reader-workflow'

async def main():
    OUT.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='msedge',headless=True)
        context=await browser.new_context(viewport=dict(width=1440,height=1000))
        await context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(BASE) else r.abort())
        page=await context.new_page();page.set_default_timeout(25000);errors=[];requests=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        page.on('request',lambda r:requests.append(r.post_data_json) if r.method=='POST' and r.url.endswith('/jobs') else None)
        aid=(await (await page.request.get(BASE+'/api/qa-fixture')).json())['id']
        async def article():return await (await page.request.get(BASE+'/api/articles/'+aid)).json()
        try:
            await page.goto(BASE+'/#'+aid)
            await expect(page.get_by_text('资料已整理，可以进入大纲',exact=True)).to_be_visible()
            await expect(page.get_by_text('OLD_OPTIONAL_CHECK',exact=False)).not_to_be_visible()
            await page.get_by_role('tab',name='本篇素材',exact=False).click()
            await expect(page.locator('.compact-source')).to_have_count(10)
            await expect(page.locator('.material-purpose').first).to_contain_text('用于说明：')
            await expect(page.locator('.compact-source').nth(1)).to_contain_text('AI 不会读取或使用')
            await expect(page.locator('.compact-source').nth(2)).to_contain_text('青椒土豆丝的做法')
            await page.get_by_role('button',name='下一页',exact=True).click()
            await expect(page.locator('.compact-source')).to_have_count(4)
            await page.get_by_label('素材采用筛选',exact=True).select_option('excluded')
            await expect(page.locator('.compact-source')).to_have_count(1)
            await page.get_by_label('素材采用筛选',exact=True).select_option('all')
            await page.get_by_label('补充检索要求',exact=True).fill('先说明炒蛋和收汁的顺序')
            await page.get_by_role('button',name='查找并整理资料',exact=True).click()
            for _ in range(300):
                jobs=await (await page.request.get(BASE+'/api/articles/'+aid+'/jobs')).json()
                if jobs and jobs[0]['stage']=='sources' and jobs[0]['status'] not in ('running','queued'):break
                await asyncio.sleep(.1)
            assert jobs[0]['status']=='completed',jobs[0].get('message')
            await expect(page.get_by_role('button',name='查找并整理资料',exact=True)).to_be_enabled()
            await expect(page.locator('.research-summary')).to_contain_text('备料、炒蛋和收汁')
            assert requests[-1]['stage']=='sources' and requests[-1]['instruction']=='先说明炒蛋和收汁的顺序'
            current=await article()
            assert current['evidence']['engine']=='wewrite-native' and not next(s for s in current['sources'] if s['id']=='Srecipe1')['selected']
            assert current['materials_state']['pending']==[]
            await page.get_by_role('tab',name='本篇素材',exact=False).click()
            await expect(page.locator('.compact-source')).to_have_count(10)
            for width in (1440,390):
                await page.set_viewport_size(dict(width=width,height=1000))
                await expect(page.get_by_role('button',name='深入核实',exact=True)).to_be_visible()
                assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                await page.screenshot(path=str(OUT/f'materials-{width}.png'),full_page=True)
            # Inspect the submitted advanced route without waiting for another
            # research run; return an explicit synthetic failure at this edge.
            async def intercept(route):
                if route.request.method=='POST':await route.fulfill(status=503,json={'detail':'Synthetic route inspection'})
                else:await route.continue_()
            await page.route('**/api/articles/'+aid+'/jobs',intercept)
            await page.get_by_role('button',name='深入核实',exact=True).click()
            await expect(page.get_by_text('Synthetic route inspection',exact=False)).to_be_visible()
            assert requests[-1]['stage']=='research'
            assert not errors,errors
            print('PASS: native default, focused research route, material purpose, exclusions, paging, history, desktop/mobile')
        finally:await browser.close()

if __name__=='__main__':asyncio.run(main())
