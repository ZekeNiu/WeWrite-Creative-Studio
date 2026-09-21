"""All backend checks use temporary storage and explicitly mocked HTTP only."""
import httpx
import pytest
from backend import store


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path)
    monkeypatch.setenv('WEWRITE_HOME',str(tmp_path/'wewrite'))
    store.init()
    send=httpx.AsyncClient.send
    async def offline_send(self,request,*args,**kwargs):
        if not isinstance(self._transport,(httpx.MockTransport,httpx.ASGITransport)):
            raise httpx.ConnectError('External HTTP is disabled in automated tests',request=request)
        return await send(self,request,*args,**kwargs)
    monkeypatch.setattr(httpx.AsyncClient,'send',offline_send)
