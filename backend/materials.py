import io
import zipfile
from pathlib import Path
from urllib.parse import urlsplit,urljoin
import httpx
from bs4 import BeautifulSoup
from . import store
from .public_network import public_url

MAX_BYTES=20*1024*1024


def blocked_page(title,text):
    return any(x in title.lower() for x in ('captcha','access denied','just a moment','client challenge','安全验证','人机验证','访问验证')) or any(x in text.lower() for x in ('a required part of this site couldn', 'verify you are human', 'enable javascript and cookies to continue'))


async def fetch_bytes(url,max_bytes=MAX_BYTES):
    async with httpx.AsyncClient(timeout=35,follow_redirects=False) as client:
        for _ in range(5):
            u=urlsplit(url)
            if u.scheme not in ('http','https') or not u.hostname or u.username: raise ValueError('请输入公开网页的 http(s) 链接')
            if not await public_url(url):
                raise ValueError('素材链接只支持公开网站，不能读取本机或内网服务')
            async with client.stream('GET',url,headers={'User-Agent':'Mozilla/5.0 WeWriteStudio/1.0'}) as r:
                if r.is_redirect:
                    url=urljoin(url,r.headers.get('location','')); continue
                if r.status_code>=400: raise ValueError(f'网页暂时无法读取（HTTP {r.status_code}），可手动粘贴正文')
                data=bytearray()
                async for chunk in r.aiter_bytes():
                    data.extend(chunk)
                    if len(data)>max_bytes: raise ValueError('素材文件过大，请选择 20 MB 内的文件')
                return bytes(data),str(r.url)
    raise ValueError('网页重定向过多，请粘贴最终链接或正文')


def extract_file(name,blob):
    suffix=Path(name).suffix.lower()
    if len(blob)>MAX_BYTES: raise ValueError('文件不能超过 20 MB')
    pages=[]
    if suffix=='.pdf':
        from pypdf import PdfReader
        reader=PdfReader(io.BytesIO(blob))
        if reader.is_encrypted: raise ValueError('请先解除 PDF 密码后再导入')
        if len(reader.pages)>500: raise ValueError('PDF 超过 500 页，请先提取相关章节')
        pages=[{'page':i+1,'text':p.extract_text() or ''} for i,p in enumerate(reader.pages)]
        text='\n\n'.join(f'[第 {p["page"]} 页]\n{p["text"]}' for p in pages)
        if sum(len(p['text'].strip()) for p in pages)<30: raise ValueError('此 PDF 未读到可用文字，可能是扫描件。请先 OCR 或粘贴文字。')
    elif suffix=='.docx':
        from docx import Document
        z=zipfile.ZipFile(io.BytesIO(blob))
        if sum(x.file_size for x in z.infolist())>100*1024*1024: raise ValueError('解压后的文档过大')
        doc=Document(io.BytesIO(blob))
        text='\n\n'.join(p.text for p in doc.paragraphs)
        for table in doc.tables: text+='\n'+'\n'.join(' | '.join(c.text for c in row.cells) for row in table.rows)
    elif suffix in ('.md','.txt'):
        try: text=blob.decode('utf-8-sig')
        except UnicodeDecodeError: text=blob.decode('gb18030')
    else: raise ValueError('支持 TXT、Markdown、DOCX 和文本型 PDF')
    if not text.strip(): raise ValueError('文件没有可用的文字内容')
    if len(text)>1_000_000: raise ValueError('材料文字过长，请拆分后导入')
    return text,pages


def source(title,text,url='',kind='user',pages=None,filename=''):
    return dict(id='S'+store.uid()[:10],title=title,text=text,url=url,kind=kind,pages=pages or [],
                filename=filename,selected=True,personal_material=False,summary=text[:220],created=store.now(),
                status='user_provided' if kind=='user' else 'retrieved',use='')


async def from_url(url):
    from .source_reader import read
    return await read(url)


async def read_url(url):
    try: blob,final=await fetch_bytes(url)
    except httpx.HTTPError: raise ValueError('网页读取失败，可改为粘贴正文或上传文件') from None
    if blob.startswith(b'%PDF'):
        text,pages=extract_file('source.pdf',blob)
        return source(Path(urlsplit(final).path).name,text,final,'web',pages)
    soup=BeautifulSoup(blob,'html.parser')
    title=soup.title.get_text(strip=True) if soup.title else urlsplit(final).hostname
    if blocked_page(title,soup.get_text(' ',strip=True)[:3000]):
        raise ValueError('网页需要验证，尚未取得正文')
    citation_doi=soup.find('meta',attrs={'name':'citation_doi'})
    published=soup.find('meta',attrs={'property':'article:published_time'}) or soup.find('meta',attrs={'name':'citation_publication_date'})
    def meta(name):
        node=soup.find('meta',attrs={'name':name})
        return node.get('content','') if node else ''
    bib=dict(title=meta('citation_title') or title,authors=[n.get('content','') for n in soup.find_all('meta',attrs={'name':'citation_author'})],
        venue=meta('citation_journal_title') or meta('citation_conference_title'),volume=meta('citation_volume'),issue=meta('citation_issue'),
        pages=meta('citation_firstpage')+('-'+meta('citation_lastpage') if meta('citation_lastpage') else ''),
        doi=meta('citation_doi'),published_date=meta('citation_publication_date'),year=meta('citation_publication_date')[:4],
        document_type='J' if meta('citation_journal_title') else 'C' if meta('citation_conference_title') else 'EB',url=final,access_date=store.now()[:10])
    if urlsplit(final).hostname in ('arxiv.org','www.arxiv.org'): bib.update(document_type='PP',platform='arXiv')
    for t in soup(['script','style','nav','footer','noscript','form']): t.decompose()
    roots=soup.select('#js_content,article,main')
    body=max(roots,key=lambda x:len(x.get_text()),default=soup.body or soup)
    text=body.get_text('\n',strip=True)
    if len(text)<300: raise ValueError('网页未返回足够正文，可能需要登录。请粘贴你可见的文章内容。')
    result=source(title,text[:200000],final,'web')
    if not bib['doi'] and len(body.select('a'))>30 and len(body.select('a'))>len(body.select('p'))*3:
        result['status']='metadata_only'
    # A bibliographic landing page is not the full research paper.
    host=(urlsplit(final).hostname or '').lower()
    if host=='pubmed.ncbi.nlm.nih.gov' or (host in ('arxiv.org','www.arxiv.org') and urlsplit(final).path.startswith('/abs/')):
        result['status']='abstract_only'
    elif bib['document_type'] in ('J','C','PP'):
        headings=' '.join(h.get_text(' ',strip=True).lower() for h in body.select('h1,h2,h3,h4'))
        full_sections=any(k in headings for k in ('methods','methodology','results','discussion','conclusion','方法','结果','讨论','结论'))
        if not full_sections or len(text)<4000: result['status']='abstract_only'
    result['doi']=citation_doi.get('content','') if citation_doi else ''
    result['published_date']=published.get('content','') if published else ''
    result['bibliography']=bib
    result['metadata_provenance']=[{'provider':'page_meta','url':final,'retrieved_at':store.now()}]
    return result
