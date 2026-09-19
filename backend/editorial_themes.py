"""Application-owned editorial presets; decorations never enter stored Markdown."""
import re
from bs4 import BeautifulSoup, Comment
from wewrite.toolkit.converter import WeChatConverter
from wewrite.toolkit.theme import Theme

SANS='-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", sans-serif'
SERIF='"Songti SC", "Noto Serif CJK SC", SimSun, serif'
PRESETS={
    'editorial-magazine':dict(name='杂志长文',description='细线与大留白，让长文有从容的章节节奏。',primary='#9b492f',text='#292b2c',muted='#777773',paper='#fffefa',tint='#f5efe7',font_size=16,line_height=1.9,paragraph_gap=20),
    'editorial-science':dict(name='专业科普',description='清晰层级与克制强调，让观点和依据都易于阅读。',primary='#24685d',text='#263b36',muted='#6b7f79',paper='#ffffff',tint='#eff6f3',font_size=16,line_height=1.8,paragraph_gap=18),
    'editorial-essay':dict(name='人文随笔',description='衬线标题、温暖纸色，让文字在留白中舒展。',primary='#79634e',text='#403a33',muted='#8b8073',paper='#fcfaf5',tint='#f2ede3',font_size=17,line_height=1.9,paragraph_gap=22),
    'editorial-feature':dict(name='现代专题',description='醒目的分节色块，建立明快的图文阅读节奏。',primary='#294bc0',text='#20283d',muted='#707b95',paper='#ffffff',tint='#f0f3fc',font_size=16,line_height=1.8,paragraph_gap=18),
}


def catalog():
    return [dict(id=id,name=p['name'],description=p['description'],group='editorial',
                 colors=dict(primary=p['primary']),defaults={k:p[k] for k in ('font_size','line_height','paragraph_gap')}) for id,p in PRESETS.items()]


def style(node,**values):
    current={}
    for pair in node.get('style','').split(';'):
        if ':' in pair:
            k,v=pair.split(':',1);current[k.strip()]=v.strip()
    current.update({k.replace('_','-'):str(v) for k,v in values.items()})
    node['style']=';'.join(f'{k}:{v}' for k,v in current.items())


class EditorialConverter(WeChatConverter):
    def __init__(self,id,cfg):
        self.id=id;self.p=PRESETS[id];self.cfg=cfg
        theme=Theme(name=id,description=self.p['description'],base_css='',colors={'primary':self.p['primary'],'text':self.p['text']})
        theme._raw_data={'aigc_footer':False}
        super().__init__(theme=theme)

    def _strip_h1(self,text):
        # Only the injected article title belongs to WeChat's separate title field.
        return text.split('\n',1)[1] if text.startswith('# ') else text

    def _process_images(self,value):
        soup=BeautifulSoup(value,'html.parser')
        return value,[im['src'] for im in soup.find_all('img',src=True)]

    def _convert_lists_to_sections(self,value):
        return value  # Keep nested structure until typography is applied below.

    def _apply_inline_styles(self,value):
        soup=BeautifulSoup(value,'html.parser');p=self.p;c=self.cfg
        primary=p['primary'];size=c['font_size'];line=c['line_height'];gap=c['paragraph_gap']
        roles={}
        for marker in list(soup.find_all(string=lambda x:isinstance(x,Comment))):
            if str(marker).startswith('studio-role:'):
                node=marker.find_next_sibling()
                if node: roles[id(node)]=str(marker).split(':',1)[1]
                marker.extract()
        for node in soup.find_all(['p','li']):
            style(node,font_size=f'{size}px',line_height=line,color=p['text'],margin=f'0 0 {gap}px',word_break='break-word')
        for node in soup.find_all(['strong','b']): style(node,font_weight=700,color=primary)
        for node in soup.find_all('em'): style(node,font_style='italic')
        for node in soup.find_all('blockquote'):
            style(node,margin='26px 0',padding='18px 20px',background=p['tint'],border_left=f'3px solid {primary}')
            for child in node.find_all('p'): style(child,margin='0 0 8px',font_size=f'{max(15,size-1)}px')
            if self.id=='editorial-essay': style(node,background='transparent',font_family=SERIF,border_left='none',border_top=f'1px solid {primary}',border_bottom=f'1px solid {primary}',padding='22px 10px')
            if self.id=='editorial-magazine': style(node,background='transparent',border_left=f'1px solid {primary}',padding='6px 0 6px 22px')
        for node in soup.find_all(['h1','h2','h3','h4','h5','h6']):
            level=int(node.name[1]);style(node,font_family=SERIF if self.id in ('editorial-essay','editorial-magazine') else SANS,
                font_size=f'{24 if level<=2 else 19 if level==3 else 17}px',font_weight=700,line_height=1.5,
                color=p['text'],margin='36px 0 18px' if level<=2 else '26px 0 12px',word_break='break-word')
        number=0
        for node in soup.find_all('h2'):
            label=node.get_text().strip()
            if roles.get(id(node))=='references' or label in ('参考文献','参考资料','参考链接'): continue
            if self.id=='editorial-magazine':
                style(node,border_top=f'1px solid {primary}',padding_top='18px',margin_top='42px',font_size='25px')
                number+=1
                if not re.match(r'^(?:第[一二三四五六七八九十百\d]+[章节部分]|[（(]?[一二三四五六七八九十百\d]+[）)、.．\s])',label):
                    badge=soup.new_tag('span');badge.string=f'{number:02d}'
                    style(badge,display='block',font_family=SANS,font_size='12px',letter_spacing='2px',color=primary,margin_bottom='10px')
                    node.insert(0,badge)
            elif self.id=='editorial-science': style(node,font_size='21px',border_left=f'4px solid {primary}',padding='0 0 0 13px')
            elif self.id=='editorial-essay': style(node,text_align='center',font_size='23px',margin='44px 0 24px',font_weight=600)
            else: style(node,font_size='21px',background=primary,color='#ffffff',padding='15px 18px',margin='34px 0 20px')
        for heading in soup.find_all(['h1','h2','h3','h4','h5','h6']):
            for strong in heading.find_all(['strong','b']): style(strong,color='inherit')
        for node in soup.find_all('img'):
            style(node,max_width='100%',height='auto',display='block',margin='28px auto 12px',border_radius='0' if self.id in ('editorial-magazine','editorial-essay') else '5px')
        for node in soup.find_all('hr'): style(node,border='none',border_top=f'1px solid {primary}',width='42px' if self.id=='editorial-essay' else '100%',margin='34px auto')
        for node in soup.find_all('code'): style(node,font_family='Consolas, Menlo, monospace',font_size='14px',background=p['tint'],color=primary,padding='2px 4px')
        for node in soup.find_all('pre'):
            style(node,background=p['tint'],padding='18px',margin='24px 0',font_size='13px',line_height=1.7,white_space='pre-wrap',word_break='break-word',overflow_wrap='anywhere')
            for code in node.find_all('code'): style(code,padding=0,background='transparent',color=p['text'])
        for table in soup.find_all('table'):
            style(table,width='100%',border_collapse='collapse',table_layout='fixed',margin='24px 0',font_size='13px',line_height=1.6)
            for node in table.find_all(['th','td']):
                style(node,padding='10px 8px',border_bottom='1px solid #d8dedb',text_align='left',vertical_align='top',word_break='break-word',overflow_wrap='anywhere',color=p['text'])
                if node.name=='th': style(node,background=p['tint'],font_weight=700,color=primary)
        # Table-like rows keep nested lists and their markers together without flex.
        for listing in reversed(soup.find_all(['ul','ol'])):
            ordered=listing.name=='ol'
            try: start=int(listing.get('start',1))
            except ValueError: start=1
            listing.name='section'
            style(listing,margin='12px 0 18px',padding='0 0 0 4px')
            for i,item in enumerate(listing.find_all('li',recursive=False),start):
                item.name='section';style(item,display='table',width='100%',margin='0 0 10px')
                marker=soup.new_tag('span');marker.string=f'{i}.' if ordered else '•'
                style(marker,display='table-cell',width='24px',color=primary,font_weight=700,vertical_align='top')
                body=soup.new_tag('section');style(body,display='table-cell',word_break='break-word')
                for child in list(item.contents): body.append(child.extract())
                item.append(marker);item.append(body)
        reference_section=False
        for node in soup.find_all(['h2','p']):
            role=roles.get(id(node))
            if role=='references': reference_section=True
            if role=='caption': style(node,font_size='12px',line_height=1.65,color=p['muted'],text_align='center',margin='0 8px 28px')
            elif role=='author': style(node,font_size='13px',color=p['muted'],margin='36px 0 20px',padding_top='16px',border_top='1px solid #d8dedb')
            elif reference_section:
                style(node,font_size='15px' if node.name=='h2' else '12px',line_height=1.7,color=p['muted'],margin='26px 0 12px' if node.name=='h2' else '0 0 9px',background='transparent',padding=0,border='none')
        root=soup.new_tag('section')
        style(root,font_family=SANS,font_size=f'{size}px',line_height=line,color=p['text'],background=p['paper'],padding='24px 22px' if self.id=='editorial-essay' else '20px',word_break='break-word')
        for child in list(soup.contents): root.append(child.extract())
        soup.append(root)
        return str(soup)


SAMPLE='''一篇好文章，值得一种与内容相称的阅读方式。排版从清晰开始，也为文字留出呼吸的空间。

## 让观点有清晰的层次

从一个问题出发，再沿着依据展开。**重要的判断**应当容易找到，解释和细节则自然地跟随。

> 好的阅读节奏，来自内容之间恰当的距离。

### 把细节放在合适的位置

- 标题告诉读者这一节讨论什么。
- 段落承载一个完整的想法。
    - 补充信息保留自己的层级。

## 为下一段留下空间

图文、引述与正文各有自己的角色，设计让它们彼此协调。

| 内容 | 呈现方式 |
| --- | --- |
| 观点 | 清楚、有依据 |
| 细节 | 舒展、易于阅读 |
'''
