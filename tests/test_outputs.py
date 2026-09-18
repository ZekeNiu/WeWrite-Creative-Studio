import io
import zipfile
from pathlib import Path
from backend import store,outputs
from tests.test_studio import client,new,patch,H


def test_archive_reuses_snapshot_and_download_is_pinned(client):
    a=patch(client,new(client),{'content':'归档正文'},'write')
    url=f'/api/articles/{a["id"]}/exports'
    first=client.post(url,headers=H,json={'revision':a['revision']}).json()
    second=client.post(url,headers=H,json={'revision':a['revision']}).json()
    assert first['path']==second['path']
    folder=Path(first['path']);assert folder.is_relative_to(store.DATA)
    assert all((folder/n).exists() for n in ('文章.md','排版.html','来源清单.json','使用说明.txt'))
    a=patch(client,a,{'content':'新的正文','title':'改名后的文章'},'write')
    r=client.get(url+'/'+first['digest']+'/md');assert '归档正文' in r.text and '新的正文' not in r.text
    assert client.post(url,headers=H,json={'revision':0}).status_code==409
    third=client.post(url,headers=H,json={'revision':a['revision']}).json()
    assert third['path']!=first['path'] and folder.exists()
    z=zipfile.ZipFile(io.BytesIO(client.get(url+'/'+third['digest']+'/zip').content))
    assert z.read('文章.md')==(Path(third['path'])/'文章.md').read_bytes()


def test_names_are_windows_safe():
    assert outputs.safe_title('CON')=='_CON'
    assert outputs.safe_title(' . ')=='未命名文章'
    assert outputs.safe_title('a<>:"/\\|?*\n')=='a__________'
    assert len(outputs.safe_title('字'*200))==48


def test_archive_failure_does_not_claim_success(client,monkeypatch):
    a=patch(client,new(client),{'content':'正文'},'write')
    def denied(*args,**kwargs): raise PermissionError('blocked')
    monkeypatch.setattr(outputs.rendering,'export_zip',denied)
    r=client.post(f'/api/articles/{a["id"]}/exports',headers=H,json={'revision':a['revision']})
    assert r.status_code==400 and '归档失败' in r.json()['detail']
