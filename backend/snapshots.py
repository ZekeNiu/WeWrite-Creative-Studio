"""Versioned, checksummed snapshots. Legacy JSON remains readable."""
import base64
import hashlib
import json
import sqlite3
import zlib
from contextlib import closing

FORMAT = 'zlib-json-v1'
_ready = set()


def prepare(data,version='snapshot-v1'):
    """Called under the store lock, before opening a write transaction."""
    key = (str(data.resolve()),version)
    if key in _ready: return
    folder = data / 'backups'; folder.mkdir(parents=True, exist_ok=True)
    backup = folder / ('before-'+version+'.sqlite')
    marker = folder / (version+'.json')
    try:
        if marker.exists():
            info = json.loads(marker.read_text('utf-8'))
            if hashlib.sha256(backup.read_bytes()).hexdigest() != info['sha256']:
                raise ValueError('升级前数据库副本校验失败，请保留数据并检查备份文件')
        else:
            temporary = folder / ('before-'+version+'.pending.sqlite')
            with closing(sqlite3.connect(data / 'studio.sqlite')) as source, closing(sqlite3.connect(temporary)) as target:
                source.backup(target)
                if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise ValueError('升级前数据库副本不完整')
            temporary.replace(backup)
            payload = dict(format=FORMAT, sha256=hashlib.sha256(backup.read_bytes()).hexdigest(),
                           note='仅数据库安全副本，不含附件。回退旧程序时需同时恢复此副本。')
            pending = marker.with_suffix('.pending')
            pending.write_text(json.dumps(payload, ensure_ascii=False), 'utf-8'); pending.replace(marker)
        _ready.add(key)
    except (OSError, sqlite3.Error, KeyError, json.JSONDecodeError) as exc:
        raise ValueError('无法建立或校验升级前数据库副本，本次保存未执行') from exc


def encode(value):
    raw = json.dumps(value, ensure_ascii=False).encode('utf-8')
    return json.dumps(dict(snapshot_format=FORMAT, sha256=hashlib.sha256(raw).hexdigest(),
                          payload=base64.b64encode(zlib.compress(raw)).decode('ascii')))


def decode(value):
    try:
        result = json.loads(value)
        if not isinstance(result,dict):raise ValueError('历史版本内容无效')
        if 'snapshot_format' not in result: return validate(result)
        if result['snapshot_format'] != FORMAT: raise ValueError('不支持的历史版本格式')
        raw = zlib.decompress(base64.b64decode(result['payload'], validate=True))
        if hashlib.sha256(raw).hexdigest() != result['sha256']: raise ValueError('历史版本校验失败')
        article = json.loads(raw)
        return validate(article)
    except (ValueError, KeyError, TypeError, zlib.error) as exc:
        raise ValueError('历史版本损坏或格式不受支持，当前文章未改变') from exc


def validate(article):
    if not isinstance(article,dict) or not isinstance(article.get('id'),str):raise ValueError('历史版本缺少文章身份')
    for key,kind in [('brief',dict),('outline',dict),('content',str),('sources',list),('layout',dict),('evidence',dict),('review',dict)]:
        if key in article and not isinstance(article[key],kind):raise ValueError('历史版本字段类型无效')
    return article
