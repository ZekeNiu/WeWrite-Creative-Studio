"""Browser acceptance for stage sidebars against the isolated qa_sidebar_app."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright,expect

BASE='http://127.0.0.1:8899'
ROOT=Path(__file__).resolve().parents[1]
ids=json.loads((ROOT/'output/test-workspaces/qa-sidebar/fixtures.json').read_text())
OUT=ROOT/'output/playwright/sidebar';OUT.mkdir(parents=True,exist_ok=True)
H={'X-Studio-Request':'1'}

with sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge',headless=True)
    context=browser.new_context(viewport={'width':1440,'height':1000},permissions=['clipboard-read','clipboard-write'])
    context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(BASE) else r.abort())
    page=context.new_page();page.set_default_timeout(12000)
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    def article(case='full'):return page.request.get(BASE+'/api/articles/'+ids[case]).json()
    def open_case(case):
        page.goto(BASE+'/#'+ids[case]);expect(page.locator('.workspace-title h1')).to_be_visible()
    def nav(label):
        page.locator('.stage-nav').filter(has=page.locator('strong',has_text=label)).click()
        expect(page.locator('.workspace-title h1')).to_have_text(label)
    def side():return page.locator('.context-sidebar')
    def tab(label):page.get_by_role('tab',name=label,exact=True).click()
    def patch(changes,stage='preferences',case='full'):
        a=article(case)
        r=page.request.patch(BASE+'/api/articles/'+ids[case],headers=H,data={'revision':a['revision'],'stage':stage,'changes':changes})
        assert r.ok,r.text()
    def screenshot(name):page.screenshot(path=str(OUT/(name+'.png')),full_page=True)

    open_case('full');before=article();jobs=page.request.get(BASE+'/api/articles/'+ids['full']+'/jobs').json()
    for label,expected in [('选题','选题方向'),('素材','素材参考'),('大纲','大纲参考'),('写作','AI 修改'),('审核修改','审核意见'),('配图','配图概况')]:
        nav(label);expect(side().get_by_role('tab',name=expected,exact=True)).to_have_attribute('aria-selected','true')
        expect(side().get_by_role('tab')).to_have_count(2)
    nav('排版导出');expect(side()).to_have_count(0);expect(page.get_by_role('button',name='展开侧栏',exact=True)).to_have_count(0)
    expect(page.get_by_label('排版主题',exact=True).locator('option')).to_have_count(25)
    assert article()['revision']==before['revision']
    assert page.request.get(BASE+'/api/articles/'+ids['full']+'/jobs').json()==jobs
    print('PASS seven stages, no navigation writes or jobs',flush=True)

    nav('素材');tab('写作设置');nav('大纲');nav('素材');expect(page.get_by_role('tab',name='写作设置',exact=True)).to_have_attribute('aria-selected','true')
    tab('素材参考');page.get_by_role('button',name='关闭侧栏',exact=True).click();nav('大纲');expect(side()).to_be_visible();nav('素材');expect(side()).to_have_count(0)
    page.get_by_role('button',name='展开侧栏',exact=True).click()
    page.get_by_role('tab',name='本篇素材 · 12',exact=True).click()
    first=page.locator('.compact-source').first
    first.locator('.source-title').click();expect(side()).to_contain_text('仅在测试条件下得到支持')
    side().get_by_text('关联来源 · 3',exact=True).click();expect(side()).to_contain_text('未采用');expect(side()).to_contain_text('来源已删除')
    tab('写作设置');first.locator('.source-title').click();first.locator('.source-title').click();expect(page.get_by_role('tab',name='写作设置',exact=True)).to_have_attribute('aria-selected','true')
    page.get_by_role('button',name='关闭侧栏',exact=True).click();first.locator('.source-title').click();first.locator('.source-title').click();expect(side()).to_have_count(0)
    first.get_by_role('button',name='查看依据',exact=True).click();expect(side()).to_be_visible();expect(page.get_by_role('tab',name='素材参考',exact=True)).to_have_attribute('aria-selected','true')
    side().get_by_role('button',name='返回素材概况',exact=True).click()
    side().get_by_role('button',name='需要处理 核实问题 12',exact=True).click()
    expect(page.locator('[data-issue="issue12"]')).to_be_visible();expect(page.locator('[data-issue="issue12"] button[aria-expanded]')).to_have_attribute('aria-expanded','true')
    expect(page.locator('.research-details')).to_contain_text('第 2 / 2 页')
    side().get_by_role('button',name='写作局限 需要保留的边界',exact=True).click();expect(page.locator('[data-issue="limit1"]')).to_be_visible()
    screenshot('sources-context')
    print('PASS remembered state, explicit/passive selection, cross-page issue focus',flush=True)

    nav('大纲');page.locator('[data-context-id="section1"] input').first.focus();expect(side()).to_contain_text('仅在测试条件下得到支持')
    side().get_by_text('关联来源 · 3',exact=True).click();side().get_by_role('button',name='模拟素材 1',exact=True).click();expect(page.get_by_role('dialog')).to_be_visible();page.get_by_role('button',name='关闭',exact=True).click()
    side().get_by_role('button',name='2. 章节 2',exact=True).click();expect(side()).to_contain_text('尚缺少支持的判断')
    assert page.locator('[data-context-id="section2"]').evaluate('(e)=>e===document.activeElement')
    # Reverse by dragging actual cards: selection follows the stable ID, not its index.
    card=page.locator('[data-context-id="section2"]');target=page.locator('[data-context-id="section1"]')
    card.locator('.drag-handle').drag_to(target)
    expect(page.locator('.outline-card').first).to_have_attribute('data-context-id','section2')
    expect(side()).to_contain_text('尚缺少支持的判断')
    card.get_by_role('button',name='删除本节',exact=True).click();expect(side()).not_to_contain_text('当前章节依据')
    screenshot('outline-context')
    nav('配图');expect(side()).to_contain_text('对应章节已不存在');side().get_by_role('button',name='章节之后：已删除章节 模拟插图 对应章节已不存在，请在主区调整位置。',exact=True).click()
    assert page.locator('[data-context-id="image1"]').evaluate('(e)=>e===document.activeElement')
    screenshot('visual-context')
    print('PASS outline relations, reorder/delete, image location navigation',flush=True)

    nav('选题');domain=side().get_by_label('这次想探索的领域',exact=True);domain.fill('保留快速编辑的领域')
    tab('写作设置');expect(side().get_by_label('这次想探索的领域',exact=True)).to_have_value('保留快速编辑的领域')
    words=side().get_by_label('目标篇幅 / 字',exact=True);words.fill('2100');side().get_by_label('这次想探索的领域',exact=True).fill('第二个领域');nav('素材')
    saved=article();assert saved['brief']['words']==2100 and saved['brief']['domain']=='第二个领域'
    nav('选题');expect(side().get_by_label('指定主题（可选）',exact=True)).to_have_count(0)
    url=BASE+'/api/articles/'+ids['full']
    def fail_save(route):
        if route.request.method=='PATCH':route.fulfill(status=409,content_type='application/json',body='{"detail":"模拟保存失败"}')
        else:route.continue_()
    page.route(url,fail_save)
    domain=side().get_by_label('这次想探索的领域',exact=True);domain.fill('失败时保留的输入');nav_button=page.locator('.stage-nav').filter(has=page.locator('strong',has_text='大纲'));nav_button.click()
    expect(page.locator('.workspace-title h1')).to_have_text('选题');expect(domain).to_have_value('失败时保留的输入');expect(domain).to_have_attribute('aria-invalid','true')
    page.get_by_role('button',name='关闭侧栏',exact=True).click();expect(side()).to_be_visible()
    tab('选题方向');expect(page.get_by_role('tab',name='写作设置',exact=True)).to_have_attribute('aria-selected','true')
    # Failed select edits must retain the selected value as well.
    side().get_by_label('目标读者',exact=True).select_option('专业解读');expect(side().get_by_label('目标读者',exact=True)).to_have_attribute('aria-invalid','true')
    expect(side().get_by_label('目标读者',exact=True)).to_have_value('专业解读')
    screenshot('save-failure-retains-input')
    page.unroute(url,fail_save);nav('大纲');assert article()['brief']['domain']=='失败时保留的输入';assert article()['brief']['audience']=='专业解读'
    print('PASS field/select saves, merge, failure retains input and current view',flush=True)

    # Article identity and stale records.
    open_case('other');expect(side()).not_to_contain_text('当前章节依据');expect(side()).to_contain_text('本篇素材')
    patch({'sources':[{'id':'S1','selected':False}]},'sources',case='other');page.reload();expect(side()).to_contain_text('历史依据')
    page.get_by_role('tab',name='本篇素材 · 1',exact=True).click();page.locator('.compact-source .source-title').first.click();expect(side()).to_contain_text('未采用')
    page.locator('.compact-source').first.get_by_role('button',name='移除素材',exact=True).click();expect(side()).to_contain_text('本篇素材');expect(side()).not_to_contain_text('返回素材概况')
    open_case('empty');nav('素材');expect(side()).to_contain_text('尚未进行资料核实');nav('大纲');expect(side()).to_contain_text('生成或添加章节后');nav('配图');expect(side()).to_contain_text('没有配图也可继续')
    print('PASS empty, stale, deleted object and article isolation',flush=True)

    open_case('review');expect(side()).to_contain_text('模拟审核意见');side().get_by_role('button',name='定位原文',exact=True).first.click()
    side().get_by_role('button',name='接受修改',exact=True).first.click();expect(page.locator('.prose-editor')).to_contain_text('修改后的段落。')
    side().get_by_role('button',name='保留原文',exact=True).click();expect(side()).to_contain_text('本轮意见已处理')
    nav('写作');editor=page.locator('.prose-editor');editor.click();page.keyboard.press('Control+End');page.keyboard.type('未保存编辑回归。');nav('排版导出');expect(page.get_by_role('button',name='复制公众号排版',exact=True)).to_be_enabled()
    assert '未保存编辑回归。' in article('review')['content']
    page.get_by_role('button',name='复制公众号排版',exact=True).click();expect(page.get_by_role('button',name='已复制',exact=True)).to_be_visible()
    with page.expect_download() as download:page.get_by_role('button',name='下载完整文章包',exact=True).click()
    assert download.value.suggested_filename.endswith('.zip')
    screenshot('layout-preserved')
    print('PASS review decisions, editor flush, original layout copy and export',flush=True)

    open_case('flows');nav('写作')
    side().get_by_label('已选中的内容',exact=True).fill('待改写的段落。')
    side().get_by_label('这次如何修改',exact=True).fill('保留适用边界')
    side().get_by_role('button',name='生成修改建议',exact=True).click()
    expect(side().locator('.suggestion')).to_be_visible()
    expect(side().locator('.suggestion')).to_contain_text('研究只适用于给定条件。')
    side().get_by_role('button',name='应用',exact=True).click()
    expect(page.locator('.prose-editor')).not_to_contain_text('待改写的段落。')
    nav('配图');page.get_by_role('button',name='生成这一张',exact=True).click()
    expect(page.locator('.image-card')).to_have_count(2)
    expect(side()).to_contain_text('2 张用于排版')
    # Existing plan-upload and image adoption operations remain in the main area.
    page.locator('.stage-body input[type=file]').set_input_files(str(ROOT/'output/test-workspaces/qa-sidebar/articles'/ids['flows']/'assets/sample.png'))
    expect(page.locator('.image-card')).to_have_count(3)
    page.locator('.image-card').last.get_by_role('switch',name='用于排版',exact=True).click()
    expect(side()).to_contain_text('2 张用于排版')
    print('PASS simulated selection revision, background image completion, upload/adoption',flush=True)

    open_case('long');nav('大纲');page.locator('[data-context-id="section1"] input').first.focus()
    expect(side().locator('.context-long')).not_to_have_attribute('open','')
    side().locator('.context-long summary').click();expect(side().locator('.context-long p')).to_be_visible()
    screenshot('long-evidence-expanded')
    # Browsing still works if browser session storage is unavailable.
    isolated=browser.new_context(viewport={'width':1440,'height':900})
    isolated.add_init_script("Storage.prototype.setItem=()=>{throw new Error('disabled')}")
    q=isolated.new_page();q.goto(BASE+'/#'+ids['empty']);expect(q.locator('.context-sidebar')).to_be_visible()
    q.get_by_role('button',name='关闭侧栏',exact=True).click();expect(q.locator('.context-sidebar')).to_have_count(0)
    q.get_by_role('button',name='展开侧栏',exact=True).click();q.get_by_role('tab',name='写作设置',exact=True).click();expect(q.get_by_role('tab',name='写作设置',exact=True)).to_have_attribute('aria-selected','true');isolated.close()
    print('PASS long evidence disclosure and unavailable storage fallback',flush=True)

    for width in (1100,390):
        mobile=browser.new_context(viewport={'width':width,'height':900});q=mobile.new_page();q.goto(BASE+'/#'+ids['full'])
        expect(q.locator('.workspace-title h1')).to_be_visible()
        q.locator('.stage-nav').filter(has=q.locator('strong',has_text='素材')).click()
        expect(q.locator('.workspace-title h1')).to_have_text('素材');expect(q.locator('.context-sidebar')).to_have_count(0)
        opener=q.get_by_role('button',name='展开侧栏',exact=True);opener.click();expect(q.get_by_role('dialog',name='素材参考',exact=True)).to_be_visible()
        assert q.locator('.context-sidebar').evaluate('(e)=>e.contains(document.activeElement)')
        q.keyboard.press('Escape');expect(q.locator('.context-sidebar')).to_have_count(0);expect(opener).to_be_focused()
        opener.click();q.locator('.context-backdrop').click(position={'x':10,'y':100});expect(q.locator('.context-sidebar')).to_have_count(0)
        opener.click();q.get_by_role('tab',name='写作设置',exact=True).click();q.get_by_label('这次想探索的领域',exact=True).fill('抽屉编辑 '+str(width));q.keyboard.press('Escape');expect(q.locator('.context-sidebar')).to_have_count(0)
        opener.click();expect(q.get_by_label('这次想探索的领域',exact=True)).to_have_value('抽屉编辑 '+str(width));q.screenshot(path=str(OUT/('drawer-'+str(width)+'.png')),full_page=True)
        assert q.evaluate('document.documentElement.scrollWidth<=innerWidth'),width
        q.keyboard.press('Escape');q.locator('.stage-nav').filter(has=q.locator('strong',has_text='排版导出')).click();expect(q.locator('.context-sidebar')).to_have_count(0)
        assert q.evaluate('document.documentElement.scrollWidth<=innerWidth'),('layout',width)
        mobile.close()
    assert not errors,errors
    browser.close()
    print('PASS responsive drawer, Escape/backdrop/focus, saved edits, no page errors',flush=True)
