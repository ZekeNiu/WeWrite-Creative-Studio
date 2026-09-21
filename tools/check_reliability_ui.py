"""Current complete UI acceptance, including delayed/failed saves. Offline QA server only."""
import asyncio
import io
import json
import os
from pathlib import Path
from playwright.async_api import async_playwright, expect
from PIL import Image

ROOT=Path(__file__).resolve().parents[1];BASE=os.environ.get('QA_BASE','http://127.0.0.1:8977')
OUT=ROOT/'output/playwright/reliability';OUT.mkdir(parents=True,exist_ok=True)
H={'X-Studio-Request':'1'}


async def main():
 async with async_playwright() as p:
    browser=await p.chromium.launch(channel='msedge',headless=True)
    context=await browser.new_context(viewport={'width':1440,'height':1000},permissions=['clipboard-read','clipboard-write'])
    await context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(BASE) else route.abort())
    page=await context.new_page();page.set_default_timeout(20000);errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    async def nav(label):
        await page.locator('.stage-nav').filter(has=page.locator('strong',has_text=label)).click()
        await expect(page.locator('.workspace-title h1')).to_have_text(label)
    async def article():return await (await page.request.get(BASE+'/api/articles/'+page.url.split('#')[1])).json()
    async def wait_article(check):
        for _ in range(200):
            a=await article()
            if check(a):return a
            await asyncio.sleep(.05)
        raise AssertionError('Persisted article did not reach expected state')
    try:
        await page.goto(BASE)
        await page.get_by_role('button',name='开始一篇新文章',exact=True).click()
        await page.get_by_role('dialog').get_by_role('button',name='创建文章',exact=True).click()
        await page.get_by_role('button',name='寻找选题灵感',exact=True).click()
        await expect(page.locator('.topic-card')).to_have_count(6)
        await page.get_by_role('button',name='就写这个',exact=True).first.click()
        await wait_article(lambda a:bool(a['brief']['topic']))
        await nav('素材')
        await expect(page.locator('.workspace-title h1')).to_have_text('素材')
        await page.locator('.source-actions').get_by_role('button',name='粘贴文字',exact=True).click()
        await page.get_by_label('素材名称',exact=True).fill('模拟原文')
        await page.get_by_label('素材正文',exact=True).fill('研究只支持关联。'+('原研究的条件和范围。'*90))
        await page.get_by_role('button',name='添加素材',exact=True).click()
        await expect(page.get_by_role('dialog')).to_have_count(0)
        await page.get_by_role('button',name='核实这批资料',exact=True).click()
        await expect(page.locator('.material-status')).to_contain_text('可进入大纲')
        await page.get_by_role('tab',name='整理结果',exact=True).click()
        await expect(page.get_by_role('button',name='待处理 · 0',exact=True)).to_be_visible()
        await expect(page.get_by_role('button',name='写作边界 · 1',exact=True)).to_be_visible()
        await page.get_by_role('button',name='检索设置',exact=True).click()
        await page.get_by_role('spinbutton',name='最多搜索次数',exact=True).fill('33')
        await page.get_by_role('button',name='保存本轮上限',exact=True).click()
        await page.reload()
        await page.get_by_role('button',name='检索设置',exact=True).click()
        await expect(page.get_by_role('spinbutton',name='最多搜索次数',exact=True)).to_have_value('33')
        await page.get_by_role('dialog').get_by_role('button',name='关闭',exact=True).click()
        await page.get_by_role('button',name='进入大纲',exact=True).click()
        await page.get_by_role('button',name='生成文章大纲',exact=True).click()
        await expect(page.locator('.outline-card')).to_have_count(1)
        await nav('写作');await page.locator('.workspace-title-actions .primary').click()
        await expect(page.locator('.prose-editor')).to_contain_text('模拟验收样稿')
        await nav('审核修改');await page.locator('.workspace-title-actions .primary').click()
        await expect(page.locator('.review-summary')).to_contain_text('AI 审核通过')
        await nav('配图');await page.get_by_role('switch',name='启用 AI 配图',exact=True).click()
        await page.get_by_role('button',name='生成配图方案',exact=True).last.click()
        await expect(page.get_by_label('图片提示词',exact=True)).to_be_visible()
        # Hold the first request while a second field is edited, reproducing the audit race.
        release=asyncio.Event();seen=asyncio.Event();writes=[]
        async def delayed(route):
            if route.request.method=='PATCH' and 'image_plans' in route.request.post_data_json.get('changes',{}):
                writes.append(route.request.post_data_json)
                if len(writes)==1:seen.set();await release.wait()
            await route.continue_()
        await page.route('**/api/articles/*',delayed)
        await page.get_by_label('图片提示词',exact=True).fill('新的图片提示词')
        await page.get_by_label('图注',exact=True).fill('新的图注')
        await page.get_by_label('图注',exact=True).press('Tab')
        await page.get_by_label('图片数量',exact=True).fill('2')
        await page.get_by_label('图片比例',exact=True).select_option('1024x1024')
        await asyncio.wait_for(seen.wait(),5);release.set()
        await wait_article(lambda a:a['image_plans'][0]['caption']=='新的图注')
        assert (await article())['image_plans'][0]['prompt']=='新的图片提示词'
        await wait_article(lambda a:a['visual']['count']==2 and a['visual']['size']=='1024x1024')
        await page.unroute('**/api/articles/*',delayed)
        # One rejected save must preserve the input and show a retry, including at top level.
        failed=False
        async def reject_once(route):
            nonlocal failed
            if not failed and route.request.method=='PATCH' and 'image_plans' in route.request.post_data_json.get('changes',{}):
                failed=True;await route.fulfill(status=409,content_type='application/json',body=json.dumps({'detail':'模拟保存冲突'}));return
            await route.continue_()
        await page.route('**/api/articles/*',reject_once)
        await page.get_by_label('图片提示词',exact=True).fill('失败后保留的提示词')
        await page.get_by_label('图片提示词',exact=True).press('Tab')
        await expect(page.get_by_role('button',name='重试保存',exact=True)).to_be_visible()
        await expect(page.locator('.save-state')).to_contain_text('尚未保存')
        await expect(page.get_by_label('图片提示词',exact=True)).to_have_value('失败后保留的提示词')
        await page.get_by_role('button',name='重试保存',exact=True).click()
        await wait_article(lambda a:a['image_plans'][0]['prompt']=='失败后保留的提示词')
        await page.unroute('**/api/articles/*',reject_once)
        if await page.locator('.toast button').count():await page.locator('.toast button').click()
        blob=io.BytesIO();Image.new('RGB',(140,90),'green').save(blob,'PNG')
        async with page.expect_file_chooser() as chooser:await page.get_by_role('button',name='上传封面',exact=True).click()
        await (await chooser.value).set_files({'name':'synthetic.png','mimeType':'image/png','buffer':blob.getvalue()})
        await expect(page.locator('.image-card')).to_have_count(1)
        await nav('排版导出')
        await page.get_by_label('正文字号',exact=True).fill('18')
        await page.get_by_label('行距倍数',exact=True).fill('1.9')
        await page.get_by_label('行距倍数',exact=True).press('Tab')
        a=await wait_article(lambda a:a['layout']['font_size']==18 and a['layout']['line_height']==1.9)
        await expect(page.get_by_role('button',name='复制公众号排版',exact=True)).to_be_enabled()
        await page.get_by_role('button',name='复制公众号排版',exact=True).click()
        await expect(page.get_by_role('button',name='已复制',exact=True)).to_be_visible()
        async with page.expect_download() as download:await page.get_by_role('button',name='下载文章分享包',exact=True).click()
        await (await download.value).save_as(OUT/'synthetic-article.zip')
        await page.screenshot(path=str(OUT/'layout-desktop.png'),full_page=True)
        await nav('写作');await page.get_by_role('button',name='历史版本',exact=True).click()
        await expect(page.get_by_role('dialog')).to_contain_text('第 1 /')
        await page.get_by_role('dialog').get_by_role('button',name='关闭',exact=True).click()
        completed_id=a['id']
        fixture=await (await page.request.get(BASE+'/api/qa-fixture')).json()
        await page.goto(BASE+'/#'+fixture['id'])
        await page.get_by_role('tab',name='整理结果',exact=True).click()
        issue=page.locator('[data-issue="Q1"]')
        await page.get_by_text('本次资料核对',exact=True).click()
        await page.get_by_text('按问题查看检索过程 · 1 项',exact=True).click()
        await page.get_by_text('因果关系是否成立 · 已尝试计划渠道',exact=True).click()
        await expect(page.locator('.research-details')).to_contain_text('零结果')
        await page.get_by_text('候选资料的采用与排除 · 1 条',exact=True).click()
        await page.get_by_text('模拟候选 · 未优先采用',exact=True).click()
        await expect(page.locator('.research-details')).to_contain_text('未回答核心问题')
        await page.get_by_role('tab',name='本篇素材 · 1',exact=True).click()
        await page.locator('.source-title').click()
        await page.get_by_text('逐源阅读笔记 · 1 条',exact=True).click()
        await page.get_by_text('局限 · 不能推断因果',exact=True).click()
        await expect(page.locator('.source-card blockquote')).to_have_text('研究只支持关联。')
        await page.get_by_role('tab',name='整理结果',exact=True).click()
        await issue.get_by_role('button',name='展开问题',exact=True).click()
        await issue.get_by_role('button',name='本篇不使用',exact=True).click()
        await wait_article(lambda a:'训练必定有效。' not in a['content'])
        await page.get_by_role('button',name='已处理 · 1',exact=True).click()
        await expect(issue).to_contain_text('正文／大纲已更新')
        if await issue.get_by_role('button',name='展开问题',exact=True).count():await issue.get_by_role('button',name='展开问题',exact=True).click()
        await issue.get_by_role('button',name='撤销处理决定',exact=True).click()
        await wait_article(lambda a:'训练必定有效。' in a['content'])
        await expect(page.locator('.source-receipt')).to_contain_text('已有撤销或更新')
        await page.get_by_role('button',name='待处理 · 1',exact=True).click()
        if await issue.get_by_role('button',name='展开问题',exact=True).count():await issue.get_by_role('button',name='展开问题',exact=True).click()
        await issue.get_by_role('button',name='长证据资料',exact=True).click()
        await page.get_by_role('dialog').get_by_text('来源内容与元数据出处',exact=True).click()
        await expect(page.locator('.source-full')).to_contain_text('完整原文内容。'*100)
        await page.get_by_role('dialog').get_by_role('button',name='关闭',exact=True).click()
        for width in (1440,1100,390):
            await page.set_viewport_size({'width':width,'height':900})
            await page.evaluate('window.scrollTo(0,0)')
            await expect(page.locator('.source-search .primary')).to_have_text('查找并整理资料')
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
            await page.screenshot(path=str(OUT/f'materials-{width}.png'),full_page=True)
        opener=page.get_by_role('button',name='打开侧栏',exact=True)
        if not await opener.count():opener=page.get_by_role('button',name='展开侧栏',exact=True)
        await opener.click();await expect(page.locator('.context-drawer')).to_be_visible()
        await page.keyboard.press('Shift+Tab')
        assert await page.evaluate('document.querySelector(".context-drawer").contains(document.activeElement)')
        await page.keyboard.press('Escape');await expect(page.locator('.context-drawer')).to_have_count(0)
        await page.add_init_script("Object.defineProperty(window,'sessionStorage',{get(){throw new Error('Storage disabled')}})")
        await page.reload();await expect(page.locator('.source-search .primary')).to_be_visible()
        await page.get_by_role('tab',name='本篇素材 · 1',exact=True).click()
        await expect(page.locator('.source-card')).to_have_count(1)
        # Server-side library search and page controls, using temporary synthetic rows.
        for index in range(21):
            response=await page.request.post(BASE+'/api/articles',headers=H,data={'topic':f'分页验收 {index}'})
            assert response.ok
        await page.goto(BASE);await page.set_viewport_size({'width':1440,'height':1000})
        await page.get_by_label('搜索文章标题或主题',exact=True).fill('分页验收')
        await expect(page.locator('.library-card')).to_have_count(20)
        await page.locator('.library').get_by_role('button',name='下一页',exact=True).click()
        await expect(page.locator('.library-card')).to_have_count(1)
        await expect(page.locator('.library')).to_contain_text('第 2 / 2 页')
        assert not errors,errors
        (OUT/'result.json').write_text(json.dumps(dict(passed=True,simulated=True,article_id=completed_id,continuous_save=True,failed_save_retained=True,exclude_undo=True,limits_persist=True,full_workflow=True,viewports=[1440,1100,390],long_evidence=True,keyboard_drawer=True,storage_disabled=True),ensure_ascii=False,indent=2),'utf-8')
        print('PASS complete current UI workflow, saves, exclude/undo, evidence, widths, keyboard and storage restrictions')
    except BaseException:
        await page.screenshot(path=str(OUT/'failure.png'),full_page=True)
        (OUT/'failure.txt').write_text(await page.locator('body').inner_text(),'utf-8')
        raise
    finally:await browser.close()

if __name__=='__main__':asyncio.run(main())
