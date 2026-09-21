import base64
import ctypes
import os
from ctypes import wintypes
from urllib.parse import urlsplit
from . import store


class Blob(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('data',ctypes.POINTER(ctypes.c_byte))]


def crypt(value: bytes, decrypt=False):
    if os.name != 'nt':
        raise ValueError('凭证加密需要 Windows 当前用户环境')
    buffer=ctypes.create_string_buffer(value)
    incoming=Blob(len(value),ctypes.cast(buffer,ctypes.POINTER(ctypes.c_byte)))
    outgoing=Blob()
    fn=ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    args=[ctypes.byref(incoming),None,None,None,None,1,ctypes.byref(outgoing)]
    if not fn(*args): raise ValueError('无法读取本机凭证，请重新填写 Key')
    try: return ctypes.string_at(outgoing.data,outgoing.size)
    finally: ctypes.windll.kernel32.LocalFree(outgoing.data)


def save_key(id, key):
    if key is None: return
    store.put_secret(id,encode_key(key))


def encode_key(key):
    return base64.b64encode(crypt(key.encode())).decode() if key else None


def key(id):
    value=store.get_secret(id)
    return crypt(base64.b64decode(value),True).decode() if value else ''


def validate_base(url):
    u=urlsplit(url)
    if u.scheme not in ('http','https') or not u.hostname or u.username or u.password or u.query or u.fragment:
        raise ValueError('服务地址应为有效的 http(s) 地址，不含凭证、查询参数或片段')
    if u.scheme=='http' and u.hostname not in ('127.0.0.1','localhost','::1'):
        raise ValueError('远程服务地址需要使用 HTTPS')
    return url.rstrip('/')
