"""Browser acceptance for source tasks, direct bounds and the recycle bin (offline only)."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1];BASE='http://127.0.0.1:8899';H={'X-Studio-Request':'1'}
ID=json.loads((ROOT/'output/test-workspaces/qa-sidebar/import-fixture.json').read_text('utf-8'))['id']
OUT=ROOT/'output/playwright/import-advice';OUT.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge',headless=True)
    context=browser.new_context(viewport={'width':1440,'height':1000})
    context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(BASE) else r.abort())
    page=context.new_page();page.set_default_timeout(15000);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    def article():return page.request.get(BASE+'/api/articles/'+ID).json()
    def jobs():return page.request.get(BASE+'/api/articles/'+ID+'/jobs').json()
    page.goto(BASE+'/#'+ID)
    expect(page.locator('.material-status')).to_contain_text('高优先级')
    assert '本轮新增' not in page.locator('.material-status').inner_text()
    # Failed read stays visible inside the dialog; editing a URL recovers in place.
    page.get_by_role('button',name='添加链接',exact=True).click()
    page.get_by_label('网页链接',exact=True).fill('https://fixture.example.org/failure')
    page.get_by_role('button',name='添加素材',exact=True).click()
    dialog=page.get_by_role('dialog',name='导入资料')
    expect(dialog.get_by_role('alert')).to_contain_text('模拟：网页需要验证')
    page.screenshot(path=str(OUT/'failure-1440.png'))
    dialog.get_by_role('button',name='修改链接',exact=True).click()
    page.get_by_label('网页链接',exact=True).fill('https://fixture.example.org/slow')
    before=len(article()['sources']);page.get_by_role('button',name='添加素材',exact=True).click()
    expect(dialog.get_by_role('button',name='取消导入')).to_be_visible()
    dialog.get_by_role('button',name='取消导入').click()
    expect(page.get_by_role('dialog')).to_have_count(0)
    assert len(article()['sources'])==before
    # A supplement belongs to exactly this request and makes the next action explicit.
    page.get_by_role('tab',name='整理结果',exact=True).click()
    row=page.locator('[data-issue="issue1"]');row.get_by_role('button',name='展开问题').click()
    row.get_by_role('button',name='补充资料').click()
    page.get_by_role('dialog').get_by_role('button',name='添加链接').click()
    page.get_by_label('网页链接',exact=True).fill('https://fixture.example.org/success')
    page.get_by_role('button',name='添加素材',exact=True).click()
    expect(page.locator('.source-receipt')).to_contain_text('模拟公开论文')
    expect(page.get_by_role('button',name='核实这批资料',exact=True)).to_be_enabled()
    assert article()['sources'][-1]['issue_ids']==['issue1']
    # Direct AI bound changes the existing paragraph and remains reversible.
    row.get_by_role('button',name='采用限定表述').click()
    expect(page.get_by_role('button',name='已处理 · 1',exact=True)).to_be_visible()
    page.get_by_role('button',name='已处理 · 1',exact=True).click()
    expect(row).to_contain_text('查看限定改动')
    assert '这是限定条件下的观察结果' in article()['content']
    row.get_by_role('button',name='撤销处理决定').click()
    expect(page.get_by_role('button',name='已处理 · 0',exact=True)).to_be_visible()
    assert '待改写的段落。' in article()['content']
    # Task-only settings do not change global defaults or run anything on save.
    before=len(jobs());settings=page.request.get(BASE+'/api/settings').json()['search']
    page.get_by_role('button',name='检索设置',exact=True).click()
    page.get_by_label('最多搜索次数',exact=True).fill('40')
    page.get_by_role('button',name='保存本轮上限',exact=True).click()
    expect(page.get_by_role('dialog')).to_have_count(0)
    assert len(jobs())==before and page.request.get(BASE+'/api/settings').json()['search']==settings
    for width in (1440,1100,390):
        page.set_viewport_size({'width':width,'height':1000})
        page.get_by_role('button',name='待处理 · 13',exact=True).click()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(OUT/f'materials-{width}.png'),full_page=True)
    # No task is started merely by proceeding to outline.
    before=len(jobs());page.get_by_role('button',name='进入大纲',exact=True).click()
    expect(page.locator('.workspace-title h1')).to_have_text('大纲');assert len(jobs())==before
    page.set_viewport_size({'width':1440,'height':1000});page.get_by_role('button',name='返回文章库',exact=True).click()
    page.get_by_role('button',name='删除文章：导入与建议离线验收',exact=True).click()
    expect(page.get_by_role('button',name='打开文章：导入与建议离线验收',exact=True)).to_have_count(0)
    page.get_by_role('button',name='回收站',exact=True).click()
    card=page.locator('.library-card').filter(has_text='导入与建议离线验收')
    card.get_by_role('button',name='恢复',exact=True).click()
    expect(card).to_have_count(0)
    page.get_by_role('button',name='返回文章库',exact=True).click()
    expect(page.get_by_role('button',name='打开文章：导入与建议离线验收',exact=True)).to_be_visible()
    # Delete only a disposable isolated article.
    expendable=page.request.post(BASE+'/api/articles',headers=H,data={'topic':'回收站永久删除验收'}).json()
    page.reload();page.get_by_role('button',name='删除文章：回收站永久删除验收',exact=True).click()
    page.get_by_role('button',name='回收站',exact=True).click()
    page.locator('.library-card').filter(has_text='回收站永久删除验收').get_by_role('button',name='彻底删除').click()
    page.get_by_role('dialog').get_by_role('button',name='确认彻底删除').click()
    expect(page.get_by_role('dialog')).to_have_count(0)
    assert page.request.get(BASE+'/api/articles/'+expendable['id']).status==404
    assert not errors,errors
    browser.close()
    print('PASS import failure/cancel/supplement, direct bound/undo, limits, responsive layout, navigation, trash/restore/purge')
