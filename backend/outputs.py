"""Local export snapshots. Runtime data and test workspaces stay isolated."""
import hashlib
import json
import os
import re
import tempfile
import zipfile
import io
import time
from datetime import datetime
from pathlib import Path
from . import store, rendering


def root():
    configured=os.environ.get('WEWRITE_STUDIO_OUTPUT')
    if configured: return Path(configured).resolve()
    return (store.ROOT/'output' if store.DATA==store.ROOT/'data' else store.DATA/'output')


def diagnostics():
    p=root()/'diagnostics'/'connection-tests'
    p.mkdir(parents=True,exist_ok=True)
    return p


def safe_title(title):
    value=re.sub(r'[<>:"/\\|?*\x00-\x1f]','_',title).strip(' .')[:48].rstrip(' .') or '未命名文章'
    if re.fullmatch(r'(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?',value): value='_'+value
    return value


def archive(a):
    if not a['content'].strip(): raise ValueError('请先写作或导入正文')
    with store.LOCK:
        try:
            package=rendering.export_zip(a)
            with zipfile.ZipFile(io.BytesIO(package)) as z:
                entries={name:z.read(name) for name in z.namelist()}
            # Missing selected images must not produce a deceptively complete snapshot.
            if any('images/'+im['filename'] not in entries for im in a['images'] if im.get('selected',True)):
                raise ValueError('部分配图文件缺失，请重新上传或取消采用后再导出')
            digest=hashlib.sha256(store.encode([a['revision'],sorted((k,hashlib.sha256(v).hexdigest()) for k,v in entries.items())]).encode()).hexdigest()
            parent=root()/'articles'/a['id'];parent.mkdir(parents=True,exist_ok=True)
            for record in parent.glob('*/manifest.json'):
                info=json.loads(record.read_text('utf-8'))
                if info.get('digest')==digest and all((record.parent/n).is_file() for n in [*entries,info['files']['zip']]):
                    return dict(info,path=str(record.parent))
            stamp=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
            base=f'{safe_title(a["title"])}_{stamp}_r{a["revision"]}'
            folder=parent/f'{stamp}_{safe_title(a["title"])}_r{a["revision"]}'
            info=dict(article_id=a['id'],revision=a['revision'],title=a['title'],created=store.now(),digest=digest,
                      basename=base,files={'md':'文章.md','html':'排版.html','zip':base+'.zip'})
            with tempfile.TemporaryDirectory(prefix='.pending-',dir=parent) as temporary:
                p=Path(temporary)
                for name,data in entries.items():
                    dest=p/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
                (p/info['files']['zip']).write_bytes(package)
                (p/'manifest.json').write_text(json.dumps(info,ensure_ascii=False,indent=2),'utf-8')
                for attempt in range(3):
                    try:
                        p.rename(folder);break
                    except PermissionError:
                        if attempt==2: raise
                        time.sleep(.1*(attempt+1))
            return dict(info,path=str(folder))
        except OSError as exc:
            raise ValueError('文章归档失败，请检查输出目录权限和磁盘空间；已有版本未被覆盖') from exc


def public_info(info):
    return {k:info[k] for k in ('article_id','revision','title','created','path','basename','digest')}
