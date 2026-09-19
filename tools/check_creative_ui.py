"""Exercise the new material journey in a browser using qa_creative_app only."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1];BASE='http://127.0.0.1:8898'
ID=json.loads((ROOT/'output/test-workspaces/qa-creative/fixture.json').read_text())['id']
OUT=ROOT/'output/playwright/creative';OUT.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge',headless=True)
    context=browser.new_context(viewport={'width':1440,'height':1000})
    context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(BASE) else r.abort())
    page=context.new_page();page.set_default_timeout(20000);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    def article():return page.request.get(BASE+'/api/articles/'+ID).json()
    def jobs():return page.request.get(BASE+'/api/articles/'+ID+'/jobs').json()
    def nav(label):page.locator('.stage-nav').filter(has=page.locator('strong',has_text=label)).click()
    created=page.request.post(BASE+'/api/articles',headers={'X-Studio-Request':'1'},data={'topic':'模拟完整创作流程','audience':'专业解读'});assert created.ok,created.text()
    ID=created.json()['id']
    page.goto(BASE+'/#'+ID)
    page.get_by_role('button',name='查找并整理资料',exact=True).click()
    expect(page.locator('.material-status')).to_contain_text('核心问题')
    expect(page.get_by_role('button',name='处理剩余问题',exact=True)).to_be_enabled()
    first=article();qid=first['materials_state']['required'][0]['id']
    page.locator('[data-issue="'+qid+'"]').get_by_role('button',name='展开问题').click()
    page.locator('[data-issue="'+qid+'"]').get_by_role('button',name='补充资料').click()
    page.get_by_role('dialog').get_by_role('button',name='关闭',exact=True).click()
    page.locator('.source-actions').get_by_role('button',name='粘贴文字').click()
    page.get_by_label('素材正文',exact=True).fill('与问题无关的个人笔记。')
    page.get_by_role('button',name='添加素材',exact=True).click()
    expect(page.get_by_role('dialog')).to_have_count(0)
    assert article()['sources'][-1]['issue_ids']==[]
    page.locator('[data-issue="'+qid+'"]').get_by_role('button',name='补充资料').click()
    page.get_by_role('dialog').get_by_role('button',name='粘贴文字').click()
    page.get_by_label('素材名称',exact=True).fill('模拟补充原文')
    page.get_by_label('素材正文',exact=True).fill('补充原文：研究只适用于给定条件。')
    page.get_by_role('button',name='添加素材',exact=True).click()
    expect(page.get_by_role('dialog')).to_have_count(0)
    assert article()['sources'][-1]['issue_ids']==[qid]
    expect(page.locator('[data-issue="'+qid+'"]').get_by_role('button',name='收起问题')).to_be_visible()
    expect(page.get_by_role('button',name='核实新增资料',exact=True)).to_be_enabled()
    before=jobs();page.get_by_role('button',name='核实新增资料',exact=True).click()
    expect(page.get_by_role('button',name='进入大纲',exact=True)).to_be_enabled()
    assert article()['research']['stats']['search_requests']==0
    assert article()['materials_state']['required']==[] and article()['materials_state']['boundaries']
    assert len(jobs())==len(before)+1
    # Expression edits leave facts and readiness intact.
    page.locator('.context-sidebar').get_by_role('tab',name='写作设置').click()
    page.get_by_label('目标篇幅 / 字',exact=True).fill('2600')
    before=len(jobs());page.get_by_role('button',name='进入大纲',exact=True).click()
    expect(page.locator('.workspace-title h1')).to_have_text('大纲')
    assert article()['brief']['words']==2600 and article()['materials_state']['ready'] and len(jobs())==before
    page.get_by_role('button',name='生成文章大纲',exact=True).click()
    expect(page.locator('.outline-card')).to_have_count(1)
    nav('写作');page.locator('.workspace-title-actions .primary').click()
    expect(page.locator('.prose-editor')).to_contain_text('模拟验收样稿')
    nav('审核修改');page.locator('.workspace-title-actions .primary').click()
    expect(page.locator('.review-summary')).to_contain_text('AI 审核通过')
    nav('素材');expect(page.get_by_role('button',name='进入大纲',exact=True)).to_be_enabled()
    page.screenshot(path=str(OUT/'ready-1440.png'),full_page=True)
    for width in (1100,390):
        page.set_viewport_size({'width':width,'height':900})
        expect(page.get_by_role('button',name='进入大纲',exact=True)).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(OUT/('ready-'+str(width)+'.png')),full_page=True)
    assert not errors,errors
    browser.close()
    print('PASS search → cancel supplement → explicit attachment → incremental verification → outline navigation → write → review; no navigation generation')
