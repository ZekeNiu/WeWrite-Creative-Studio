"""All backend checks use temporary storage and explicitly mocked HTTP only."""
import httpx
import pytest
from backend import store,public_network,browser_search


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path,monkeypatch):
    monkeypatch.setattr(store,'DATA',tmp_path)
    monkeypatch.setenv('WEWRITE_HOME',str(tmp_path/'wewrite'))
    store.init()
    # Keep URL validation deterministic; individual security tests override DNS.
    monkeypatch.setattr(public_network,'CACHE',{})
    monkeypatch.setattr(public_network,'PENDING',{})
    monkeypatch.setattr(public_network.socket,'getaddrinfo',lambda *args,**kwargs:[(2,1,6,'',('93.184.216.34',443))])
    async def no_browser(*args,**kwargs):
        raise ValueError('Browser fallback is disabled in unit tests; use the separate UI acceptance server')
    monkeypatch.setattr(browser_search,'launch',no_browser)
    send=httpx.AsyncClient.send
    async def offline_send(self,request,*args,**kwargs):
        if not isinstance(self._transport,(httpx.MockTransport,httpx.ASGITransport)):
            raise httpx.ConnectError('External HTTP is disabled in automated tests',request=request)
        return await send(self,request,*args,**kwargs)
    monkeypatch.setattr(httpx.AsyncClient,'send',offline_send)
