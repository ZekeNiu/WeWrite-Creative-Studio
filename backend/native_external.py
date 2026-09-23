"""Isolated deterministic WeWrite/WeChat operations. Secrets arrive only on stdin."""
import json
import sys
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit


def execute(packet):
    import requests
    home=Path(packet['home']);receipt=home/'external-receipt.json'
    state=dict(action=packet['action'],requests=[],result=None)
    def save():receipt.write_text(json.dumps(state,ensure_ascii=False,indent=2),'utf-8')
    def guard():
        if (home/'cancel-requested').exists():raise InterruptedError('已停止后续微信请求；已上传素材保留')
        with sqlite3.connect(Path(packet['database']).as_uri()+'?mode=ro',uri=True) as db:
            job=db.execute('SELECT status FROM jobs WHERE id=?',(packet['job_id'],)).fetchone()
            if not job or job[0]!='running':raise InterruptedError('任务已结束或后台已重启，未继续发送微信请求')
            a=db.execute('SELECT data FROM articles WHERE id=?',(packet['article_id'],)).fetchone()
            if not a or json.loads(a[0])['revision']!=packet['revision']:raise ValueError('文章已更新，未继续发送；已上传素材保留')
            account=db.execute('SELECT data FROM account_memory WHERE id=1').fetchone()
            if not account or json.loads(account[0])['revision']!=packet['account_revision']:raise ValueError('账号参考已改变，未继续发送')
            secret=db.execute('SELECT value FROM secrets WHERE id=?',('wewrite:wechat',)).fetchone()
            import hashlib
            if not secret or hashlib.sha256(secret[0].encode()).hexdigest()!=packet['credential_id']:raise ValueError('微信凭证已变更，未继续发送')
    old_get,old_post=requests.get,requests.post
    def request(fn,url,**kwargs):
        if urlsplit(url).hostname!='api.weixin.qq.com' or urlsplit(url).scheme!='https':raise ValueError('此动作只允许微信官方接口')
        guard()
        if len(state['requests'])>=50:raise ValueError('微信请求次数超过本次动作上限')
        item=dict(endpoint=urlsplit(url).path,status='sent');state['requests'].append(item);save()
        try:
            response=fn(url,**{**kwargs,'allow_redirects':False,'timeout':30})
            if response.status_code!=200:raise ValueError('微信接口 HTTP '+str(response.status_code))
            data=response.json()
            if data.get('errcode',0):raise ValueError('微信接口错误码 '+str(data['errcode']))
            if '/datacube/' in url and not isinstance(data.get('list'),list):raise ValueError('微信接口没有返回统计列表，未视为零数据')
        except Exception as exc:
            item['status']='unknown';save()
            raise ValueError(str(exc) if isinstance(exc,ValueError) and str(exc).startswith('微信') else '微信接口未确认成功，请核对草稿箱后再操作') from None
        item.update(status='completed',**{k:data[k] for k in ('media_id','url') if k in data});save()
        return response
    requests.get=lambda url,**kw:request(old_get,url,**kw)
    requests.post=lambda url,**kw:request(old_post,url,**kw)
    from wewrite.toolkit.wechat_api import get_access_token,upload_image,upload_thumb
    from wewrite.toolkit.publisher import create_draft,create_image_post,get_draft
    try:
        token=get_access_token(packet['appid'],packet['secret'],True)
        action=packet['action']
        if action=='stats':
            from wewrite.commands.fetch_stats import fetch_article_total
            rows=fetch_article_total(token,packet['date'])
            result=dict(rows=rows)
        elif action=='draft_read':
            result=dict(html=get_draft(token,packet['media_id']))
        elif action=='image_post':
            ids=[upload_thumb(token,str(home/path)) for path in packet['images']]
            created=create_image_post(token,packet['title'],ids,packet.get('description',''),False,False)
            result=dict(media_id=created.media_id,image_count=created.image_count)
        else:
            from bs4 import BeautifulSoup
            soup=BeautifulSoup((home/'publish.html').read_text('utf-8'),'html.parser')
            for im in soup.find_all('img'):
                path=packet['image_map'].get(im.get('src'))
                if not path:raise ValueError('正文图片没有对应的本地文件')
                im['src']=upload_image(token,str(home/path))
            thumb=upload_thumb(token,str(home/packet['cover']))
            created=create_draft(token,packet['title'],str(soup),packet['digest'],thumb,packet.get('author',''))
            result=dict(media_id=created.media_id)
        state['result']=result;save();return dict(status='completed',result=result)
    except InterruptedError as exc:return dict(status='cancelled',error=str(exc))
    except Exception as exc:return dict(status='failed',error=str(exc))
    finally:requests.get,requests.post=old_get,old_post


if __name__=='__main__':
    try:result=execute(json.load(sys.stdin))
    except Exception:result=dict(status='failed',error='微信动作未完成；本地产物已保留')
    print(json.dumps(result,ensure_ascii=False))
