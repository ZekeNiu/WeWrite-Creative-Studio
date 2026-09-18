"""Browser acceptance for compact materials and batch semantics, using synthetic data."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright,expect

BASE='http://127.0.0.1:8896'
ids=json.loads(Path('output/test-workspaces/qa-v142/materials-fixtures.json').read_text())
OUT=Path('output/diagnostics/screenshots');OUT.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge',headless=True)
    page=browser.new_page(viewport={'width':1366,'height':768});page.set_default_timeout(20000)
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    writes=[];page.on('request',lambda r:writes.append(r.url) if r.method in ('POST','PATCH','PUT','DELETE') else None)
    def article(n):return page.request.get(BASE+'/api/articles/'+ids[str(n)]).json()
    def open_case(n):
        page.goto(BASE+'/#'+ids[str(n)])
        page.get_by_role('tab',name='本篇素材').wait_for()
    for n in (0,1,30):
        open_case(n);a=article(n);before=len(writes)
        panel=page.get_by_role('tabpanel',name='本篇素材',exact=True)
        expect(panel).to_be_visible();assert panel.locator('.source-card').count()==min(n,10)
        page.get_by_role('tab',name='资料整理结果',exact=True).click();page.get_by_role('tab',name='本篇素材').click()
        if n:
            panel.get_by_role('button',name='展开本页',exact=True).click();panel.get_by_role('button',name='收起本页',exact=True).click()
        if n==30:
            panel.get_by_role('button',name='下一页').click();page.reload()
            expect(page.get_by_role('tabpanel',name='本篇素材',exact=True)).to_contain_text('第 2 / 3 页')
        assert len(writes)==before and article(n)['revision']==a['revision']
    open_case(100)
    expect(page.get_by_role('tabpanel',name='资料整理结果',exact=True)).to_be_visible()
    results=page.get_by_role('tabpanel',name='资料整理结果',exact=True)
    results.get_by_role('checkbox',name='全选当前页待处理项').check()
    results.get_by_role('button',name='忽略所选并保留边界（10）',exact=True).click()
    results.get_by_role('button',name='已处理 · 11',exact=True).click()
    assert sum(x['status']=='waived' for x in article(100)['research']['issues'])==10
    handled=results.locator('.research-issue').first
    handled.get_by_role('button',name='展开问题').click();handled.get_by_role('button',name='撤销忽略').click()
    results.get_by_role('button',name='需要处理 · 16',exact=True).click()
    page.get_by_role('tab',name='本篇素材').click();panel=page.get_by_role('tabpanel',name='本篇素材',exact=True)
    panel.get_by_role('textbox',name='搜索本篇素材').fill('匹配材料');expect(panel).to_contain_text('共 30 条')
    before=article(100);panel.get_by_role('button',name='全部不采用',exact=True).click()
    expect(panel.locator('.source-card input[type=checkbox]').first).not_to_be_checked()
    page.wait_for_function("document.querySelector('.material-overview').textContent.includes('46 / 100')")
    after=article(100);assert after['revision']==before['revision']+1 and len(after['sources'])==100
    assert [s['selected'] for s in after['sources'][30:]]==[s['selected'] for s in before['sources'][30:]]
    assert not any(s['selected'] for s in after['sources'][:30])
    panel.get_by_role('button',name='全部采用',exact=True).dblclick()
    page.wait_for_function("document.querySelector('.material-overview').textContent.includes('76 / 100')")
    assert article(100)['revision']==after['revision']+1
    # A rejected mutation must not optimistically alter adoption.
    url=BASE+'/api/articles/'+ids['100']
    page.route(url,lambda route:route.fulfill(status=409,json={'detail':'模拟版本冲突'}) if route.request.method=='PATCH' else route.continue_(),times=1)
    first=panel.locator('.source-card').first;first.get_by_role('checkbox').click()
    page.get_by_text('模拟版本冲突',exact=True).wait_for();expect(first.get_by_role('checkbox')).to_be_checked()
    # Manual override, reset, and explicit experience authorization.
    first=panel.locator('.source-card').nth(1);first.locator('.source-title').click();field=first.get_by_role('textbox',name='这份素材的用途')
    field.fill('人工指定的用途');field.press('Tab');expect(first).to_contain_text('人工指定：人工指定的用途')
    first.get_by_role('button',name='恢复 AI 判断').click();expect(first).to_contain_text('AI 判断')
    assert not article(100)['sources'][0]['personal_material']
    page.locator('.toast button').click()
    first.locator('.source-title').click()
    assert first.locator('p').first.evaluate('(el)=>getComputedStyle(el).webkitLineClamp')=='2'
    page.get_by_role('tab',name='本篇素材').scroll_into_view_if_needed()
    for width,height in ((1366,768),(1280,800)):
        page.set_viewport_size({'width':width,'height':height});assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        page.screenshot(path=str(OUT/f'materials-v142-{width}.png'))
    # Paused entry focuses a specific expandable issue; navigating never writes.
    before=article(100)['revision'];page.get_by_role('button',name='处理核实问题',exact=True).click()
    results=page.get_by_role('tabpanel',name='资料整理结果',exact=True)
    expect(results).to_be_visible();expect(results.locator('.research-issue').first.get_by_role('button',name='AI 核实',exact=True)).to_be_visible()
    results.get_by_role('checkbox',name='全选当前页待处理项',exact=True).check();expect(results).to_contain_text('已选 10 项')
    results.get_by_role('button',name='下一页').click();expect(results).to_contain_text('已选 0 项')
    assert article(100)['revision']==before
    # Stale material disables ignore, but allows supplying evidence.
    results.locator('.research-issue').first.get_by_role('button',name='展开问题').click()
    results.locator('.research-issue').first.get_by_role('button',name='补充资料').click()
    page.get_by_role('dialog').get_by_role('button',name='粘贴文字').click()
    page.get_by_role('textbox',name='素材名称').fill('新增补充');page.get_by_role('textbox',name='素材正文').fill('补充关键范围。')
    page.get_by_role('button',name='添加素材',exact=True).click();page.get_by_role('button',name='返回对应核实问题').click()
    expect(results.locator('.research-issue').filter(has_text='第 11 项').get_by_role('button',name='忽略并继续')).to_be_disabled()
    assert len(article(100)['sources'])==101
    page.get_by_role('tab',name='本篇素材').click()
    page.locator('.stage-nav').nth(3).click();page.locator('.stage-nav').nth(1).click()
    expect(page.get_by_role('tabpanel',name='本篇素材',exact=True)).to_be_visible()
    assert not errors,errors
    browser.close()
report=dict(simulated=True,counts=[0,1,30,100],view_only_no_writes=True,batch_scope=True,duplicate_protection=True,conflict_preserved=True,manual_use=True,issue_pagination=True,batch_ignore_and_undo=True,supplement_return=True,layouts=[1366,1280],console_errors=errors)
Path('output/diagnostics/ui-v142.json').write_text(json.dumps(report,indent=2),'utf-8');print(json.dumps(report))
