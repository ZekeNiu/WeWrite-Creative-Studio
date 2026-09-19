"""Browser regression with only local synthetic fixtures (start qa_optimizations_app first)."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

BASE='http://127.0.0.1:8897'
ids=json.loads(Path('output/test-workspaces/qa-optimizations/fixtures.json').read_text())
out=Path('output/playwright');out.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge',headless=True)
    context=browser.new_context(viewport={'width':1440,'height':1000},permissions=['clipboard-read','clipboard-write'])
    context.route('**/*',lambda r:r.continue_() if r.request.url.startswith(BASE) else r.abort())
    page=context.new_page();page.set_default_timeout(15000);errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    def open_case(case):
        page.goto(BASE+'/#'+ids[case]);page.locator('.review-panel').wait_for()
    def article(case):return page.request.get(BASE+'/api/articles/'+ids[case]).json()
    def navigate(label):page.locator('.stage-nav').filter(has=page.locator('strong',has_text=label)).click()

    open_case('review')
    page.get_by_text('查看辅助评分与机械检查',exact=True).click()
    expect(page.locator('.review-checks')).to_contain_text('句长变化')
    expect(page.locator('.review-checks')).to_contain_text('表达自然度')
    assert page.locator('.review-checks pre').count()==0
    page.locator('.context-sidebar').evaluate('(el)=>el.scrollTop=el.scrollHeight')
    page.screenshot(path=str(out/'review-checks.png'),full_page=True)
    page.get_by_role('button',name='接受修改',exact=True).first.click()
    expect(page.get_by_text('已应用修改',exact=True)).to_be_visible()
    page.get_by_role('button',name='保留原文',exact=True).click()
    expect(page.locator('.review-summary strong')).to_have_text('本轮意见已处理')
    expect(page.get_by_text('需要你确认当前结果',exact=True)).to_have_count(0)
    page.reload();expect(page.locator('.review-summary strong')).to_have_text('本轮意见已处理')
    expect(page.locator('.prose-editor')).to_contain_text('修改甲。')
    page.screenshot(path=str(out/'review-completed.png'),full_page=True)
    page.get_by_role('button',name='调用记录',exact=True).click()
    expect(page.locator('.usage-table')).to_contain_text('状态')
    expect(page.locator('.usage-table')).not_to_contain_text('预估金额')
    page.get_by_role('button',name='关闭',exact=True).click()
    navigate('配图')
    expect(page.get_by_label('图片数量',exact=True)).to_be_visible()
    assert page.get_by_text('本篇图片预算 / 元',exact=True).count()==0
    page.get_by_role('button',name='生成这一张',exact=True).click()
    page.wait_for_function("document.querySelectorAll('.image-library img, .image-card img, .generated-images img').length>0")
    assert len(article('review')['images'])==1
    navigate('排版导出')
    page.locator('.reading-advice summary').click()
    page.get_by_role('button',name='获取阅读与结构建议',exact=True).click()
    expect(page.get_by_text('正在生成阅读与结构建议',exact=True)).to_be_visible()
    expect(page.locator('.layout-advice')).to_contain_text('建议保留小标题')
    preview=page.frame_locator('iframe[title="公众号排版预览"]')
    expect(preview.locator('body')).not_to_contain_text('本文使用 AI 辅助创作或编辑')
    expect(preview.locator('body')).not_to_contain_text('部分配图由 AI 生成')
    page.get_by_role('button',name='复制公众号排版',exact=True).click()
    expect(page.get_by_role('button',name='已复制',exact=True)).to_be_visible()
    copied=page.evaluate('navigator.clipboard.readText()')
    assert '本文使用 AI 辅助创作或编辑' not in copied and '部分配图由 AI 生成' not in copied
    page.screenshot(path=str(out/'layout-advice.png'),full_page=True)

    open_case('editor')
    page.get_by_role('button',name='插入引用',exact=True).click()
    page.get_by_role('button',name='查看证据与信息',exact=True).click()
    expect(page.get_by_label('文献类型',exact=True)).to_have_value('M')
    expect(page.get_by_label('出版社',exact=True)).to_have_value('科学出版社')
    expect(page.get_by_text('采用理由：本章对应实验',exact=True)).to_be_visible()
    page.get_by_role('button',name='关闭',exact=True).last.click()
    page.get_by_role('button',name='关闭',exact=True).click()
    page.get_by_role('button',name='Markdown 源文',exact=True).click()
    page.get_by_role('textbox',name='Markdown 正文',exact=True).fill('原文甲。\n\n原文乙。\n\n独立段落已人工修改。')
    page.get_by_role('button',name='接受修改',exact=True).first.click()
    expect(page.get_by_text('已应用修改',exact=True)).to_be_visible()
    content=article('editor')['content']
    assert '独立段落已人工修改。' in content and '修改甲。' in content
    page.get_by_role('button',name='保留原文',exact=True).click()
    expect(page.locator('.review-summary strong')).to_have_text('本轮意见已处理')
    page.get_by_role('textbox',name='Markdown 正文',exact=True).fill(content+'\n\n完成之后再编辑。')
    expect(page.locator('.review-summary strong')).to_have_text('正文已更新，需要复审')
    open_case('empty');page.get_by_text('查看辅助评分与机械检查',exact=True).click()
    expect(page.get_by_text('暂无编辑维度评分。',exact=True)).to_be_visible()
    expect(page.get_by_text('暂无机械检查结果。',exact=True)).to_be_visible()
    page.set_viewport_size({'width':1100,'height':800})
    assert page.evaluate('document.documentElement.scrollWidth<=window.innerWidth')
    page.locator('.context-sidebar').evaluate('(el)=>el.scrollTop=el.scrollHeight')
    page.screenshot(path=str(out/'review-empty-narrow.png'),full_page=True)
    assert not errors,errors
    browser.close()
print('Browser acceptance passed: review decisions, save/refresh, checks, image without price, layout progress and clipboard.')
