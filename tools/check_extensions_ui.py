"""Contextual tool flows against the isolated server; all model/WeChat IO is mocked."""
import asyncio
import io
import json
import os
import sys
from pathlib import Path
from PIL import Image
from playwright.async_api import async_playwright,expect


async def check(page,base,out):
    assert (await page.request.get(base+'/api/qa-fixture')).ok,'Use the isolated QA server'
    headers={'X-Studio-Request':'1'}
    a=await (await page.request.post(base+'/api/articles',headers=headers,data=dict(topic='扩展验收'))).json()
    original='这份模拟文章用于检查独立功能。我们保留原稿，只创建独立平台版本，并核对每个工具返回的实际结果。'*8
    a=await (await page.request.patch(base+'/api/articles/'+a['id'],headers=headers,data=dict(revision=a['revision'],stage='write',changes=dict(content=original,current_stage='write')))).json()
    blob=io.BytesIO();Image.new('RGB',(80,60),'green').save(blob,'PNG')
    response=await page.request.post(base+'/api/articles/'+a['id']+'/images/upload',headers=headers,multipart=dict(revision=str(a['revision']),role='cover',file=dict(name='fixture.png',mimeType='image/png',buffer=blob.getvalue())))
    assert response.ok
    a=await response.json()
    b=await (await page.request.post(base+'/api/articles',headers=headers,data=dict(topic='另篇模拟文章'))).json()
    started=[]
    def requests(request):
        if request.method=='POST' and request.url==base+'/api/extensions/actions':started.append(request.post_data_json)
    page.on('request',requests)

    async def stage(name):await page.locator('.stage-nav').filter(has=page.locator('strong',has_text=name)).click()
    async def close(dialog):await dialog.get_by_role('button',name='关闭',exact=True).click()
    async def tool(name):
        await page.get_by_role('button',name=name,exact=True).click()
        dialog=page.get_by_role('dialog',name=name,exact=True)
        await expect(dialog).to_be_visible()
        return dialog
    async def screenshot(name,dialog=None):
        for width in (1440,390):
            await page.set_viewport_size(dict(width=width,height=900))
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            if dialog:assert await dialog.evaluate('(el)=>el.scrollWidth<=el.clientWidth+1')
            await page.evaluate('window.scrollTo(0,0)')
            if dialog:await dialog.evaluate('(el)=>el.scrollTop=0')
            await page.wait_for_timeout(100)
            await page.screenshot(path=str(out/f'{name}-{width}.png'),full_page=True)
        await page.set_viewport_size(dict(width=1440,height=1000))

    await page.goto(base+'/#'+a['id'])
    await expect(page.get_by_role('button',name='扩展',exact=True)).to_have_count(0)
    await page.get_by_role('tab',name='写作设置',exact=True).click()
    await page.get_by_label('语气与表达偏好',exact=True).locator('xpath=ancestor::details').locator('summary').click()
    await page.get_by_label('语气与表达偏好',exact=True).fill('模拟：保留自然语气')
    dialog=await tool('管理自定义人格')
    assert (await (await page.request.get(base+'/api/articles/'+a['id'])).json())['brief']['tone']=='模拟：保留自然语气'
    await dialog.get_by_text('高级：人格编号',exact=True).click()
    await dialog.get_by_label('自定义人格编号',exact=True).fill('user-fixture')
    await dialog.get_by_label('人格显示名称',exact=True).fill('验收读书人')
    await dialog.get_by_label('人格与语感',exact=True).fill('从具体问题展开，保留自然的声音。')
    await dialog.get_by_role('button',name='保存自定义人格',exact=True).click()
    await expect(dialog.get_by_role('button',name='编辑人格',exact=True)).to_be_visible()
    await screenshot('persona',dialog);await close(dialog)
    await expect(page.get_by_label('写作人格',exact=True).locator('option[value="user-fixture"]')).to_have_count(1)
    await expect(page.get_by_label('写作人格',exact=True)).to_have_value(a['brief']['persona'])

    await stage('排版导出')
    dialog=await tool('从文章学习排版')
    await dialog.get_by_label('公众号排版参考链接',exact=True).fill('https://mp.weixin.qq.com/s/fixture-theme')
    await dialog.get_by_text('高级：主题编号',exact=True).click()
    await dialog.get_by_label('新主题编号',exact=True).fill('user-fixture-theme')
    await dialog.get_by_label('新主题显示名称',exact=True).fill('验收学习主题')
    await dialog.get_by_role('button',name='学习并保存主题',exact=True).click()
    await expect(dialog).to_contain_text('主题已加入排版下拉框')
    await close(dialog)
    await expect(page.get_by_label('排版主题',exact=True).locator('option[value="user-fixture-theme"]')).to_have_count(1)
    await expect(page.get_by_label('排版主题',exact=True)).to_have_value(a['layout']['theme'])
    dialog=await tool('多平台改写')
    await dialog.get_by_role('button',name='生成独立平台稿',exact=True).click()
    await expect(dialog.get_by_role('button',name='停止此任务',exact=True)).to_be_visible()
    await close(dialog)
    dialog=await tool('多平台改写')
    await expect(dialog).to_contain_text('与源稿／其他平台最大相似度')
    assert len([x for x in started if x['action']=='rewrite'])==1
    await expect(dialog).not_to_contain_text('主题已加入排版下拉框')
    await close(dialog);await page.reload();await stage('排版导出')
    dialog=await tool('多平台改写')
    await expect(dialog).to_contain_text('与源稿／其他平台最大相似度')
    await screenshot('rewrite',dialog);await close(dialog)

    dialog=await tool('推送微信草稿')
    await dialog.get_by_label('微信摘要',exact=True).fill('连接往返后仍应保留')
    await dialog.get_by_role('button',name='配置公众号连接',exact=True).click()
    account=page.get_by_role('dialog',name='账号与学习',exact=True)
    await expect(dialog).to_have_count(0)
    await expect(account.get_by_label('公众号 AppID',exact=True)).to_be_visible()
    await account.get_by_label('公众号 AppID',exact=True).fill('wx1234567890')
    await account.get_by_label('公众号 AppSecret',exact=True).fill('synthetic-wechat-secret')
    await account.get_by_role('button',name='保存公众号连接',exact=True).click()
    await expect(account).to_contain_text('已保存凭证')
    await expect(account.get_by_label('公众号 AppSecret',exact=True)).to_have_value('')
    await screenshot('connection',account);await close(account)
    await expect(dialog.get_by_label('微信摘要',exact=True)).to_have_value('连接往返后仍应保留')
    assert not [x for x in started if x['action'] in ('publish','image_post')]
    for kind,label in [('publish','将此文章推送到微信草稿箱'),('image_post','将采用图片推送为图片帖')]:
        await dialog.get_by_label('草稿类型',exact=True).select_option(kind)
        await dialog.get_by_role('button',name='查看推送预览',exact=True).click()
        await expect(dialog.get_by_role('button',name=label,exact=True)).to_be_enabled()
        if kind=='publish':
            await dialog.get_by_label('微信摘要',exact=True).fill('更新后的摘要')
            await expect(dialog.get_by_role('button',name=label,exact=True)).to_have_count(0)
            await dialog.get_by_role('button',name='查看推送预览',exact=True).click()
            await expect(dialog.get_by_role('button',name=label,exact=True)).to_be_enabled()
            await screenshot('publish',dialog)
        await dialog.get_by_role('button',name=label,exact=True).click()
        await expect(dialog.get_by_role('button',name='查看推送预览',exact=True)).to_be_enabled()
        await expect(dialog).to_contain_text('offline-draft-')
    assert len([x for x in started if x['action'] in ('publish','image_post')])==2
    await dialog.get_by_role('button',name='读取微信草稿副本',exact=True).click()
    await expect(dialog).to_contain_text('微信模拟人工修改副本')
    await close(dialog)

    account=await tool('账号与学习')
    await account.get_by_role('button',name='效果记录',exact=True).click()
    effects=account.get_by_role('region',name='微信数据与复盘',exact=True)
    await effects.get_by_label('微信统计文章编号（msgid）',exact=True).fill('123456_1')
    await effects.get_by_role('button',name='关联所选文章',exact=True).click()
    await expect(effects).to_contain_text('扩展验收 · 123456_1')
    await effects.get_by_role('button',name='拉取并回填在线效果',exact=True).click()
    await expect(effects).to_contain_text('阅读 120，分享 8，点赞 未知')
    await effects.get_by_role('button',name='复盘已有数据（AI）',exact=True).click()
    await expect(effects).to_contain_text('当前数据只能描述已有样本')
    await expect(effects).not_to_contain_text('offline-draft-')
    await screenshot('effects',account)
    arrived=asyncio.Event();release=asyncio.Event()
    async def delayed(route):
        if 'article_id='+a['id'] in route.request.url:
            response=await route.fetch();arrived.set();await release.wait();await route.fulfill(response=response)
        else:await route.continue_()
    await page.route('**/api/extensions/jobs?*',delayed)
    await account.get_by_label('关联文章',exact=True).select_option(b['id'])
    await account.get_by_label('关联文章',exact=True).select_option(a['id'])
    await asyncio.wait_for(arrived.wait(),10)
    await account.get_by_label('关联文章',exact=True).select_option(b['id'])
    release.set();await page.wait_for_timeout(250)
    await expect(effects).not_to_contain_text('当前数据只能描述已有样本')
    await expect(effects).not_to_contain_text('123456_1')
    await page.unroute('**/api/extensions/jobs?*',delayed)
    await account.get_by_label('关联文章',exact=True).select_option(a['id'])
    await expect(effects).to_contain_text('当前数据只能描述已有样本')
    await close(account)

    async def fail(route):await route.fulfill(status=500,json=dict(detail='模拟服务失败，成果仍保留'))
    await page.route('**/api/extensions/actions',fail)
    dialog=await tool('多平台改写')
    await dialog.get_by_role('button',name='生成独立平台稿',exact=True).click()
    await expect(dialog.get_by_role('alert')).to_contain_text('模拟服务失败')
    await expect(dialog).to_contain_text('与源稿／其他平台最大相似度')
    assert len([x for x in started if x['action']=='rewrite'])==2
    await close(dialog);await page.unroute('**/api/extensions/actions',fail)

    dialog=await tool('多平台改写')
    await dialog.get_by_role('button',name='生成独立平台稿',exact=True).click()
    await dialog.get_by_role('button',name='停止此任务',exact=True).click()
    await expect(dialog.get_by_role('button',name='生成独立平台稿',exact=True)).to_be_enabled()
    rows=await (await page.request.get(base+'/api/extensions/jobs?action=rewrite&article_id='+a['id'])).json()
    assert rows['items'][0]['status']=='cancelled'
    assert any(j.get('result',{}).get('outputs') for j in rows['items'] if j.get('result'))
    await close(dialog)

    await page.get_by_label('排版主题',exact=True).select_option('user-fixture-theme')
    await expect(page.get_by_role('button',name='复制公众号排版',exact=True)).to_be_enabled()
    await expect(page.locator('.theme-swatches button').first).to_be_visible()
    await expect(page.get_by_label('正文字号',exact=True)).to_be_visible()
    await expect(page.get_by_title('公众号排版预览',exact=True)).to_be_visible()
    await screenshot('layout-context')
    await page.set_viewport_size(dict(width=390,height=844))
    await page.locator('.mobile-extras summary').click()
    await expect(page.locator('.mobile-menu')).not_to_contain_text('扩展')
    await page.locator('.mobile-menu').get_by_role('button',name='账号与学习',exact=True).click()
    await close(account)
    for name in ('从文章学习排版','多平台改写','推送微信草稿'):await close(await tool(name))
    await page.set_viewport_size(dict(width=1440,height=1000))
    final=await (await page.request.get(base+'/api/articles/'+a['id'])).json()
    assert final['content']==original and any(x['action']=='publish' for x in final['extensions'])
    assert all(x['article_id']==a['id'] for x in started if x['action']!='theme')
    assert all(not x['article_id'] for x in started if x['action']=='theme')
    page.remove_listener('request',requests)
    await check_preview_race(page,base)


async def check_preview_race(page,base):
    headers={'X-Studio-Request':'1'}
    a=await (await page.request.post(base+'/api/articles',headers=headers,data=dict(topic='模拟：预览等待时修改摘要'))).json()
    response=await page.request.patch(base+'/api/articles/'+a['id'],headers=headers,data=dict(revision=a['revision'],stage='write',changes=dict(content='模拟正文。'*50,current_stage='layout')))
    assert response.ok
    await page.goto(base+'/#'+a['id'])
    await page.locator('.stage-nav').filter(has=page.locator('strong',has_text='排版导出')).click()
    await page.get_by_role('button',name='推送微信草稿',exact=True).click()
    dialog=page.get_by_role('dialog',name='推送微信草稿',exact=True)
    button=dialog.get_by_role('button',name='查看推送预览',exact=True)
    await expect(button).to_be_enabled()
    await dialog.get_by_label('微信摘要',exact=True).fill('请求开始时的摘要')
    arrived=asyncio.Event();release=asyncio.Event()
    async def delayed(route):
        response=await route.fetch();arrived.set();await release.wait();await route.fulfill(response=response)
    await page.route('**/api/extensions',delayed)
    try:
        await button.click();await asyncio.wait_for(arrived.wait(),10)
        await dialog.get_by_label('微信摘要',exact=True).fill('等待期间新输入的摘要')
        release.set();await expect(button).to_be_enabled()
        await expect(dialog.get_by_role('button',name='将此文章推送到微信草稿箱',exact=True)).to_have_count(0,timeout=5000)
    finally:release.set();await page.unroute('**/api/extensions',delayed)
    await button.click()
    await expect(dialog.get_by_role('button',name='将此文章推送到微信草稿箱',exact=True)).to_have_count(1)
    await expect(dialog).to_contain_text('微信摘要：等待期间新输入的摘要')
    await dialog.get_by_role('button',name='关闭',exact=True).click()


async def main():
    base=os.environ.get('QA_BASE','http://127.0.0.1:8977')
    out=Path(__file__).resolve().parents[1]/'output/playwright/v238';out.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as p:
        browser=await p.chromium.launch(channel='msedge',headless=True)
        context=await browser.new_context(viewport=dict(width=1440,height=1000))
        await context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(base) else r.abort())
        page=await context.new_page();page.set_default_timeout(30000);errors=[]
        page.on('pageerror',lambda e:errors.append(str(e)))
        try:
            if '--preview-race' in sys.argv:await check_preview_race(page,base)
            else:await check(page,base,out)
            assert not errors,errors
            print(json.dumps(dict(passed=True,contextual_entries=True,task_recovery=True,article_isolation=True,connection_return=True,preview_invalidation=True,desktop=True,mobile=True,errors=errors)))
        except BaseException:
            await page.screenshot(path=str(out/'failure.png'),full_page=True)
            (out/'failure.txt').write_text(await page.locator('body').inner_text(),'utf-8');raise
        finally:await browser.close()


if __name__=='__main__':asyncio.run(main())
