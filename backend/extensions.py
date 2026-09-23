"""Explicit upstream extensions, isolated from the automatic writing pipeline."""
import asyncio
import copy
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import date
from pathlib import Path
from typing import Literal
from bs4 import BeautifulSoup
import yaml
from fastapi import APIRouter
from pydantic import BaseModel,Field
from . import account_memory,store,security,native_catalog,native_skills,native_runtime,rendering,materials,workflow

router=APIRouter(prefix='/api/extensions')
SECRET='wewrite:wechat'


def credentials():
    raw=security.key(SECRET)
    return json.loads(raw) if raw else dict(appid='',secret='')


def config():
    blob=store.get_secret(SECRET) or ''
    return dict(configured=bool(blob),credential_id=hashlib.sha256(blob.encode()).hexdigest(),account_revision=account_memory.get()['revision'])


@router.get('')
def overview():
    value=account_memory.get()
    return dict(**config(),personas=native_catalog.personas(),custom_personas=value.get('personas',[]),themes=value.get('themes',[]),
                online_metrics=value.get('online_metrics',[]),bindings=value.get('wechat_bindings',[]),
                platforms=[yaml.safe_load(p.read_text('utf-8')) for p in sorted((native_skills.SKILLS/'wewrite-rewrite/platforms').glob('*.yaml'))],
                jobs=store.jobs('__extensions__'))


@router.put('/wechat')
def save_credentials(value:dict):
    with store.LOCK:
        if value.get('credential_id')!=config()['credential_id']:raise store.Conflict('微信配置已更新，请刷新后重试')
        if value.get('remove'):
            security.save_key(SECRET,'');return config()
        appid=str(value.get('appid','')).strip();secret=str(value.get('secret','')).strip()
        if not re.fullmatch(r'wx[0-9a-zA-Z]{8,32}',appid) or not secret or len(secret)>512:raise ValueError('请填写有效 AppID 和 AppSecret')
        security.save_key(SECRET,json.dumps(dict(appid=appid,secret=secret)))
    return config()


@router.post('/personas')
def save_persona(value:dict):
    native_catalog.save_persona(value);return overview()


@router.post('/bindings')
def save_binding(value:dict):
    a=store.get_article(value['article_id']);msgid=str(value.get('msgid',''))
    if not re.fullmatch(r'\d+_\d+',msgid):raise ValueError('请填写微信统计中的 msgid，格式如 123456_1；草稿 media_id 不能代替')
    def mutate(v):
        rows=v.setdefault('wechat_bindings',[])
        if any(x['msgid']==msgid and x['article_id']!=a['id'] for x in rows):raise ValueError('该微信文章已经关联另一篇本地稿')
        rows[:]=[x for x in rows if x['article_id']!=a['id']]
        rows.append(dict(article_id=a['id'],msgid=msgid,title=a['title']))
    account_memory.change(value['revision'],mutate,'明确关联微信统计文章');return overview()


class Action(BaseModel):
    action:Literal['theme','rewrite','publish','image_post','stats','stats_review','draft_read']
    article_id:str=''
    revision:int=0
    account_revision:int
    client_id:str=Field(pattern=r'^[a-f0-9-]{32,36}$')
    url:str=''
    name:str=''
    label:str=''
    platforms:list[Literal['xiaohongshu','douyin']]=Field(default_factory=lambda:['xiaohongshu','douyin'],max_length=2)
    date:str=''
    preview_hash:str=''
    description:str=Field(default='',max_length=1000)
    digest:str=Field(default='',max_length=120)
    media_id:str=Field(default='',max_length=200)


def preflight(a,action,digest='',description=''):
    rendered=rendering.render(a);issues=[]
    selected=[x for x in a['images'] if x.get('selected',True)]
    files={x['filename']:store.article_dir(a['id'])/'assets'/x['filename'] for x in selected}
    root=(store.article_dir(a['id'])/'assets').resolve()
    if any(not p.resolve().is_relative_to(root) or not p.is_file() for p in files.values()):issues.append('采用图片缺少有效本地文件')
    if not a['title'].strip():issues.append('请填写标题')
    if action=='image_post' and len(a['title'])>32:issues.append('图片帖标题不能超过32字')
    if action=='image_post':
        if not 1<=len(selected)<=20:issues.append('图片帖需要1—20张采用图片')
    else:
        if not 200<=len(a['content'])<=20000:issues.append('草稿正文应为200—20000字')
        if not any(x.get('role')=='cover' for x in selected):issues.append('推送草稿箱需要独立封面')
        if len(digest.encode('utf-8'))>120:issues.append('摘要超过120个UTF-8字节')
        issues += [x['message'] for x in rendered['compatibility'] if x['level']=='ERROR']
        soup=BeautifulSoup(rendered['body'],'html.parser')
        if len(soup.find_all('img'))>10:issues.append('正文图片超过10张')
        if any(sum(int(c.get('colspan',1)) for c in tr.find_all(['td','th'],recursive=False))>4 for tr in soup.find_all('tr')):issues.append('表格超过4列')
        allowed={f'/api/articles/{a["id"]}/assets/{name}' for name in files}
        if any(im.get('src') not in allowed for im in soup.find_all('img')):issues.append('正文图片须先导入本地图片栏，不能直接发布外部或无效图片链接')
    fingerprint=hashlib.sha256(store.encode([a['id'],a['revision'],action,rendered['body'],selected,digest,description,config()['credential_id'],account_memory.get()['revision']]).encode()).hexdigest()
    return dict(revision=a['revision'],title=a['title'],digest=digest or rendered['digest'],html=rendered['html'],issues=issues,preview_hash=fingerprint,
                configured=config()['configured'],images=len(selected),cover=next((x['filename'] for x in selected if x.get('role')=='cover'),None))


@router.post('/preview')
def preview(value:dict):
    if value.get('action') not in ('publish','image_post'):raise ValueError('未知发布类型')
    return preflight(store.get_article(value['article_id']),value['action'],value.get('digest',''),value.get('description',''))


@router.post('/actions')
async def start(value:Action):
    with store.LOCK:
        with store.connection() as db:
            old=db.execute("SELECT data FROM jobs WHERE json_extract(data,'$.request.client_id')=?",(value.client_id,)).fetchone()
        if old:
            existing=json.loads(old[0])
            if existing['request'].get('action')!=value.action or existing['request'].get('article_id','')!=value.article_id:raise ValueError('动作编号已用于其他请求')
            return existing
        if value.account_revision!=account_memory.get()['revision']:raise store.Conflict('账号参考已更新，请刷新扩展面板')
        if value.action=='theme':native_catalog.identifier(value.name)
        else:
            a=store.get_article(value.article_id)
            if a['revision']!=value.revision:raise store.Conflict('文章已更新，请刷新后重试')
            if value.action=='rewrite' and (not a['content'].strip() or not value.platforms):raise ValueError('需要正文和目标平台')
        if value.action in ('publish','image_post'):
            check=preflight(a,value.action,value.digest,value.description)
            if value.preview_hash!=check['preview_hash']:raise store.Conflict('文章或发布设置已改变，请重新查看预览')
            if check['issues']:raise ValueError('；'.join(check['issues']))
        if value.action in ('publish','image_post','stats','draft_read') and not config()['configured']:raise ValueError('尚未配置公众号 AppID / AppSecret；本地成果仍可使用')
        if value.action=='stats':
            try:day=date.fromisoformat(value.date)
            except ValueError:raise ValueError('请选择文章群发日期') from None
            if day>=date.today():raise ValueError('请查询昨天或更早的日期；刚发表的内容稍后再查')
        if value.action=='draft_read':
            receipts=a.get('extensions',[])
            if not value.media_id or not any(x.get('result',{}).get('media_id')==value.media_id and x.get('action')=='publish' for x in receipts):raise ValueError('请选择本篇已推送成功的草稿记录')
        j=store.create_job(value.article_id or '__extensions__',dict(stage=value.action,credential_id=config()['credential_id'],**value.model_dump()))
        workflow.TASKS[j['id']]=asyncio.create_task(run(j['id']))
        return j


async def external(session,value,prepared):
    secret=credentials();cfg=config()
    if value['credential_id']!=cfg['credential_id']:raise store.Conflict('微信凭证已变更，本次未发送')
    packet=dict(home=str(session.home),database=str(store.DATA/'studio.sqlite'),job_id=session.job_id,article_id=session.article['id'],revision=session.article['revision'],
                credential_id=cfg['credential_id'],account_revision=value['account_revision'],action=value['action'],**secret,**prepared)
    store.update_job(session.job_id,external_inflight=True,external_home=str(session.home))
    env={**os.environ,'PYTHONUTF8':'1','PYTHONDONTWRITEBYTECODE':'1'}
    process=await asyncio.create_subprocess_exec(sys.executable,'-m','backend.native_external',cwd=store.ROOT,env=env,
        stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE,creationflags=0x08000000 if os.name=='nt' else 0)
    try:
        async with asyncio.timeout(900):out,_=await process.communicate(json.dumps(packet,ensure_ascii=False).encode())
        if process.returncode:raise ValueError('微信动作中断，成功状态未知；请核对草稿箱，任务不会自动重试')
        result=json.loads(out)
        if result['status']=='cancelled':raise asyncio.CancelledError()
        if result['status']!='completed':raise ValueError(result.get('error','微信动作未完成'))
        return result['result']
    except BaseException:
        if process.returncode is None:process.kill();await process.wait()
        raise
    finally:
        receipt=session.home/'external-receipt.json'
        if receipt.exists():
            store.update_job(session.job_id,external_receipt=json.loads(receipt.read_text('utf-8')))
            shutil.copy2(receipt,session.directory/'wechat-receipt.json')
        store.update_job(session.job_id,external_inflight=False)


async def learn_theme(jid,value):
    from wewrite.commands.learn_theme import extract_styles,analyze_styles,generate_theme_yaml,_attach_title
    native_skills.verify()
    blob,url=await materials.fetch_bytes(value['url'],4*1024*1024)
    soup=BeautifulSoup(blob,'html.parser');content=soup.find(id='js_content')
    if content is None:raise ValueError('没有读到公众号原始排版；请确认链接可公开读取，未生成替代主题')
    _attach_title(soup,content);grouped=extract_styles(content)
    if not any(grouped.values()):raise ValueError('没有可学习的内联样式')
    raw=generate_theme_yaml(value['name'],getattr(content,'_wewrite_title',''),analyze_styles(grouped))
    target=store.DATA/'extension-artifacts'/jid;target.mkdir(parents=True)
    (target/'theme.yaml').write_text(raw,'utf-8')
    account_memory.guard(dict(revision=value['account_revision']))
    native_catalog.save_theme(value['account_revision'],value['name'],value['label'],yaml.safe_load(raw),url)
    store.update_job(jid,result=dict(theme=value['name'],source=url),native=dict(upstream_revision=native_skills.verify(),reads=[{k:v for k,v in d.items() if k!='content'} for d in native_skills.documents('theme','industry-observer')]))


def project_stats(value,rows):
    bindings=account_memory.get().get('wechat_bindings',[]);result=[];unmatched=[]
    for row in rows:
        binding=next((b for b in bindings if b['msgid']==row.get('msgid')),None)
        if not binding:unmatched.append(dict(msgid=row.get('msgid'),title=row.get('title')));continue
        for detail in row.get('details',[]):
            if not detail.get('stat_date'):continue
            stats=dict(read_count=detail.get('int_page_read_count'),share_count=detail.get('share_count'),like_count=detail.get('like_count'))
            result.append(dict(article_id=binding['article_id'],msgid=row['msgid'],published_date=row.get('ref_date',value['date']),observed_at=detail['stat_date'],stats=stats,raw=detail))
    def mutate(v):
        known={(x['article_id'],x['msgid'],x['observed_at']):x for x in v.get('online_metrics',[])}
        for x in result:known[(x['article_id'],x['msgid'],x['observed_at'])]=x
        v['online_metrics']=list(known.values())
    if result:account_memory.change(value['account_revision'],mutate,'回填微信原始效果数据')
    return dict(matched=len(result),unmatched=unmatched,rows=rows)


async def run(jid):
    from .execution_budget import ACTIVE
    token=ACTIVE.set(jid);session=None
    try:
        j=store.job(jid);value=j['request'];action=value['action']
        account_memory.guard(dict(revision=value['account_revision']))
        if value['article_id'] and store.get_article(value['article_id'])['revision']!=value['revision']:raise store.Conflict('文章已更新，本次未执行')
        store.update_job(jid,status='running',message='正在执行独立扩展动作')
        if action=='theme':await learn_theme(jid,value)
        elif action in ('rewrite','stats_review'):
            a=store.get_article(j['article_id']);stage='stats' if action=='stats_review' else 'rewrite'
            packet=await native_runtime.generate(a,jid,stage,value)
            def mutate(v):
                account_memory.guard(packet['account_use'])
                v.setdefault('extensions',[]).append(dict(job_id=jid,action=action,native=packet['native'],result=packet['result'],created=store.now()))
            store.save_article(a['id'],value['revision'],mutate,'上游独立扩展 '+action)
            if packet['result'].get('needs_input'):store.update_job(jid,status='needs_input',ended=store.now(),message='版本已保留；上游质量检查仍有待处理项');return
        else:
            a=store.get_article(j['article_id']);session=native_runtime.Session(a,jid,'stats' if action=='stats' else 'publish',value)
            await session.prepare();account_memory.guard(session.used)
            for item in store.job(jid)['native']['reads']:item['reader']='deterministic_adapter'
            root=session.home/'assets';root.mkdir(exist_ok=True);images=[];image_map={};cover=None
            if action in ('publish','image_post'):
                for im in a['images']:
                    if not im.get('selected',True):continue
                    source=store.article_dir(a['id'])/'assets'/im['filename'];destination=root/im['filename'];shutil.copy2(source,destination)
                    path=destination.relative_to(session.home).as_posix();images.append(path)
                    image_map[f'/api/articles/{a["id"]}/assets/{im["filename"]}']=path
                    if im.get('role')=='cover' and cover is None:cover=path
                body=rendering.render(a);(session.home/'publish.html').write_text(body['body'],'utf-8')
                (session.directory/'article.md').write_text(body['markdown'],'utf-8')
                (session.directory/'preview.html').write_text(body['html'],'utf-8')
                await session.cli(['run','permission','publish','allow'],True)
                await session.cli(['run','update','--patch',json.dumps(dict(flags=dict(skip_publish=False)))],True)
            prepared=dict(title=a['title'],author=a['layout']['author'],digest=value['digest'] or (body['digest'] if action=='publish' else ''),description=value['description'],cover=cover,images=images,image_map=image_map,date=value['date'],media_id=value['media_id'])
            result=await external(session,value,prepared)
            store.update_job(jid,result=result)
            if action=='stats':result=project_stats(value,result['rows']);store.update_job(jid,result=result)
            elif action=='draft_read':
                from wewrite.toolkit.publisher import html_to_plaintext
                result=dict(content=html_to_plaintext(result['html']),media_id=value['media_id'],note='远端草稿副本；未覆盖正文，未推定为人工定稿')
                store.update_job(jid,result=result)
            else:
                await session.cli(['run','update','--patch',json.dumps(dict(publish=dict(media_id=result['media_id'],preview_html=str(session.directory/'preview.html'))))],True)
                await session.cli(['run','step','publish','completed'])
                def mutate(v):v.setdefault('extensions',[]).append(dict(job_id=jid,action=action,result=result,created=store.now(),source_revision=value['revision']))
                try:store.save_article(a['id'],value['revision'],mutate,'记录微信草稿回执')
                except store.Conflict:
                    store.update_job(jid,status='needs_input',ended=store.now(),message='微信已创建草稿，但本地正文已有更新；回执保留在任务中，请勿重复推送');return
            account_memory.finish_use(session.used,'returned')
        store.update_job(jid,status='completed',ended=store.now(),message='扩展动作完成，本地成果与回执已保留')
    except asyncio.CancelledError:store.update_job(jid,status='cancelled',ended=store.now(),message='已停止；已发送微信请求请查看保留回执')
    except Exception as exc:store.update_job(jid,status='needs_input' if isinstance(exc,store.Conflict) else 'failed',ended=store.now(),message=str(exc))
    finally:
        if session:account_memory.finish_use(session.used,'returned' if store.job(jid)['status']=='completed' else 'incomplete')
        ACTIVE.reset(token);workflow.TASKS.pop(jid,None);store.event(jid,'finished',status=store.job(jid)['status'])
