import copy
import io
import json
import zipfile
from pathlib import Path
import pytest
from bs4 import BeautifulSoup
from backend import rendering,editorial_themes,prompts,source_context,store,workflow,materials
from .test_studio import client,new,patch,run,model,H


def sample(client):
    a=new(client)
    source=materials.source('阅读设计','原文证据。')
    source['bibliography']=dict(title='阅读设计',document_type='M',authors=['测试作者'],year='2025',publisher='测试出版社',publication_place='北京')
    a['sources']=[source]
    a['content']=editorial_themes.SAMPLE
    a['content']+='\n\n## 03 已有编号\n\n## **重要**的标题\n\n# 保留正文一级标题\n\n证据 ['+source['id']+']。\n\n```python\nprint("内容保留")\n```\n\n[长链接](https://example.org/'+('path'*60)+')'
    a['layout']['author']='测试署名'
    a['images']=[dict(id='im',filename='sample.png',caption='图注原文',role='article',after_heading='让观点有清晰的层次',selected=True)]
    return a


def test_catalog_and_read_only_previews(client,monkeypatch):
    monkeypatch.setattr(source_context,'sources',lambda *a,**k:pytest.fail('No evidence context required'))
    meta=client.get('/api/meta').json();themes=meta['themes']
    assert len([t for t in themes if t['group']=='editorial'])==7
    assert len([t for t in themes if t['id'] in editorial_themes.CRAFTED])==3
    assert len([t for t in themes if t['group']=='classic'])==18
    before=client.get('/api/articles').json()
    for theme in themes[:7]:
        response=client.get('/api/themes/'+theme['id']+'/preview')
        assert response.status_code==200 and '让观点有清晰的层次' in response.json()['html']
        assert 'defaults' in theme
    assert client.get('/api/articles').json()==before
    assert client.get('/api/themes/unknown/preview').status_code==404


@pytest.mark.parametrize('theme',editorial_themes.PRESETS)
def test_complete_render_preserves_content_and_roles(client,theme):
    a=sample(client);a['layout'].update(theme=theme);original=copy.deepcopy(a)
    result=rendering.render(a);soup=BeautifulSoup(result['body'],'html.parser')
    assert a==original
    assert 'studio-role:' not in result['markdown'] and 'studio-role:' not in result['body']
    assert '保留正文一级标题' in soup.get_text()
    assert len(soup.find_all('img'))==1
    assert '图注原文' in soup.get_text() and '测试署名' in soup.get_text()
    caption=next(n for n in soup.find_all('p') if n.get_text()=='图注原文')
    assert 'font-size:12px' in caption['style']
    refs=next(n for n in soup.find_all('h2') if n.get_text()=='参考文献')
    assert refs.find('span',attrs={'leaf':''}) and 'font-size:15px' in refs['style']
    numbered=next(n for n in soup.find_all('h2') if '03 已有编号' in n.get_text())
    assert not [span for span in numbered.find_all('span') if span.get_text().strip().isdigit()]
    assert '补充信息保留自己的层级' in soup.get_text()
    assert 'table-layout:fixed' in soup.table['style']
    assert '本文使用 AI' not in result['body'] and '部分配图由 AI' not in result['body']
    exported=rendering.render(a,True)
    assert exported['body'].replace('images/sample.png',f'/api/articles/{a["id"]}/assets/sample.png')==result['body']
    assert '<h1' in exported['html']
    archive=zipfile.ZipFile(io.BytesIO(rendering.export_zip(a)))
    assert archive.read('文章.md').decode()==exported['markdown']
    assert archive.read('排版.html').decode()==exported['html']


@pytest.mark.parametrize('theme',editorial_themes.PRESETS)
def test_manual_typography_applies_to_paragraphs_and_lists(client,theme):
    a=new(client);a['content']='正文。\n\n- 列表内容';a['layout'].update(theme=theme,font_size=19,line_height=2.1,paragraph_gap=25)
    soup=BeautifulSoup(rendering.render(a)['body'],'html.parser')
    assert 'font-size:19px' in soup.p['style'] and 'line-height:2.1' in soup.p['style'] and '25px' in soup.p['style']
    listing=next(n for n in soup.find_all('section') if 'display:table;' in n.get('style',''))
    assert 'font-size:19px' in listing['style']


def test_theme_switch_retains_review_history_and_conflict_protection(client):
    a=new(client);assert a['layout']['theme']=='editorial-science'
    a=patch(client,a,{'content':'正文。'},'write')
    a=workflow.apply_result(a,'review',dict(decision='pass',summary='通过',issues=[],dimensions={}),{})
    assert a['stages']['review']=='done'
    old=copy.deepcopy(a)
    a=patch(client,a,{'layout':dict(a['layout'],theme='professional-clean',font_size=20)},'layout')
    assert a['stages']['review']=='done' and a['content']==old['content']
    reopened=client.get('/api/articles/'+a['id']).json();assert reopened['layout']==a['layout']
    response=client.patch('/api/articles/'+a['id'],headers=H,json={'revision':old['revision'],'stage':'layout','changes':{'layout':old['layout']}})
    assert response.status_code==409
    latest=store.versions(a['id'])[0]
    restored=store.restore(a['id'],latest['id'],a['revision'])
    assert restored['layout']==old['layout']


def test_legacy_theme_keeps_renderer(client):
    from wewrite.toolkit.theme import load_theme
    from wewrite.toolkit.converter import WeChatConverter
    a=new(client);a['content']='## 小标题\n\n旧文章正文';a['layout'].update(theme='professional-clean',font_size=18)
    cfg=a['layout'];theme=load_theme(cfg['theme'],str(rendering.THEMES));theme._raw_data['aigc_footer']=False
    theme.base_css+=f'\np {{font-size:{cfg["font_size"]}px;line-height:{cfg["line_height"]};margin-bottom:{cfg["paragraph_gap"]}px;}}'
    from wewrite.toolkit.converter import make_paste_safe
    expected=rendering.safe_html(make_paste_safe(rendering.safe_html(WeChatConverter(theme=theme).convert(rendering.markdown(a)).html)))
    assert rendering.render(a)['body']==expected


def test_advice_uses_only_reading_context_and_does_not_apply_changes(client,model,monkeypatch):
    a=new(client);a=patch(client,a,{'content':'正文。'},'write')
    monkeypatch.setattr(source_context,'sources',lambda *a,**k:pytest.fail('Must not load unrelated source context'))
    value=json.loads(prompts.prompt('layout_advice',a,{}))
    assert set(value['资料与当前内容'])=={'title','article','images'}
    assert '不超过 5 条' in value['任务']
    result=run(client,a,'layout_advice',chain=False)
    assert result['status']=='completed'
    after=client.get('/api/articles/'+a['id']).json()
    assert after['content']==a['content'] and after['layout']==a['layout']
    assert len(client.get('/api/articles/'+a['id']+'/jobs').json())==1


def test_new_theme_blocks_unsafe_html(client):
    a=new(client);a['content']='安全正文<script>alert(1)</script><iframe src="https://bad.test"></iframe><img src="x" onerror="alert(1)">'
    result=rendering.render(a)['body']
    assert '<script' not in result and '<iframe' not in result and 'onerror' not in result


def test_plain_article_and_invalid_list_start_do_not_lose_content(client):
    a=new(client);a['content']='没有小标题的正文。\n\n<ol start="invalid"><li>保留项目</li></ol>'
    soup=BeautifulSoup(rendering.render(a)['body'],'html.parser')
    assert not soup.find('h2')
    assert '没有小标题的正文' in soup.get_text() and '保留项目' in soup.get_text()


def test_theme_export_creates_new_archive_and_preserves_old_snapshot(client):
    from backend import outputs
    a=new(client);a['content']='完整正文。'
    first=outputs.archive(a);folder=Path(first['path'])
    original=(folder/'排版.html').read_bytes()
    a['layout']['theme']='editorial-essay'
    second=outputs.archive(a)
    assert first['digest']!=second['digest'] and first['path']!=second['path']
    assert (folder/'排版.html').read_bytes()==original


@pytest.mark.parametrize('theme',editorial_themes.CRAFTED)
def test_crafted_decorations_survive_sanitizer_without_animation_or_raw_changes(client,theme):
    a=sample(client);a['layout']['theme']=theme
    result=rendering.render(a);soup=BeautifulSoup(result['body'],'html.parser')
    assert 'animation' not in result['body'] and '<svg' not in result['body'] and '<script' not in result['body']
    assert '┆' not in result['markdown'] and '◇' not in result['markdown']
    if theme=='editorial-fieldnotes':
        badge=next(n for n in soup.find_all('span') if n.get_text()=='01')
        assert 'border-top:1px solid' in badge['style'] and 'border-left:1px solid' in badge['style']
    if theme=='editorial-folio': assert 'border-left:1px solid' in soup.img['style']
