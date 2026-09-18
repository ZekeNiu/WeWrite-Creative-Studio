import html
import io
import re
import zipfile
import json
from pathlib import Path
import bleach
from bleach.css_sanitizer import CSSSanitizer
from bs4 import BeautifulSoup
from . import store, bibliography

THEMES=store.ROOT/'vendor/wewrite/src/wewrite/toolkit/themes'
THEME_LABELS={'bauhaus':'包豪斯','bold-green':'墨绿商务','bold-navy':'深蓝商务','bytedance':'清新科技',
 'elegant-rose':'玫瑰雅致','focus-red':'焦点红','github':'开发者笔记','impeccable':'极简质感','ink':'水墨留白',
 'lobster-notes':'手账随笔','midnight':'深夜阅读','minimal-gold':'黑金简约','minimal':'纯净简约','newspaper':'报刊风',
 'professional-clean':'专业清爽','sspai':'少数派','tech-modern':'现代科技','warm-editorial':'温暖叙事'}
CSS=CSSSanitizer(allowed_css_properties=CSSSanitizer().allowed_css_properties|frozenset(['border-radius','padding','margin','display','max-width','min-width','width','height','line-height','letter-spacing','box-shadow','overflow','word-break','background','opacity','text-align','border-left','border-bottom','border-top','border-right','font-weight']))
TAGS=['section','article','div','span','p','br','h1','h2','h3','h4','h5','h6','strong','em','b','i','u','s','a','img','blockquote','ul','ol','li','pre','code','table','thead','tbody','tr','th','td','hr','sup','sub','figure','figcaption']


def safe_html(value):
    soup=BeautifulSoup(value,'html.parser')
    for node in soup(['script','style','iframe','object','form','input','button','svg']): node.decompose()
    return bleach.clean(str(soup),tags=TAGS,attributes={'*':['style','data-darkmode-color','data-darkmode-bgcolor'],'a':['href','title','rel'],'img':['src','alt','width','height'],'td':['colspan','rowspan'],'th':['colspan','rowspan']},protocols=['http','https'],css_sanitizer=CSS,strip=True)


def themes():
    import yaml
    result=[]
    for p in sorted(THEMES.glob('*.yaml')):
        d=yaml.safe_load(p.read_text(encoding='utf-8'))
        result.append({'id':p.stem,'name':THEME_LABELS.get(p.stem,d['name']),'description':d.get('description',''),'colors':d.get('colors',{})})
    return result


def markdown(a, export=False):
    content,refs,unknown=bibliography.citations(a['content'],a['sources'])
    for im in a['images']:
        if not im.get('selected',True): continue
        url=f'images/{im["filename"]}' if export else f'/api/articles/{a["id"]}/assets/{im["filename"]}'
        caption=im.get('caption','').replace(']','')
        block=f'\n\n![{caption}]({url})\n\n'
        if caption: block+='*'+caption.replace('*','\\*')+'*\n\n'
        heading=im.get('after_heading','')
        if im.get('role')=='cover': content=block+content
        elif heading:
            matches=list(re.finditer(r'^#{1,6}\s+(.+)$',content,re.M))
            target=next((i for i,m in enumerate(matches) if m.group(1).strip()==heading.strip()),None)
            if target is not None:
                pos=matches[target+1].start() if target+1<len(matches) else len(content)
                content=content[:pos]+block+content[pos:]
            else: content+=block
        else: content+=block
    if a['layout']['author']: content+='\n\n'+a['layout']['author']
    provenance=[]
    if any(u.get('stage') in ('write','revise','review') and u.get('status')=='completed' for u in store.usage(a['id'])):
        provenance.append('本文使用 AI 辅助创作或编辑。')
    if any(im.get('prompt') and im.get('selected',True) for im in a['images']): provenance.append('部分配图由 AI 生成。')
    if provenance: content+='\n\n'+''.join(provenance)
    if unknown: content+='\n\n引用待关联：'+', '.join(unknown)
    if refs:
        content+='\n\n## 参考文献\n\n'
        for ref in refs: content+=f'[{ref["number"]}] '+html.escape(ref['text'])+'\n\n'
    return '# '+a['title']+'\n\n'+content


def render(a, export=False):
    from wewrite.toolkit.theme import load_theme
    from wewrite.toolkit.converter import WeChatConverter
    cfg=a['layout']
    if cfg['theme'] not in {t['id'] for t in themes()}: raise ValueError('排版主题不存在')
    theme=load_theme(cfg['theme'],str(THEMES))
    theme._raw_data['aigc_footer']=False
    theme.base_css+=f'\np {{font-size:{cfg["font_size"]}px;line-height:{cfg["line_height"]};margin-bottom:{cfg["paragraph_gap"]}px;}}'
    result=WeChatConverter(theme=theme).convert(markdown(a,export))
    body=safe_html(result.html)
    title=f'<h1 style="font-size:24px;line-height:1.6">{html.escape(a["title"])}</h1>' if export else ''
    document=f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(a["title"])}</title><body style="margin:0;padding:24px 20px;max-width:680px;margin-inline:auto;background:#fff;word-break:break-word">{title}{body}</body></html>'
    _,references,unknown=bibliography.citations(a['content'],a['sources'])
    return dict(html=document,body=body,markdown=markdown(a,export),plaintext=BeautifulSoup(body,'html.parser').get_text('\n'),references=references,unresolved_citations=unknown)


def export_zip(a):
    result=render(a,True); output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('文章.md',result['markdown']); z.writestr('排版.html',result['html'])
        z.writestr('来源清单.json',json.dumps(a['sources'],ensure_ascii=False,indent=2))
        z.writestr('使用说明.txt','打开排版.html 查看完整排版。复制正文到公众号编辑器后，请按图示位置上传 images 中的本地图片。\n审核状态：'+a['stages']['review']+'\nAI 审核只作辅助，请最终核对正文与引用。')
        for im in a['images']:
            if im.get('selected',True):
                p=store.article_dir(a['id'])/'assets'/im['filename']
                if p.is_file(): z.write(p,'images/'+im['filename'])
    return output.getvalue()
