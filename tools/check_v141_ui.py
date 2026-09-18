"""Browser checks for paused work, controls, stale materials and recovery."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright,expect

OUT=Path('output/diagnostics/screenshots');OUT.mkdir(parents=True,exist_ok=True)
aid=json.loads(Path('output/test-workspaces/qa-v14/workflow-fixture.json').read_text())['article_id']
with sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge',headless=True)
    page=browser.new_page(viewport={'width':1366,'height':768});page.set_default_timeout(30000)
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto('http://127.0.0.1:8895/#'+aid)
    page.get_by_role('button',name='处理核实问题',exact=True).wait_for()
    page.locator('.stage-nav').nth(3).click()
    expect(page.get_by_role('button',name='生成初稿',exact=True)).to_be_disabled()
    page.get_by_role('button',name='前往素材',exact=True).click()
    issue=page.locator('.research-issue').first
    issue.get_by_role('button',name='展开问题',exact=True).click()
    issue.get_by_role('button',name='忽略并继续',exact=True).click()
    page.get_by_role('button',name='已处理 · 1',exact=True).click()
    issue.get_by_role('button',name='撤销忽略',exact=True).wait_for()
    page.get_by_role('button',name='继续生成大纲',exact=True).wait_for()
    issue.get_by_role('button',name='撤销忽略',exact=True).click()
    page.get_by_role('button',name='需要处理 · 1',exact=True).click()
    issue.get_by_role('button',name='补充资料',exact=True).click()
    page.get_by_role('dialog').get_by_role('button',name='粘贴文字',exact=True).click()
    page.get_by_role('textbox',name='素材名称',exact=True).fill('验收补充')
    page.get_by_role('textbox',name='素材正文',exact=True).fill('已补充关键范围，研究只适用于给定条件。')
    page.get_by_role('button',name='添加素材',exact=True).click()
    expect(issue.get_by_role('button',name='忽略并继续',exact=True)).to_be_disabled()
    page.reload();page.locator('.stage-nav').nth(1).click()
    page.locator('.research-issue').first.get_by_role('button',name='AI 核实',exact=True).click()
    page.get_by_role('button',name='继续生成大纲',exact=True).wait_for()
    page.locator('.research-history').last.locator('summary').first.click()
    expect(page.locator('.research-history').last).to_contain_text('历次检索与核对')
    for width,height in [(1366,768),(1280,800)]:
        page.set_viewport_size({'width':width,'height':height})
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        page.screenshot(path=str(OUT/f'workflow-v141-{width}.png'))
    page.get_by_role('button',name='继续生成大纲',exact=True).click()
    page.locator('.stage-nav').nth(2).get_by_text('已完成',exact=True).wait_for()
    assert page.locator('.outline-card').count()>0
    page.locator('.stage-nav').nth(3).click()
    expect(page.get_by_role('button',name='生成初稿',exact=True)).to_be_enabled()
    page.reload();page.locator('.stage-nav').nth(2).click()
    expect(page.locator('.outline-card').first).to_be_visible()
    assert not errors,errors
    report=dict(simulated=True,prerequisites=True,waive_undo=True,attach_and_verify=True,resume_outline=True,refresh=True,layouts=[1366,1280],console_errors=errors)
    Path('output/diagnostics/ui-v141.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report));browser.close()
