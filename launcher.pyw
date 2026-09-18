"""Windows launcher. Runs without a terminal; only this workspace's server is reused/stopped."""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT=Path(__file__).resolve().parent
DATA=ROOT/'data'
STATE=DATA/'server.json'


def message(text,error=False):
    ctypes.windll.user32.MessageBoxW(None,text,'WeWrite 创作工作台',0x10 if error else 0x40)


def health(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health',timeout=1) as r:
            value=json.load(r)
        return value.get('app')=='wewrite-studio' and Path(value.get('workspace','')).resolve()==ROOT
    except Exception: return False


def state():
    try: return json.loads(STATE.read_text('utf-8'))
    except Exception: return {}


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
                req=urllib.request.Request(f'http://127.0.0.1:{previous["port"]}/api/shutdown',data=b'{}',headers={'X-Studio-Request':'1','X-Stop-Token':previous['token'],'Content-Type':'application/json'},method='POST')
                with urllib.request.urlopen(req,timeout=5): pass
            if '--no-browser' not in sys.argv: message('工作台已停止。文章和设置仍保存在本机。')
            return
        if previous.get('port') and health(previous['port']):
            if '--no-browser' not in sys.argv: webbrowser.open(f'http://127.0.0.1:{previous["port"]}')
            return
        python=ROOT/'.venv/Scripts/python.exe'
        log=DATA/'setup.log'
        env=dict(os.environ,PYTHONUTF8='1',PYTHONIOENCODING='utf-8',WEWRITE_HOME=str(DATA/'wewrite'),WEWRITE_STUDIO_DATA=str(DATA))
        if not python.exists():
            import venv
            venv.EnvBuilder(with_pip=True).create(ROOT/'.venv')
        with log.open('a',encoding='utf-8') as handle:
            check=subprocess.run([str(python),'-c','import fastapi,uvicorn,httpx,bleach,tinycss2,wewrite,pypdf,docx,playwright,bibtexparser;from backend.app import app'],cwd=ROOT,env=env,stdout=handle,stderr=handle,creationflags=subprocess.CREATE_NO_WINDOW)
            if check.returncode:
                result=subprocess.run([str(python),'-m','pip','install','-r','requirements-lock.txt'],cwd=ROOT,env=env,stdout=handle,stderr=handle,creationflags=subprocess.CREATE_NO_WINDOW)
                if result.returncode: raise RuntimeError('首次安装依赖未完成。请检查网络后重新启动。详细记录：data/setup.log')
        if not (ROOT/'dist/index.html').exists(): raise RuntimeError('缺少预构建界面 dist。请重新解压完整工作台，或按开发说明构建。')
        port=None
        for candidate in range(8765,8865):
            with socket.socket() as test:
                try: test.bind(('127.0.0.1',candidate));port=candidate;break
                except OSError: continue
        if port is None: raise RuntimeError('没有可用的本地端口，请关闭不用的本地服务后再试')
        token=secrets.token_urlsafe(32);env['STUDIO_STOP_TOKEN']=token
        with (DATA/'server.log').open('a',encoding='utf-8') as handle:
            process=subprocess.Popen([str(python),'-m','uvicorn','backend.app:app','--host','127.0.0.1','--port',str(port),'--no-access-log'],cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=handle,stderr=handle,creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(100):
            if health(port): break
            if process.poll() is not None: raise RuntimeError('后台服务没有启动成功。详细记录：data/server.log')
            time.sleep(.2)
        else:
            process.terminate()
            raise RuntimeError('服务启动超时，请重新启动工作台。详细记录：data/server.log')
        STATE.write_text(json.dumps(dict(pid=process.pid,port=port,token=token,workspace=str(ROOT))),encoding='utf-8')
        if '--no-browser' not in sys.argv: webbrowser.open(f'http://127.0.0.1:{port}')
    finally:
        ctypes.windll.kernel32.ReleaseMutex(mutex)
        ctypes.windll.kernel32.CloseHandle(mutex)


if __name__=='__main__':
    try: main()
    except Exception as exc:
        if '--no-browser' in sys.argv: raise
        message(str(exc),True)
