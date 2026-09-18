"""Public URL validation, including independently checked local-proxy fake DNS."""
import asyncio
import ipaddress
import socket
import time
import urllib.request
from urllib.parse import urlsplit
import httpx

FAKE_NET=ipaddress.ip_network('198.18.0.0/15')
CACHE={}
PENDING={}
DNS_LIMIT=asyncio.Semaphore(4)


async def public_url(url):
    try: host=urlsplit(url).hostname
    except ValueError: return False
    # Validate each URL's scheme/port/credentials even when host lookups coalesce.
    try:
        u=urlsplit(url)
        if u.scheme not in ('http','https') or not host or u.username or u.password or (u.port or 443) not in (80,443): return False
    except ValueError: return False
    if host in PENDING: return await asyncio.shield(PENDING[host])
    task=asyncio.create_task(check(url));PENDING[host]=task
    task.add_done_callback(lambda _:PENDING.pop(host,None))
    return await asyncio.shield(task)


async def check(url):
    try:
        u=urlsplit(url);host=u.hostname;port=u.port or (443 if u.scheme=='https' else 80)
        if u.scheme not in ('http','https') or not host or u.username or u.password: return False
        if port not in (80,443): return False
        try: return ipaddress.ip_address(host).is_global
        except ValueError: pass
        if host=='localhost' or host.endswith(('.localhost','.local','.internal')): return False
        cached=CACHE.get(host)
        if cached and cached[0]>time.monotonic(): return cached[1]
        answers=await asyncio.to_thread(socket.getaddrinfo,host,port)
        ips={ipaddress.ip_address(r[4][0]) for r in answers}
        valid=bool(ips) and all(ip.is_global for ip in ips)
        if not valid and ips and all(ip in FAKE_NET for ip in ips):
            # Only the reserved fake-DNS pool of an explicitly configured local proxy
            # is eligible. Literal private IPs and ordinary private DNS never are.
            proxies=urllib.request.getproxies()
            local_proxy=any(urlsplit(v).hostname in ('127.0.0.1','localhost','::1') for k,v in proxies.items() if k in ('http','https'))
            if local_proxy:
                async with DNS_LIMIT:
                    async with httpx.AsyncClient(timeout=8) as client:
                        records=[]
                        for kind in ('A','AAAA'):
                            r=await client.get('https://cloudflare-dns.com/dns-query',params={'name':host,'type':kind},headers={'accept':'application/dns-json'})
                            r.raise_for_status();d=r.json()
                            if d.get('Status')!=0: return False
                            records.extend(ipaddress.ip_address(x['data']) for x in d.get('Answer',[]) if x.get('type') in (1,28))
                valid=bool(records) and all(ip.is_global for ip in records)
        CACHE[host]=(time.monotonic()+30,valid)
        return valid
    except (OSError,ValueError,httpx.HTTPError): return False
