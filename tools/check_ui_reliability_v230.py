"""v2.3 regression acceptance. Run only against qa_reliability_app (no paid IO)."""
import asyncio
import json
import os
from datetime import datetime,timezone,timedelta
from pathlib import Path
from playwright.async_api import async_playwright,expect

BASE=os.environ.get('QA_BASE','http://127.0.0.1:8977')
OUT=Path(__file__).resolve().parents[1]/'output/playwright/reliability'
H={'X-Studio-Request':'1'}


async def main():
 async with async_playwright() as p:
    browser=await p.chromium.launch(channel='msedge',headless=True)
    context=await browser.new_context(viewport=dict(width=1440,height=1000))
    await context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(BASE) else r.abort())
    page=await context.new_page();page.set_default_timeout(15000);errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    async def nav(label):
        await page.locator('.stage-nav').filter(has=page.locator('strong',has_text=label)).click()
        await expect(page.locator('.workspace-title h1')).to_have_text(label)
    async def article():return await (await page.request.get(BASE+'/api/articles/'+aid)).json()
    async def saved(check):
        for _ in range(150):
            a=await article()
            if check(a):return a
            await asyncio.sleep(.1)
        raise AssertionError('Draft or article was not saved')
    async def patch(changes,stage='preferences'):
        a=await article()
        r=await page.request.patch(BASE+'/api/articles/'+aid,headers=H,data=dict(revision=a['revision'],stage=stage,changes=changes))
        assert r.ok,await r.text()
        return await r.json()
    try:
        # A separate article; no production data and no automatic chain.
        a=await (await page.request.post(BASE+'/api/articles',headers=H,data={})).json();aid=a['id']
        await page.goto(BASE+'/#'+aid)
        await page.get_by_label('指定文章主题',exact=True).fill('未采用的选题草稿')
        await page.get_by_label('这次想怎样探索（可选）',exact=True).fill('探索要求甲')
        await nav('素材');await nav('选题');await page.reload();await nav('选题')
        await expect(page.get_by_label('指定文章主题',exact=True)).to_have_value('未采用的选题草稿')
        await expect(page.get_by_label('这次想怎样探索（可选）',exact=True)).to_have_value('探索要求甲')
        assert not (await article())['brief']['topic']
        assert '处理条件' in await page.locator('.stage-footer').inner_text()

        failing=True
        async def fail_save(route):
            if failing and route.request.method=='PATCH':await route.fulfill(status=503,json={'detail':'模拟保存失败'})
            else:await route.continue_()
        await page.route('**/api/articles/'+aid,fail_save)
        await page.get_by_label('这次想怎样探索（可选）',exact=True).fill('保存失败仍应保留')
        await expect(page.get_by_text('未保存，请重试；输入已保留',exact=False)).to_be_visible()
        await page.locator('.stage-nav').filter(has=page.locator('strong',has_text='素材')).click()
        await expect(page.locator('.workspace-title h1')).to_have_text('选题')
        await expect(page.get_by_label('这次想怎样探索（可选）',exact=True)).to_have_value('保存失败仍应保留')
        failing=False
        await page.get_by_role('button',name='重试保存',exact=True).click()
        await saved(lambda a:a.get('input_drafts',{}).get('topic_feedback')=='保存失败仍应保留')
        await page.unroute('**/api/articles/'+aid,fail_save)

        requests=[]
        def collect(req):
            if req.method=='POST' and req.url==BASE+'/api/articles/'+aid+'/jobs':requests.append(req.post_data_json)
        page.on('request',collect)
        await page.get_by_label('这次想怎样探索（可选）',exact=True).fill('空状态入口最新要求')
        await page.get_by_role('button',name='寻找选题灵感',exact=True).click()
        await expect(page.locator('.topic-card')).to_have_count(6)
        assert len(requests)==1 and requests[-1]['instruction']=='空状态入口最新要求'
        await page.get_by_label('这次想怎样探索（可选）',exact=True).fill('顶部入口最新要求')
        # Dispatch both clicks in one event turn to exercise the synchronous lock.
        await page.get_by_role('button',name='换一批选题',exact=True).evaluate('(el)=>{el.click();el.click()}')
        await expect(page.get_by_role('button',name='换一批选题',exact=True)).to_be_enabled(timeout=20000)
        assert len(requests)==2 and requests[-1]['instruction']=='顶部入口最新要求'
        await page.get_by_role('button',name='就写这个',exact=True).first.click()
        await saved(lambda a:bool(a['brief']['topic']))
        await nav('素材');await page.get_by_label('补充检索要求',exact=True).fill('检索要求也应保存')
        await nav('选题');await page.reload();await nav('素材')
        await expect(page.get_by_label('补充检索要求',exact=True)).to_have_value('检索要求也应保存')

        # Failed chained job: reminder is scoped, retry targets the failed stage.
        stamp=datetime.now(timezone.utc).isoformat()
        failure=dict(id='synthetic-failed-chain',article_id=aid,stage='outline',status='failed',created=stamp,ended=stamp,
            request=dict(stage='topic',instruction='旧选题要求',chain=True),message='模型服务请求限流',
            retry_request=dict(stage='outline',revision=0,chain=True),execution_usage=dict(requests=4),
            failure=dict(category='rate_limit',http_status=429,provider_code='rate_limit_exceeded',request_id='qa-request',
                retry_at=(datetime.now(timezone.utc)+timedelta(seconds=3)).isoformat(),service=dict(name='实际失败服务',model='qa-model')))
        async def failed_list(route):await route.fulfill(json=[failure])
        await page.route('**/api/articles/'+aid+'/jobs',failed_list)
        await page.reload();await nav('素材')
        await expect(page.locator('.task-status')).to_have_count(0)
        await page.get_by_role('button',name='查看大纲任务',exact=True).click()
        await expect(page.locator('.task-status')).to_contain_text('实际失败服务')
        await page.get_by_text('查看错误详情',exact=True).click()
        await expect(page.locator('.failure-details')).to_contain_text('请求限流')
        await page.unroute('**/api/articles/'+aid+'/jobs',failed_list)
        retries=[]
        async def capture_retry(route):
            if route.request.method=='POST':
                retries.append(route.request.post_data_json);await route.fulfill(json={**failure,'id':'synthetic-retry'})
            else:await route.continue_()
        await page.route('**/api/articles/'+aid+'/jobs',capture_retry)
        await page.get_by_role('button',name='重新运行大纲',exact=True).click()
        assert len(retries)==1 and retries[0]['stage']=='outline' and not retries[0].get('instruction')
        await page.unroute('**/api/articles/'+aid+'/jobs',capture_retry)

        # Explicit settings saving, keyboard close, discard, save and targeted route.
        await nav('选题');await page.get_by_role('button',name='调整选题服务',exact=True).first.click()
        settings=page.get_by_role('dialog',name='AI 服务与偏好',exact=True)
        await expect(settings.locator('#route-topic')).to_be_visible()
        await settings.get_by_role('button',name='模型服务',exact=True).click()
        service=settings.get_by_label('服务名称 / 分组备注',exact=True).first
        original=await service.input_value();await service.fill('尚未保存的服务')
        await page.keyboard.press('Escape')
        confirm=page.get_by_role('dialog',name='设置尚未保存',exact=True)
        await expect(confirm).to_be_visible();await confirm.get_by_role('button',name='继续编辑').click()
        await expect(service).to_have_value('尚未保存的服务')
        await settings.get_by_role('button',name='关闭',exact=True).click();await confirm.get_by_role('button',name='放弃修改').click()
        await page.get_by_role('button',name='AI 服务与设置',exact=True).click()
        await expect(service).to_have_value(original)
        await service.fill('验收服务名称');await page.keyboard.press('Escape')
        await confirm.get_by_role('button',name='保存并关闭').click()
        await expect(settings).to_have_count(0)
        cfg=await (await page.request.get(BASE+'/api/settings')).json();assert cfg['services'][0]['name']=='验收服务名称'
        cfg['services'][0]['name']=original;assert (await page.request.put(BASE+'/api/settings',headers=H,data=cfg)).ok

        # Outline keyboard alternatives and preservation of deliberate word counts.
        await patch(dict(brief={**(await article())['brief'],'words':3200}))
        await patch(dict(outline=dict(thesis='测试主张',reader_question='测试问题',takeaway='测试所得',sections=[dict(id='qa-one',title='第一节',purpose='甲',points=['A'],claim_ids=[]),dict(id='qa-two',title='第二节',purpose='乙',points=['B'],claim_ids=[])])),'outline')
        await patch(dict(content='## 第一节\n\n可选择的正文。\n\n## 第二节\n\n另一段正文。'),'write')
        await page.reload();await nav('大纲')
        await page.get_by_role('button',name='下移章节 第一节',exact=True).click()
        await saved(lambda a:a['outline']['sections'][0]['id']=='qa-two')
        first=page.locator('.outline-card').first
        await first.get_by_role('button',name='收起',exact=True).click()
        await expect(first.get_by_label('这一节推进什么',exact=True)).to_be_hidden()
        await first.get_by_role('button',name='删除本节',exact=True).click()
        await expect(page.locator('.outline-card')).to_have_count(1)
        await page.get_by_role('button',name='撤销删除',exact=True).click()
        await expect(page.locator('.outline-card')).to_have_count(2)
        await nav('选题');await page.get_by_role('tab',name='写作设置',exact=True).click()
        await page.get_by_label('目标读者',exact=True).select_option(index=1)
        assert (await saved(lambda a:a['brief']['audience']=='专业解读'))['brief']['words']==3200

        for width in (1440,1100,390):
            await page.set_viewport_size(dict(width=width,height=900))
            for label in ('选题','素材','大纲','写作','审核修改','配图','排版导出'):
                await nav(label)
                assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'),(width,label)
                assert await page.locator('.stage-nav[aria-current="step"]').count()==1
                assert all(await page.locator('.stage-nav').evaluate_all('(els)=>els.map(e=>!!e.getAttribute("aria-label")&&getComputedStyle(e.querySelector("strong")).display!=="none")'))
                assert await page.locator('.header-settings').evaluate('(e)=>e.getBoundingClientRect().bottom<=document.querySelector(".app-header").getBoundingClientRect().bottom')
                if label=='排版导出':
                    await expect(page.get_by_role('switch')).to_have_count(0)
                    await expect(page.get_by_label('排版主题',exact=True)).to_be_visible()
                await page.evaluate('window.scrollTo(0,0)')
                await page.screenshot(path=str(OUT/f'v230-{label}-{width}.png'),full_page=True)
            await nav('审核修改')
            await page.locator('.prose-editor').evaluate('(e)=>{const r=document.createRange();r.selectNodeContents(e.querySelector("p"));const s=getSelection();s.removeAllRanges();s.addRange(r);document.dispatchEvent(new Event("selectionchange"))}')
            await page.get_by_role('button',name='打开 AI 修改',exact=True).click()
            await expect(page.locator('.workspace-title h1')).to_have_text('写作')
            await expect(page.get_by_label('已选中的内容',exact=True)).not_to_have_value('')
            await expect(page.get_by_role('tab',name='AI 修改',exact=True)).to_be_visible()
            await page.get_by_role('button',name='关闭侧栏',exact=True).click()
        # Delayed results belong to their article, even after hash navigation.
        await page.set_viewport_size(dict(width=1440,height=1000))
        other=await (await page.request.post(BASE+'/api/articles',headers=H,data=dict(topic='另一篇验收文章'))).json()
        active={**failure,'id':'qa-delayed-job','status':'running','stage':'topic','request':dict(stage='topic',chain=False)}
        started=asyncio.Event();release=asyncio.Event();delivered=asyncio.Event()
        async def active_list(route):await route.fulfill(json=[active])
        async def delayed_job(route):
            started.set();await release.wait();await route.fulfill(json={**failure,'id':active['id']});delivered.set()
        await page.route('**/api/articles/'+aid+'/jobs',active_list)
        await page.route('**/api/jobs/'+active['id'],delayed_job)
        await page.reload();await asyncio.wait_for(started.wait(),10)
        await page.evaluate('(id)=>location.hash=id',other['id'])
        await expect(page.locator('.header-center')).to_contain_text('另一篇验收文章')
        release.set();await asyncio.wait_for(delivered.wait(),10)
        await expect(page.locator('.header-center')).to_contain_text('另一篇验收文章')
        await expect(page.locator('.task-status')).to_have_count(0)
        await page.unroute('**/api/articles/'+aid+'/jobs',active_list)
        await page.unroute('**/api/jobs/'+active['id'],delayed_job)
        # A slow article-open request must not replace a newer selection either.
        waiting=asyncio.Event();unblock=asyncio.Event();finished=asyncio.Event();first_article=await article()
        async def slow_article(route):
            waiting.set();await unblock.wait();await route.fulfill(json=first_article);finished.set()
        await page.route('**/api/articles/'+aid,slow_article)
        await page.evaluate('(id)=>location.hash=id',aid);await asyncio.wait_for(waiting.wait(),10)
        await page.get_by_role('button',name='返回文章库',exact=True).click()
        await expect(page.locator('.home')).to_be_visible()
        unblock.set();await asyncio.wait_for(finished.wait(),10)
        await expect(page.locator('.home')).to_be_visible()
        await page.unroute('**/api/articles/'+aid,slow_article)
        assert not errors,errors
        print('v2.3 UI acceptance passed: drafts, failures, retry, settings, outline, word count, 21 stage/width views and AI selection')
    except Exception:
        OUT.mkdir(parents=True,exist_ok=True);await page.screenshot(path=str(OUT/'v230-failure.png'),full_page=True);raise
    finally:await browser.close()


if __name__=='__main__':asyncio.run(main())
