"""Windows launcher. Runs without a terminal; only this workspace's server is reused/stopped."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import sqlite3
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data'
STATE=DATA/'server.json'
LOGS=DATA/'logs'


def message(text,error=False):
    ctypes.windll.user32.MessageBoxW(None,text,'WeWrite 创作工作台',0x10 if error else 0x40)


def server_info(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health',timeout=1) as r:
            value=json.load(r)
        if value.get('app')=='wewrite-studio' and Path(value.get('workspace','')).resolve()==ROOT: return value
    except Exception: pass
    return None


def health(port):
    return server_info(port) is not None


def expected_version():
    return json.loads((ROOT/'package.json').read_text('utf-8'))['version']


def open_workbench(port):
    # A unique navigation also bypasses an old tab's in-memory app or cached entry.
    webbrowser.open_new_tab(f'http://127.0.0.1:{port}/?v={expected_version()}&opened={time.time_ns()}')


def active_jobs():
    path=DATA/'studio.sqlite'
    if not path.exists(): return False
    with sqlite3.connect(path.as_uri()+'?mode=ro',uri=True) as db:
        return bool(db.execute("SELECT 1 FROM jobs WHERE status IN ('running','queued') LIMIT 1").fetchone())


def stop_server(previous,restart=False):
    req=urllib.request.Request(f'http://127.0.0.1:{previous["port"]}/api/shutdown',
        data=json.dumps({'restart':restart}).encode(),headers={'X-Studio-Request':'1','X-Stop-Token':previous['token'],'Content-Type':'application/json'},method='POST')
    with urllib.request.urlopen(req,timeout=5): pass
    for _ in range(50):
        if not health(previous['port']): return
        time.sleep(.1)
    raise RuntimeError('旧后台尚未退出，请稍后重新启动；不会另开一个版本混用。')


def reuse_existing(previous):
    """Only reuse this workspace's current version; never interrupt active work."""
    info=server_info(previous['port']) if previous.get('port') else None
    if not info: return False
    if info.get('version')==expected_version(): return True
    if active_jobs():
        raise RuntimeError('检测到新版本，但仍有生成任务运行。请等待任务结束，或在工作台停止任务后重新双击启动。')
    stop_server(previous,restart=True)
    return False


def state():
    try: return json.loads(STATE.read_text('utf-8'))
    except Exception: return {}


def ensure_dependencies(python,env,handle):
    lock=ROOT/'requirements-lock.txt'
    fingerprint=hashlib.sha256(lock.read_bytes()).hexdigest()
    marker=DATA/'dependencies.sha256'
    installed=marker.read_text('utf-8').strip() if marker.exists() else ''
    command=[str(python),'-c','import fastapi,uvicorn,httpx,bleach,tinycss2,wewrite,pypdf,docx,playwright,bibtexparser;from backend.app import app']
    options=dict(cwd=ROOT,env=env,stdout=handle,stderr=handle,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    check=subprocess.run(command,**options)
    if check.returncode or installed!=fingerprint:
        result=subprocess.run([str(python),'-m','pip','install','-r',str(lock)],**options)
        if result.returncode:raise RuntimeError('依赖更新未完成。请检查网络后重试；原安装标记未改变。详细记录：data/logs/setup.log')
        if subprocess.run(command,**options).returncode:raise RuntimeError('依赖安装后自检未通过，请查看 data/logs/setup.log')
        temporary=marker.with_suffix('.pending');temporary.write_text(fingerprint,'utf-8');temporary.replace(marker)


def main():
    DATA.mkdir(exist_ok=True)
    # The OS releases this mutex even if setup crashes, avoiding stale lock files.
    name='Local\\WeWriteStudio-'+hashlib.sha256(str(ROOT).lower().encode()).hexdigest()[:20]
    mutex=ctypes.windll.kernel32.CreateMutexW(None,False,name)
    ctypes.windll.kernel32.WaitForSingleObject(mutex,120000)
    try:
        previous=state()
        if '--stop' in sys.argv:
            if previous.get('port') and health(previous['port']):
                stop_server(previous)
            if '--no-browser' not in sys.argv: message('工作台已停止。文章和设置仍保存在本机。')
            return
        if reuse_existing(previous):
            if '--no-browser' not in sys.argv: open_workbench(previous['port'])
            return
        LOGS.mkdir(parents=True,exist_ok=True)
        for name in ('setup.log','server.log'):
            old=DATA/name
            if old.exists() and not (LOGS/name).exists(): old.rename(LOGS/name)
        python=ROOT/'.venv/Scripts/python.exe'
        log=LOGS/'setup.log'
        env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8',WEWRITE_HOME=str(DATA/'wewrite'),WEWRITE_STUDIO_DATA=str(DATA))
        if not python.exists():
            import venv
            venv.EnvBuilder(with_pip=True).create(ROOT/'.venv')
        with log.open('a',encoding='utf-8') as handle:
            ensure_dependencies(python,env,handle)
        if not (ROOT/'dist/index.html').exists(): raise RuntimeError('缺少预构建界面 dist。请重新解压完整工作台，或按开发说明构建。')
        port=None
        for candidate in range(8765,8865):
            with socket.socket() as test:
                try: test.bind(('127.0.0.1',candidate));port=candidate;break
                except OSError: continue
        if port is None: raise RuntimeError('没有可用的本地端口，请关闭不用的本地服务后再试')
        token=secrets.token_urlsafe(32);env['STUDIO_STOP_TOKEN']=token
        with (LOGS/'server.log').open('a',encoding='utf-8') as handle:
            process=subprocess.Popen([str(python),'-m','uvicorn','backend.app:app','--host','127.0.0.1','--port',str(port),'--no-access-log'],cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=handle,stderr=handle,creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(100):
            if health(port): break
            if process.poll() is not None: raise RuntimeError('后台服务没有启动成功。详细记录：data/logs/server.log')
            time.sleep(.2)
        else:
            process.terminate()
            raise RuntimeError('服务启动超时，请重新启动工作台。详细记录：data/logs/server.log')
        STATE.write_text(json.dumps(dict(pid=process.pid,port=port,token=token,workspace=str(ROOT))),encoding='utf-8')
        if '--no-browser' not in sys.argv: open_workbench(port)
    finally:
        ctypes.windll.kernel32.ReleaseMutex(mutex)
        ctypes.windll.kernel32.CloseHandle(mutex)


if __name__=='__main__':
    try: main()
    except Exception as exc:
        if '--no-browser' in sys.argv: raise
        message(str(exc),True)
