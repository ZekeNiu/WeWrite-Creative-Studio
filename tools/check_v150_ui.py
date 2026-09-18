"""Browser acceptance against the offline QA app only."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright,expect
BASE='http://127.0.0.1:8875'
aid=json.loads(Path('output/test-workspaces/qa-v150/fixture.json').read_text())['article_id']
out=Path('output/diagnostics');out.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge',headless=True)
    page=browser.new_page(viewport={'width':1366,'height':768});page.set_default_timeout(15000)
    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    def article():return page.request.get(BASE+'/api/articles/'+aid).json()
    page.goto(BASE+'/#'+aid);page.get_by_text('先安排位置，再选择图片',exact=True).wait_for()
    before=article()['revision'];page.locator('.picture-plan summary').first.click();page.locator('.picture-plan summary').first.click()
    assert article()['revision']==before
    card=page.locator('.image-card').nth(1)
    card.locator('summary').filter(has_text='来源、使用依据与图片用途').click()
    field=card.get_by_role('textbox',name='使用依据');field.fill('界面验收：模拟明确许可');field.press('Tab')
    expect(card.get_by_role('switch',name='用于排版')).to_be_visible()
    card.get_by_role('switch',name='用于排版').click();expect(card.get_by_role('switch',name='用于排版')).to_have_attribute('aria-checked','true')
    page.reload();page.get_by_text('先安排位置，再选择图片',exact=True).wait_for()
    expect(page.locator('.image-card').nth(1).get_by_role('switch',name='用于排版')).to_have_attribute('aria-checked','true')
    cover=page.locator('.image-card').first;cover.get_by_text('调整封面裁切 · 2.35:1').click()
    cover.get_by_label('纵向位置').focus();cover.get_by_label('纵向位置').press('ArrowRight')
    page.wait_for_function("document.querySelector('input[aria-label=\"纵向位置\"]').value!=='50'")
    for width,height in ((1366,768),(1280,800)):
        page.set_viewport_size(dict(width=width,height=height));page.locator('.visual-slot').first.scroll_into_view_if_needed()
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        page.screenshot(path=str(out/f'v150-ui-{width}.png'))
    a=article();response=page.request.post(BASE+'/api/articles/'+aid+'/exports',headers={'X-Studio-Request':'1'},data={'revision':a['revision']})
    assert response.status==200,response.text()
    assert not errors,errors
    (out/'v150-ui.json').write_text(json.dumps(dict(simulated=True,passed=True,viewports=['1366x768','1280x800'],checks=['browse_without_mutation','rights_confirmation','adoption','refresh','cover_crop','no_overflow','export'],errors=errors),indent=2),'utf-8')
    browser.close();print('Visual UI acceptance passed at both sizes')
