import asyncio
import importlib.machinery
import importlib.util
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from backend import store
from backend.app import app,APP_VERSION,shutdown
from tests.test_studio import client,H,new


@pytest.fixture
def launcher(tmp_path,monkeypatch):
    loader=importlib.machinery.SourceFileLoader('studio_launcher',str(Path(__file__).resolve().parents[1]/'launcher.pyw'))
    spec=importlib.util.spec_from_loader(loader.name,loader);module=importlib.util.module_from_spec(spec);loader.exec_module(module)
    monkeypatch.setattr(module,'ROOT',tmp_path);monkeypatch.setattr(module,'DATA',tmp_path/'data')
    (tmp_path/'package.json').write_text(json.dumps({'version':'1.4.6'}))
    (tmp_path/'data').mkdir()
    return module


def test_launch_opens_fresh_versioned_tab_without_closing_old_tab(launcher,monkeypatch):
    from urllib.parse import urlparse,parse_qs
    opened=[]
    monkeypatch.setattr(launcher.webbrowser,'open_new_tab',opened.append)
    launcher.open_workbench(8765);launcher.open_workbench(8765)
    assert len(opened)==2 and opened[0]!=opened[1]
    for url in opened:
        parts=urlparse(url);query=parse_qs(parts.query)
        assert parts.netloc=='127.0.0.1:8765'
        assert query['v']==['1.4.6'] and query['opened'][0].isdigit()


@pytest.mark.parametrize('version,reused',[('1.4.6',True),('1.4.4',False),('1.4.5',False)])
def test_launcher_reuses_only_current_version(launcher,monkeypatch,version,reused):
    stopped=[]
    monkeypatch.setattr(launcher,'server_info',lambda port:{'version':version})
    monkeypatch.setattr(launcher,'active_jobs',lambda:False)
    monkeypatch.setattr(launcher,'stop_server',lambda state,restart=False:stopped.append(restart))
    assert launcher.reuse_existing({'port':8765})==reused
    assert stopped==([] if reused else [True])


def test_launcher_will_not_interrupt_generation(launcher,monkeypatch):
    monkeypatch.setattr(launcher,'server_info',lambda port:{'version':'1.4.4'})
    monkeypatch.setattr(launcher,'active_jobs',lambda:True)
    monkeypatch.setattr(launcher,'stop_server',lambda *a,**k:pytest.fail('Must not stop active work'))
    with pytest.raises(RuntimeError,match='生成任务运行'):launcher.reuse_existing({'port':8765})


def test_launcher_does_not_stop_another_workspace(launcher,monkeypatch):
    class Response:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self):return json.dumps({'app':'wewrite-studio','workspace':str(launcher.ROOT/'other'),'version':'1.4.4'}).encode()
    monkeypatch.setattr(launcher.urllib.request,'urlopen',lambda *a,**k:Response())
    monkeypatch.setattr(launcher,'stop_server',lambda *a,**k:pytest.fail('Must not stop another workspace'))
    assert not launcher.health(8765)
    assert not launcher.reuse_existing({'port':8765})


@pytest.mark.parametrize('status,active',[('running',True),('queued',True),('needs_input',False),('completed',False)])
def test_launcher_reads_active_jobs_without_changing_database(launcher,status,active):
    path=launcher.DATA/'studio.sqlite'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE jobs(status TEXT)');db.execute('INSERT INTO jobs VALUES(?)',(status,))
    before=path.read_bytes()
    assert launcher.active_jobs()==active
    assert path.read_bytes()==before


def test_health_reports_loaded_and_available_versions(client,monkeypatch,tmp_path):
    (tmp_path/'package.json').write_text(json.dumps({'version':'9.9.9'}))
    monkeypatch.setattr(store,'ROOT',tmp_path)
    response=client.get('/api/health')
    assert response.json()['version']==APP_VERSION
    assert response.json()['available_version']=='9.9.9'
    assert response.headers['cache-control']=='no-store'


def test_entry_html_is_not_cached(client):
    for url in ('/','/index.html'):
        response=client.get(url)
        assert response.status_code==200 and response.headers['cache-control']=='no-store'


def test_restart_refused_if_new_job_started(client,monkeypatch):
    monkeypatch.setenv('STUDIO_STOP_TOKEN','test-token')
    a=new(client);store.create_job(a['id'],{'stage':'topic','revision':a['revision']})
    response=client.post('/api/shutdown',headers={**H,'X-Stop-Token':'test-token'},json={'restart':True})
    assert response.status_code==400 and '生成任务运行' in response.json()['detail']
    assert not getattr(app.state,'restarting',False)


def test_restart_rejects_new_writes_but_keeps_reads(client,monkeypatch):
    monkeypatch.setattr(app.state,'restarting',False,raising=False)
    monkeypatch.setenv('STUDIO_STOP_TOKEN','test-token')
    async def body():return {'restart':True}
    # Close the delayed exit coroutine without ever stopping the test process.
    with monkeypatch.context() as m:
        m.setattr(asyncio,'create_task',lambda coro:coro.close())
        asyncio.run(shutdown(SimpleNamespace(headers={'x-stop-token':'test-token'},json=body)))
    assert client.get('/api/health').status_code==200
    assert client.post('/api/articles',headers=H,json={}).status_code==409
