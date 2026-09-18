"""UI acceptance against the isolated qa_v14_app server (port 8894)."""
import io
import json
import os
import zipfile
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

BASE=os.environ.get('WEWRITE_QA_URL','http://127.0.0.1:8894')
OUT=Path('output/diagnostics')
OUT.mkdir(parents=True,exist_ok=True)
(OUT/'screenshots').mkdir(exist_ok=True)
H={'X-Studio-Request':'1'}

with sync_playwright() as p:
    browser=p.chromium.launch(channel='msedge',headless=True)
    page=browser.new_page(accept_downloads=True,viewport={'width':1366,'height':768})
    page.set_default_timeout(60000)
    errors=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    a=page.request.post(BASE+'/api/articles',headers=H,data={'topic':'界面验收：证据、素材与归档'}).json()
    aid=a['id']
    page.goto(BASE+'/#'+aid)
    page.get_by_role('heading',name='素材',exact=True).wait_for()

    def nav(index): page.locator('.stage-nav').nth(index).click()
    def complete(index):
        page.locator('.stage-nav').nth(index).get_by_text('已完成',exact=True).wait_for()
        page.get_by_role('button',name='停止',exact=True).wait_for(state='hidden')

    page.get_by_role('button',name='查找并整理资料',exact=True).click()
    complete(1)
    page.get_by_role('tab',name='资料整理结果',exact=True).click()
    page.get_by_role('heading',name='资料整理结果',exact=True).wait_for()
    assert not page.get_by_text('补充学术检索与文献导入',exact=True).count()
    for width,height in [(1366,768),(1280,800)]:
        page.set_viewport_size({'width':width,'height':height})
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        page.screenshot(path=str(OUT/f'screenshots/materials-{width}.png'))
    for index,label in [(2,'生成大纲'),(3,'生成初稿'),(4,'审核当前稿')]:
        nav(index);page.get_by_role('button',name=label,exact=True).click();complete(index)
    # Export immediately after editing, before the editor's debounce timer fires.
    nav(3)
    page.get_by_role('button',name='Markdown 源文',exact=True).click()
    marker='导出前刚刚补充的句子。'
    editor=page.get_by_role('textbox',name='Markdown 正文',exact=True)
    editor.fill(editor.input_value()+'\n\n'+marker)
    nav(6)
    with page.expect_download() as event:
        page.get_by_role('button',name='下载完整文章包',exact=True).click()
    download=event.value
    download_failure=download.failure()
    if not download_failure: download.save_as(str(OUT/'ui-browser-article.zip'))
    assert '_r' in download.suggested_filename
    page.get_by_role('button',name='打开归档文件夹',exact=True).wait_for()
    page.screenshot(path=str(OUT/'screenshots/archive.png'))
    a=page.request.get(BASE+'/api/articles/'+aid).json()
    assert marker in a['content']
    snapshot=page.request.post(BASE+'/api/articles/'+aid+'/exports',headers=H,data={'revision':a['revision']}).json()
    response=page.request.get(BASE+'/api/articles/'+aid+'/exports/'+snapshot['digest']+'/zip')
    assert response.status==200
    with zipfile.ZipFile(io.BytesIO(response.body())) as z:
        assert marker in z.read('文章.md').decode('utf-8')
        assert z.testzip() is None
    (OUT/'ui-article.zip').write_bytes(response.body())
    repeated=page.request.post(BASE+'/api/articles/'+aid+'/exports',headers=H,data={'revision':a['revision']}).json()
    assert repeated['path']==snapshot['path']
    page.reload();page.locator('.stage-nav').nth(6).wait_for();nav(6)
    page.get_by_role('button',name='下载完整文章包',exact=True).wait_for()
    nav(1)
    page.locator('.source-actions input[type=file]').set_input_files({'name':'fixture.bib','mimeType':'text/plain',
        'buffer':b'@article{demo,title={Fixture import},author={Smith, Alex},year={2025},journal={Fixture Journal}}'})
    page.get_by_role('tab',name='本篇素材').click()
    page.get_by_role('button',name='Fixture import',exact=True).wait_for()
    page.get_by_role('tab',name='资料整理结果',exact=True).click()
    page.get_by_text('材料或主题已改变，请重新整理。历史结果仍保留，但不会作为当前结论展示。',exact=True).wait_for()
    assert not errors,errors
    report=dict(simulated=True,manual_workflow=True,unsaved_edit_export=True,archive_reuse=True,archive_endpoint=True,
        reload=True,bibtex_import=True,stale_material_notice=True,download_filename=download.suggested_filename,
        browser_download_failure=download_failure,console_errors=errors)
    (OUT/'ui-v14.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    print(json.dumps(report,ensure_ascii=True))
    browser.close()
