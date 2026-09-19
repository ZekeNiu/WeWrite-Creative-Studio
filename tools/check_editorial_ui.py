"""Run against tools.qa_editorial_app on 8898. No production writes or paid calls."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright,expect

ROOT=Path(__file__).resolve().parents[1]
BASE='http://127.0.0.1:8898'
ids=json.loads((ROOT/'output/test-workspaces/qa-editorial/fixtures.json').read_text())
OUT=ROOT/'output/playwright/editorial';OUT.mkdir(parents=True,exist_ok=True)
H={'X-Studio-Request':'1'}

with sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge',headless=True)
    context=browser.new_context(viewport={'width':1440,'height':1050},permissions=['clipboard-read','clipboard-write'])
    page=context.new_page();page.set_default_timeout(15000)
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    article_url=BASE+'/api/articles/'+ids['layout']
    initial=page.request.get(article_url).json()
    page.goto(BASE+'/#'+ids['layout'])
    copy_button=page.get_by_role('button',name='复制公众号排版',exact=True)
    expect(copy_button).to_be_enabled()
    expect(page.locator('.editorial-card')).to_have_count(0)
    expect(page.get_by_role('combobox',name='排版主题',exact=True).locator('option')).to_have_count(25)
    expect(page.locator('.reading-advice')).not_to_have_attribute('open','')
    expect(page.get_by_role('combobox',name='排版主题',exact=True)).to_have_value('editorial-science')
    page.screenshot(path=str(OUT/'original-layout-restored.png'),full_page=True)
    themes=[t for t in page.request.get(BASE+'/api/meta').json()['themes'] if t['group']=='editorial']
    for theme in themes:
        page.get_by_role('combobox',name='排版主题',exact=True).select_option(theme['id'])
        expect(copy_button).to_be_enabled()
        expect(page.get_by_role('combobox',name='排版主题',exact=True)).to_have_value(theme['id'])
        article=page.request.get(article_url).json()
        assert article['layout']['theme']==theme['id'] and article['content']==initial['content']
        assert article['layout']['author']=='测试署名' and article['stages']['review']=='done'
        preview=page.request.post(article_url+'/preview',headers=H).json()
        for width in (375,430):
            view=context.new_page();view.set_viewport_size({'width':width,'height':1000});view.goto(BASE)
            view.set_content(preview['html']);view.locator('img').wait_for()
            assert view.evaluate('document.documentElement.scrollWidth<=innerWidth'),theme['id']
            view.screenshot(path=str(OUT/(theme['id']+'-'+str(width)+'.png')),full_page=True)
            view.close()
    assert not page.request.get(article_url+'/jobs').json()
    # Rapid selections must save and render the last intent; copying stays disabled while pending.
    page.evaluate("""() => {for(const name of ['杂志长文','人文随笔','现代专题'])document.querySelector(`[aria-label="${name}"]`).click()}""")
    expect(copy_button).to_be_disabled();expect(copy_button).to_be_enabled()
    assert page.request.get(article_url).json()['layout']['theme']=='editorial-feature'
    page.get_by_role('spinbutton',name='正文字号',exact=True).fill('19')
    page.get_by_role('spinbutton',name='正文字号',exact=True).press('Tab')
    expect(copy_button).to_be_enabled()
    assert page.request.get(article_url).json()['layout']['font_size']==19
    page.get_by_role('button',name='恢复推荐设置',exact=True).click();expect(copy_button).to_be_enabled()
    assert page.request.get(article_url).json()['layout']['font_size']==16
    # A failed preview cannot leave an earlier result available for copying.
    page.route('**/api/articles/*/preview',lambda route:route.fulfill(status=503,json={'detail':'模拟预览暂时不可用'}))
    page.get_by_role('button',name='杂志长文').click()
    expect(page.get_by_role('button',name='重新加载预览',exact=True)).to_be_visible()
    expect(copy_button).to_be_disabled()
    page.unroute('**/api/articles/*/preview')
    page.get_by_role('button',name='重新加载预览',exact=True).click();expect(copy_button).to_be_enabled()
    page.get_by_role('button',name='现代专题').click();expect(copy_button).to_be_enabled()
    page.reload();expect(copy_button).to_be_enabled()
    expect(page.get_by_role('combobox',name='排版主题',exact=True)).to_have_value('editorial-feature')
    # Capture actual clipboard HTML and check the selected theme is the one copied.
    page.evaluate("""() => {window.copiedHTML='';navigator.clipboard.write=async items=>{window.copiedHTML=await (await items[0].getType('text/html')).text()}}""")
    copy_button.click();expect(page.get_by_role('button',name='已复制',exact=True)).to_be_visible()
    assert page.evaluate('window.copiedHTML')==page.request.post(article_url+'/preview',headers=H).json()['body']
    page.locator('.reading-advice summary').click()
    before=page.request.get(article_url).json()
    page.get_by_role('button',name='获取阅读与结构建议',exact=True).click()
    expect(page.locator('.layout-advice')).to_contain_text('可以保留现有分段')
    after=page.request.get(article_url).json()
    assert after['layout']==before['layout'] and after['content']==before['content']
    # A stale revision must retain the server result and expose a conflict, without silent overwrite.
    page.request.patch(article_url,headers=H,data={'revision':after['revision'],'stage':'layout','changes':{'layout':dict(after['layout'],author='并发编辑署名')}})
    page.get_by_role('button',name='人文随笔').click()
    expect(page.get_by_role('alert')).to_contain_text('文章已有更新')
    expect(page.get_by_role('button',name='复制公众号排版',exact=True)).to_be_disabled()
    assert page.request.get(article_url).json()['layout']['author']=='并发编辑署名'
    page.reload();expect(page.get_by_role('button',name='复制公众号排版',exact=True)).to_be_enabled()
    # Navigation to layout must flush unsaved editor content.
    page.goto(BASE+'/#'+ids['editor'])
    page.get_by_role('button',name='Markdown 源文',exact=True).click()
    page.get_by_role('textbox',name='Markdown 正文',exact=True).fill('排版前尚未自动保存的正文。')
    page.get_by_role('button',name='排版导出',exact=False).first.click()
    expect(page.get_by_role('button',name='复制公众号排版',exact=True)).to_be_enabled()
    assert page.request.get(BASE+'/api/articles/'+ids['editor']).json()['content']=='排版前尚未自动保存的正文。'
    page.set_viewport_size({'width':1100,'height':900})
    page.screenshot(path=str(OUT/'layout-1100.png'),full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.set_viewport_size({'width':760,'height':900})
    expect(page.locator('.local-badge')).to_be_visible()
    page.screenshot(path=str(OUT/'layout-760.png'),full_page=True)
    # Stress long titles, unbroken links and a wide table without paid generation.
    plain_url=BASE+'/api/articles/'+ids['plain'];plain=page.request.get(plain_url).json()
    wide='\n\n|'+ '|'.join(['很长的列标题']*8)+'|\n|'+ '|'.join(['---']*8)+'|\n|'+ '|'.join(['UnbrokenLongValue1234567890']*8)+'|'
    for theme in themes:
        plain=page.request.patch(plain_url,headers=H,data={'revision':plain['revision'],'stage':'layout','changes':{'title':'很长的文章标题用于验证换行与完整显示'*5,'layout':dict(plain['layout'],theme=theme['id'],**theme['defaults']),'content':'## '+('很长的章节标题'*10)+'\n\n'+initial['content']+wide}}).json()
        html=page.request.post(plain_url+'/preview',headers=H).json()['html']
        view=context.new_page();view.goto(BASE);view.set_viewport_size({'width':375,'height':1000});view.set_content(html)
        assert view.evaluate('document.documentElement.scrollWidth<=innerWidth'),theme['id']
        assert view.locator('td').last.inner_text()=='UnbrokenLongValue1234567890'
        view.close()
    assert not errors,errors
    browser.close()
print('Passed: seven themes at 375/430, original dropdown, selection/defaults/refresh, rapid switching, clipboard consistency, optional advice, conflicts, unsaved editor, narrow version badge.')
