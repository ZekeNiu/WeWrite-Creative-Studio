"""Offline upgrade UX plus read-only validation of the actual workspace service."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8897'
VERSION=json.loads((ROOT/'package.json').read_text())['version']
ids=json.loads((ROOT/'output/test-workspaces/qa-optimizations/fixtures.json').read_text())
with sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge',headless=True)
    context=browser.new_context(viewport={'width':1440,'height':1000})
    page=context.new_page();page.set_default_timeout(15000)
    page.goto(BASE+'/#'+ids['editor'])
    expect(page.locator('.local-badge')).to_contain_text('v'+VERSION)
    expect(page.locator('.version-notice')).to_have_count(0)
    runtime={'version':'1.4.4'}
    page.route('**/api/health',lambda route:route.fulfill(json=runtime))
    page.evaluate("window.dispatchEvent(new Event('focus'))")
    expect(page.locator('.version-notice')).to_contain_text('后台 v1.4.4')
    expect(page.get_by_role('button',name='保存并刷新页面',exact=True)).to_have_count(0)
    runtime={'version':VERSION,'available_version':'9.9.9'}
    page.evaluate("window.dispatchEvent(new Event('focus'))")
    expect(page.locator('.version-notice')).to_contain_text('请重新双击')
    runtime={'version':'9.9.9','available_version':'9.9.9'}
    page.evaluate("window.dispatchEvent(new Event('focus'))")
    expect(page.get_by_role('button',name='保存并刷新页面',exact=True)).to_be_visible()
    page.get_by_role('button',name='Markdown 源文',exact=True).click()
    text='更新页面前尚未自动保存的正文。'
    page.get_by_role('textbox',name='Markdown 正文',exact=True).fill(text)
    page.get_by_role('button',name='保存并刷新页面',exact=True).click()
    expect(page.locator('.prose-editor')).to_contain_text(text)
    assert page.request.get(BASE+'/api/articles/'+ids['editor']).json()['content']==text
    page.get_by_role('button',name='Markdown 源文',exact=True).click()
    page.get_by_role('textbox',name='Markdown 正文',exact=True).fill('保存失败时必须留在页面的草稿。')
    page.route('**/api/articles/'+ids['editor'],lambda route:route.fulfill(status=409,json={'detail':'模拟保存冲突'}) if route.request.method=='PATCH' else route.continue_())
    page.get_by_role('button',name='保存并刷新页面',exact=True).click()
    expect(page.get_by_role('alert')).to_contain_text('模拟保存冲突')
    expect(page.get_by_role('textbox',name='Markdown 正文',exact=True)).to_have_value('保存失败时必须留在页面的草稿。')
    context.close()

    # The following actual-service validation must never write an article or call a model.
    state=json.loads((ROOT/'data/server.json').read_text())
    live='http://127.0.0.1:'+str(state['port'])
    context=browser.new_context(viewport={'width':1440,'height':1000})
    def readonly(route):
        request=route.request
        allowed=request.method in ('GET','HEAD') or request.url.endswith('/api/references/preview')
        route.continue_() if request.url.startswith(live) and allowed else route.abort()
    context.route('**/*',readonly)
    page=context.new_page();page.set_default_timeout(15000)
    health=page.request.get(live+'/api/health').json()
    assert health['version']==health['available_version']==VERSION
    articles=page.request.get(live+'/api/articles').json()
    target=None
    for row in articles:
        article=page.request.get(live+'/api/articles/'+row['id']).json()
        if article.get('review',{}).get('summary') and page.request.get(live+'/api/articles/'+row['id']+'/usage').json():
            target=article;break
    assert target,'Need an existing reviewed article for read-only acceptance'
    page.goto(live+'/?verify='+VERSION+'#'+target['id'])
    expect(page.locator('.local-badge')).to_contain_text('v'+VERSION)
    expect(page.locator('.version-notice')).to_have_count(0)
    page.locator('.stage-nav').filter(has=page.locator('strong',has_text='审核修改')).click()
    page.get_by_text('查看辅助评分与机械检查',exact=True).click()
    assert page.locator('.review-checks pre, .review-panel .detail-json').count()==0
    expect(page.locator('.review-checks')).to_contain_text('机械检查')
    page.get_by_role('button',name='调用记录',exact=True).click()
    expect(page.locator('.usage-table')).to_contain_text('状态')
    expect(page.locator('.usage-table')).not_to_contain_text('预估金额')
    page.get_by_role('button',name='关闭',exact=True).click()
    page.locator('.stage-nav').filter(has=page.locator('strong',has_text='配图')).click()
    assert page.get_by_text('本篇图片预算 / 元',exact=True).count()==0
    assert page.request.get(live+'/').headers['cache-control']=='no-store'
    context.close();browser.close()
print('Passed: update notices, save-before-refresh, save failure preserves draft; actual service version, usage table, review rendering and no-cache entry.')
