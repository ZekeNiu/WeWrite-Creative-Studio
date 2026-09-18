import json
import os
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from .models import Brief, Layout, VisualSettings, STAGES

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get('WEWRITE_STUDIO_DATA', ROOT / 'data')).resolve()
LOCK = threading.RLock()


def now():
    return datetime.now(timezone.utc).isoformat()


def uid():
    return uuid.uuid4().hex


def encode(value):
    return json.dumps(value, ensure_ascii=False)


@contextmanager
def connection():
    DATA.mkdir(parents=True, exist_ok=True)
    with LOCK:
        db = sqlite3.connect(DATA / 'studio.sqlite', timeout=15)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()


def init():
    with connection() as db:
        db.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS articles(id TEXT PRIMARY KEY, data TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS versions(id TEXT PRIMARY KEY, article_id TEXT, created TEXT, label TEXT, data TEXT);
        CREATE INDEX IF NOT EXISTS versions_article ON versions(article_id, created);
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, article_id TEXT, status TEXT, data TEXT);
        CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT, job_id TEXT, data TEXT);
        CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY, data TEXT);
        CREATE TABLE IF NOT EXISTS usage(id TEXT PRIMARY KEY, article_id TEXT, data TEXT);
        CREATE TABLE IF NOT EXISTS secrets(id TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS research_cache(id TEXT PRIMARY KEY, expires REAL, data TEXT);
        CREATE TABLE IF NOT EXISTS capabilities(id TEXT PRIMARY KEY, data TEXT);
        ''')
        for row in db.execute("SELECT * FROM jobs WHERE status IN ('running','queued')").fetchall():
            j = json.loads(row['data'])
            j.update(status='interrupted', message='上次运行中断，已保留内容。可从当前环节重新开始。', ended=now())
            db.execute('UPDATE jobs SET status=?,data=? WHERE id=?', ('interrupted', encode(j), row['id']))


def get_article(id):
    with connection() as db:
        row = db.execute('SELECT data FROM articles WHERE id=?', (id,)).fetchone()
        if not row:
            raise KeyError('找不到这篇文章')
        from .flow_state import present
        return present(json.loads(row['data']))


def list_articles():
    with connection() as db:
        data = [json.loads(r['data']) for r in db.execute('SELECT data FROM articles')]
    return sorted([{k: a[k] for k in ('id','title','revision','updated','brief','current_stage','stages')} for a in data if not a.get('diagnostic')], key=lambda a: a['updated'], reverse=True)


def create_article(brief=None, auto=None, diagnostic=False):
    brief = Brief.model_validate(brief or {}).model_dump()
    a = dict(id=uid(), title=brief['topic'] or '未命名文章', revision=0, created=now(), updated=now(),
             brief=brief, current_stage='topic', stages={s:'idle' for s in STAGES},
             auto={s:bool((auto or {}).get(s,False)) for s in STAGES}, topics=[], sources=[], evidence={},
             outline={}, content='', review={}, suggestions=[], visual=VisualSettings().model_dump(),
             image_plans=[], images=[], layout=Layout().model_dump(), layout_advice='')
    if brief['topic']:
        a['stages']['topic']='done'; a['current_stage']='sources'
    if diagnostic: a['diagnostic']=True
    with connection() as db:
        db.execute('INSERT INTO articles VALUES(?,?)',(a['id'],encode(a)))
    from .flow_state import present
    return present(a)


class Conflict(Exception):
    pass


def save_article(id, expected_revision, mutate, label, invalidate=None):
    with connection() as db:
        row=db.execute('SELECT data FROM articles WHERE id=?',(id,)).fetchone()
        if not row: raise KeyError('文章不存在')
        a=json.loads(row['data'])
        if a['revision'] != expected_revision:
            raise Conflict('文章已有更新，为避免覆盖，未应用本次修改。请先查看最新版本。')
        db.execute('INSERT INTO versions VALUES(?,?,?,?,?)',(uid(),id,now(),label,encode(a)))
        from .flow_state import material_sources
        previous_sources=encode(material_sources(a))
        old_source_ids={s['id'] for s in a['sources']}
        previous_research=encode(a.get('research'))
        previous_brief=encode([a['brief'],a['title']])
        previous_content=a['content']
        mutate(a)
        for source in a['sources']:
            if source['id'] not in old_source_ids and a.get('pending_issue_attachments'):
                source['issue_ids']=list(a['pending_issue_attachments'])
        if {s['id'] for s in a['sources']}-old_source_ids: a.pop('pending_issue_attachments',None)
        if a.get('research') and encode(a['research'])==previous_research:
            if (encode(material_sources(a))!=previous_sources or encode([a['brief'],a['title']])!=previous_brief
                    or (a['research'].get('stage')=='review' and a['content']!=previous_content)):
                a['research']['stale']=True
        if encode(material_sources(a))!=previous_sources:
            a['current_stage']='sources'
            if a['evidence'] and a['stages']['sources']!='needs_input': a['stages']['sources']='stale'
        if invalidate is not None:
            start = -1 if invalidate == 'setup' else STAGES.index(invalidate)
            for s in STAGES[start+1:]:
                if a['stages'][s] in ('done','needs_input','stale'):
                    a['stages'][s]='stale'
        a['revision']+=1; a['updated']=now()
        db.execute('UPDATE articles SET data=? WHERE id=?',(encode(a),id))
        from .flow_state import present
        return present(a)


def versions(id):
    with connection() as db:
        return [dict(r) for r in db.execute('SELECT id,created,label FROM versions WHERE article_id=? ORDER BY created DESC LIMIT 100',(id,))]


def restore(id, version, revision):
    with connection() as db:
        row=db.execute('SELECT data FROM versions WHERE id=? AND article_id=?',(version,id)).fetchone()
        if not row: raise KeyError('历史版本不存在')
        old=json.loads(row['data'])
    def change(a):
        a.update({k:v for k,v in old.items() if k not in ('id','revision','created','updated')})
    return save_article(id,revision,change,'恢复历史版本')


def get_settings():
    with connection() as db:
        row=db.execute('SELECT data FROM settings WHERE id=1').fetchone()
        return json.loads(row[0]) if row else None


def set_settings(value):
    with connection() as db:
        db.execute('INSERT OR REPLACE INTO settings VALUES(1,?)',(encode(value),))


def put_secret(id, value):
    with connection() as db:
        if value is None: db.execute('DELETE FROM secrets WHERE id=?',(id,))
        else: db.execute('INSERT OR REPLACE INTO secrets VALUES(?,?)',(id,value))


def get_secret(id):
    with connection() as db:
        row=db.execute('SELECT value FROM secrets WHERE id=?',(id,)).fetchone()
        return row[0] if row else None


def create_job(article_id, request):
    with connection() as db:
        if db.execute("SELECT 1 FROM jobs WHERE article_id=? AND status IN ('running','queued')",(article_id,)).fetchone():
            raise Conflict('这篇文章已有任务正在运行，请等待完成或先停止。')
        j=dict(id=uid(),article_id=article_id,status='queued',created=now(),ended=None,message='准备开始',
               stage=request['stage'],request=request,result=None,partial='')
        db.execute('INSERT INTO jobs VALUES(?,?,?,?)',(j['id'],article_id,j['status'],encode(j)))
    return j


def job(id):
    with connection() as db:
        r=db.execute('SELECT data FROM jobs WHERE id=?',(id,)).fetchone()
        if not r: raise KeyError('任务不存在')
        return json.loads(r[0])


def update_job(id, **patch):
    with connection() as db:
        j=job(id); j.update(patch)
        db.execute('UPDATE jobs SET status=?,data=? WHERE id=?',(j['status'],encode(j),id))
    return j


def jobs(article_id):
    with connection() as db:
        return [json.loads(r[0]) for r in db.execute('SELECT data FROM jobs WHERE article_id=? ORDER BY rowid DESC LIMIT 20',(article_id,))]


def event(job_id, kind, **payload):
    with connection() as db:
        db.execute('INSERT INTO events(job_id,data) VALUES(?,?)',(job_id,encode(dict(kind=kind,at=now(),**payload))))


def events(job_id, after):
    with connection() as db:
        return [dict(seq=r['seq'],**json.loads(r['data'])) for r in db.execute('SELECT seq,data FROM events WHERE job_id=? AND seq>? ORDER BY seq LIMIT 100',(job_id,after))]


def add_usage(article_id, **value):
    row=dict(id=uid(),at=now(),**value)
    with connection() as db:
        db.execute('INSERT INTO usage VALUES(?,?,?)',(row['id'],article_id,encode(row)))
    return row


def usage(article_id):
    with connection() as db:
        return [json.loads(r[0]) for r in db.execute('SELECT data FROM usage WHERE article_id=? ORDER BY rowid DESC',(article_id,))]


def update_usage(id,**changes):
    with connection() as db:
        row=db.execute('SELECT data FROM usage WHERE id=?',(id,)).fetchone()
        if row:
            value=json.loads(row[0]);value.update(changes)
            db.execute('UPDATE usage SET data=? WHERE id=?',(encode(value),id))


def article_dir(id):
    get_article(id)
    p=DATA/'articles'/id
    p.mkdir(parents=True,exist_ok=True)
    return p


def cache_get(key):
    import time
    with connection() as db:
        r=db.execute('SELECT data FROM research_cache WHERE id=? AND expires>?',(key,time.time())).fetchone()
        return json.loads(r[0]) if r else None


def cache_put(key,value,ttl=86400):
    import time
    with connection() as db:
        db.execute('INSERT OR REPLACE INTO research_cache VALUES(?,?,?)',(key,time.time()+ttl,encode(value)))


def capability(key,value=None):
    with connection() as db:
        if value is not None:
            db.execute('INSERT OR REPLACE INTO capabilities VALUES(?,?)',(key,encode(dict(value,at=now()))))
        r=db.execute('SELECT data FROM capabilities WHERE id=?',(key,)).fetchone()
        return json.loads(r[0]) if r else {'status':'untested'}


def latest_search_check(active=False):
    with connection() as db:
        query="SELECT data FROM jobs"+(" WHERE status IN ('running','queued')" if active else '')+" ORDER BY rowid DESC"
        for row in db.execute(query):
            j=json.loads(row[0])
            if j.get('request',{}).get('kind')=='search_check': return j
    return None
