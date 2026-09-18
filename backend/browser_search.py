"""Local browser worker with a dedicated profile and public-network-only requests."""
import asyncio
import base64
from contextlib import asynccontextmanager
from urllib.parse import urlsplit, urlencode, parse_qs
from . import store
from .public_network import public_url

LOCK=asyncio.Lock()
INTERACTIVE=None


async def guard(route,lightweight=True):
    if (lightweight and route.request.resource_type in ('image','media','font')) or not await public_url(route.request.url):
        await route.abort()
    else: await route.continue_()


async def launch(headless=True):
    from playwright.async_api import async_playwright
    profile=store.DATA/'cache'/'research-browser'
    profile.parent.mkdir(parents=True,exist_ok=True)
    legacy=store.DATA/'research-browser'
    if legacy.exists() and not profile.exists(): legacy.rename(profile)
    driver=await async_playwright().start()
    for channel in ('msedge','chrome',None):
        try:
            context=await driver.chromium.launch_persistent_context(str(profile),
                channel=channel,headless=headless,accept_downloads=False,service_workers='block',
                viewport={'width':1200,'height':800},locale='zh-CN',args=['--disable-background-networking'])
            async def route_request(route): await guard(route,headless)
            await context.route('**/*',route_request)
            await context.route_web_socket('**/*',lambda ws:ws.close())
            return driver,context
        except Exception: continue
    await driver.stop()
    raise ValueError('没有可用的浏览器，请安装或更新 Edge / Chrome 后重试')


@asynccontextmanager
async def browser():
    async with LOCK:
        if INTERACTIVE: raise ValueError('检索浏览器正在等待验证，请完成后点击“继续检索”')
        driver,context=await launch()
        try: yield context
        finally:
            await context.unroute_all(behavior='ignoreErrors')
            try: await asyncio.wait_for(context.close(),10)
            finally: await driver.stop()


def unwrap(url):
    if url.startswith('/url?'): url='https://www.google.com'+url
    if (urlsplit(url).hostname or '') in ('www.google.com','google.com') and urlsplit(url).path=='/url':
        return parse_qs(urlsplit(url).query).get('q',parse_qs(urlsplit(url).query).get('url',[url]))[0]
    if url.startswith('//'): url='https:'+url
    if (urlsplit(url).hostname or '').endswith('duckduckgo.com'):
        value=parse_qs(urlsplit(url).query).get('uddg',[''])[0]
        if value.startswith(('http://','https://')): return value
    if 'bing.com/ck/' in url:
        value=parse_qs(urlsplit(url).query).get('u',[''])[0]
        if value.startswith('a1'):
            try: return base64.urlsafe_b64decode(value[2:]+'='*(-len(value[2:])%4)).decode()
            except (ValueError,UnicodeError): pass
    return url


async def search(query,engine='bing'):
    from playwright.async_api import TimeoutError as BrowserTimeout
    url=search_url(query,engine)
    selector={'google':'div.MjjYud, div.g','bing':'#b_results .b_algo','baidu':'#content_left .result, #content_left .c-container','duckduckgo':'.result'}[engine]
    # Read ordinary public HTML first. It avoids depending on the engine's visual
    # reveal scripts; browser rendering remains the fallback for dynamic pages.
    from .materials import fetch_bytes
    from bs4 import BeautifulSoup
    try:
        raw,_=await fetch_bytes(url,max_bytes=8*1024*1024)
        soup=BeautifulSoup(raw,'html.parser');rows=[]
        for node in soup.select(selector)[:8]:
            a=node.select_one('h2 a,h3 a,.result__a')
            if engine=='google':
                h=node.select_one('h3');a=h.find_parent('a') if h else None
            if a and a.get('href','').startswith('/url?'): a['href']=unwrap(a['href'])
            if a and a.get('href','').startswith(('https://','http://','//')):
                rows.append(dict(title=a.get_text(' ',strip=True),url=unwrap(a['href']),content=node.get_text(' ',strip=True)[:1600],provider=engine,status='excerpt_only'))
        if rows: return rows
        if soup.title and any(x in soup.title.get_text().lower() for x in ('captcha','安全验证','人机验证')):
            raise ValueError('搜索页面需要验证，正在切换其他来源')
    except ValueError as exc:
        if '需要验证' in str(exc): raise
    except Exception: pass
    try:
        async with browser() as context:
            page=await context.new_page()
            await page.goto(url,wait_until='commit',timeout=25000)
            try: await page.locator(selector).first.wait_for(state='attached',timeout=15000)
            except BrowserTimeout: raise ValueError('搜索页面暂时不可读取或需要验证，正在切换渠道') from None
            rows=await page.locator(selector).evaluate_all('''els => els.slice(0,8).map(e => {
                const a=e.querySelector('h2 a,h3 a,.result__a')||e.querySelector('h3')?.closest('a');
                return {title:a?.textContent?.trim()||'',url:a?.href||'',content:(e.textContent||'').trim().slice(0,1600)};
            }).filter(x=>x.url&&x.title)''')
            return [dict(x,url=unwrap(x['url']),provider=engine,status='excerpt_only') for x in rows]
    except BrowserTimeout: raise ValueError('浏览器搜索超时，正在尝试其他渠道') from None


def search_url(query,engine):
    return {'google':'https://www.google.com/search?'+urlencode({'q':query,'num':8}),
            'bing':'https://www.bing.com/search?'+urlencode({'q':query}),
            'baidu':'https://www.baidu.com/s?'+urlencode({'wd':query}),
            'duckduckgo':'https://html.duckduckgo.com/html/?'+urlencode({'q':query})}[engine]


async def read(url):
    from playwright.async_api import TimeoutError as BrowserTimeout
    if not await public_url(url): raise ValueError('只能读取公开网页')
    try:
        async with browser() as context:
            page=await context.new_page()
            r=await page.goto(url,wait_until='commit',timeout=25000)
            if r and r.status>=400: raise ValueError('网页拒绝访问')
            await page.locator('body').wait_for(timeout=15000)
            await page.wait_for_timeout(1200)
            data=await page.evaluate('''() => {
                const roots=[...document.querySelectorAll('#js_content,article,main')];
                const root=roots.sort((a,b)=>b.textContent.length-a.textContent.length)[0]||document.body;
                const copy=root.cloneNode(true);
                copy.querySelectorAll('script,style,nav,footer,form,noscript').forEach(x=>x.remove());
                return {title:document.title,text:copy.innerText||copy.textContent||'',url:location.href};
            }''')
            from .materials import blocked_page
            if len(data['text'].strip())<300 or blocked_page(data['title'],data['text']):
                raise ValueError('网页需要验证或未取得正文')
            return data
    except BrowserTimeout: raise ValueError('网页读取超时') from None


async def open_verification(url):
    global INTERACTIVE
    if not await public_url(url): raise ValueError('只能打开公开来源网页')
    async with LOCK:
        if INTERACTIVE: return
        driver,context=await launch(False)
        try:
            page=await context.new_page(); await page.goto(url,wait_until='domcontentloaded',timeout=25000)
            INTERACTIVE=(driver,context)
        except Exception:
            await context.close(); await driver.stop(); raise ValueError('验证窗口打开失败，请重试') from None


async def close_verification():
    global INTERACTIVE
    async with LOCK:
        if INTERACTIVE:
            driver,context=INTERACTIVE; INTERACTIVE=None
            await context.close(); await driver.stop()
