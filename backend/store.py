import copy
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
    if (DATA/'studio.sqlite').exists():
        from . import snapshots
        with LOCK: snapshots.prepare(DATA,'quality-account-v1')
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
            if j.get('external_inflight'):
                j.update(external_inflight=False,message='微信动作曾被中断，远端结果可能已产生；请查看回执并核对草稿箱，勿直接重复推送。')
                home=Path(j.get('external_home','')).resolve()
                receipt=home/'external-receipt.json'
                if home.is_relative_to((DATA/'native').resolve()) and receipt.is_file():
                    try:
                        record=json.loads(receipt.read_text('utf-8'));j['external_receipt']=record
                        if record.get('result'):
                            j['result']=record['result'];j['message']='已恢复微信回执；请核对远端成果，本地正文没有自动覆盖。'
                    except (ValueError,OSError):pass
            db.execute('UPDATE jobs SET status=?,data=? WHERE id=?', ('interrupted', encode(j), row['id']))


    from . import account_memory
    account_memory.init()


def get_article(id,include_trash=False):
    with connection() as db:
        row = db.execute('SELECT data FROM articles WHERE id=?', (id,)).fetchone()
        if not row:
            raise KeyError('找不到这篇文章')
        from .flow_state import present
        from .review_state import legacy
        a=json.loads(row['data'])
        if a.get('trashed_at') and not include_trash: raise Conflict('这篇文章已在回收站，请恢复后继续')
        return present(legacy(a, db))


def list_articles(state='active', page=None, page_size=20, query=''):
    fields=('title','revision','updated','brief','current_stage','stages','trashed_at')
    select='id,'+','.join(f"json_extract(data,'$.{k}') AS {k}" for k in fields)+",json_extract(data,'$.content') AS word_content"
    where="coalesce(json_extract(data,'$.diagnostic'),0)=0 AND (json_extract(data,'$.trashed_at') IS NOT NULL)=?"
    params=[state=='trash']
    if query.strip():
        where+=" AND (instr(lower(json_extract(data,'$.title')),lower(?))>0 OR instr(lower(json_extract(data,'$.brief.topic')),lower(?))>0)"
        params += [query.strip(),query.strip()]
    with connection() as db:
        total=db.execute('SELECT count(*) FROM articles WHERE '+where,params).fetchone()[0]
        sql='SELECT '+select+' FROM articles WHERE '+where+" ORDER BY json_extract(data,'$.updated') DESC,id DESC"
        if page is not None: sql+=' LIMIT ? OFFSET ?';params += [page_size,(page-1)*page_size]
        rows=[dict(r) for r in db.execute(sql,params)]
        for row in rows:
            latest=db.execute('SELECT data FROM jobs WHERE article_id=? ORDER BY rowid DESC LIMIT 1',(row['id'],)).fetchone()
            if latest:
                j=json.loads(latest[0]);row['latest_job']={k:j.get(k) for k in ('id','stage','status','message')}
    for row in rows:
        for key in ('brief','stages'):row[key]=json.loads(row[key])
        row['word_count']=len(''.join((row.pop('word_content') or '').split()))
    return rows if page is None else dict(items=rows,total=total,page=page,page_size=page_size)


def trash_article(id,revision,restore=False):
    with LOCK:
        if any(j['status'] in ('queued','running') for j in jobs(id)):raise Conflict('文章仍有活动任务，请完成或停止任务后再操作')
        return save_article(id,revision,lambda a:a.update(trashed_at=None if restore else now()),'恢复回收站文章' if restore else '移入回收站',allow_trash=True)


def purge_article(id,revision):
    import shutil
    from . import outputs
    with connection() as db:
        a=get_article(id,include_trash=True)
        if a['revision']!=revision:raise Conflict('文章已改变，请刷新回收站后重试')
        if not a.get('trashed_at'):raise ValueError('请先将文章移入回收站')
        if db.execute("SELECT 1 FROM jobs WHERE article_id=? AND status IN ('queued','running')",(id,)).fetchone():raise Conflict('文章仍有活动任务，不能删除')
        for parent in (DATA/'articles',outputs.root()/'articles'):
            target=(parent/id).resolve();base=parent.resolve()
            if target.parent!=base or target==base:raise ValueError('文章文件路径无效')
            if target.exists():shutil.rmtree(target)
        db.execute('DELETE FROM events WHERE job_id IN (SELECT id FROM jobs WHERE article_id=?)',(id,))
        for table in ('versions','jobs','usage'):db.execute(f'DELETE FROM {table} WHERE article_id=?',(id,))
        db.execute('DELETE FROM articles WHERE id=?',(id,))
        db.execute('DELETE FROM article_index WHERE article_id=?',(id,))
        db.execute('DELETE FROM account_uses WHERE article_id=?',(id,))
    return {'deleted':True}


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
        from .account_memory import index_article
        index_article(db,a)
    from .flow_state import present
    return present(a)


class Conflict(Exception):
    pass


def save_article(id, expected_revision, mutate, label, invalidate=None, review_action=False,allow_trash=False,account_use=None):
    from . import snapshots
    with LOCK:
        snapshots.prepare(DATA)
        snapshots.prepare(DATA,'quality-evidence-v1')
        snapshots.prepare(DATA,'quality-editorial-v1')
    with connection() as db:
        row=db.execute('SELECT data FROM articles WHERE id=?',(id,)).fetchone()
        from .account_memory import guard,index_article
        guard(account_use)
        if not row: raise KeyError('文章不存在')
        a=json.loads(row['data'])
        if a.get('trashed_at') and not allow_trash:raise Conflict('这篇文章已在回收站，请恢复后继续')
        if a['revision'] != expected_revision:
            raise Conflict('文章已有更新，为避免覆盖，未应用本次修改。请先查看最新版本。')
        db.execute('INSERT INTO versions VALUES(?,?,?,?,?)',(uid(),id,now(),label,snapshots.encode(a)))
        from . import evidence_state
        before=copy.deepcopy(a)
        # Upgrade a legacy decision only when this article is explicitly edited.
        from .flow_state import issues,legacy_signature,signature
        for issue in issues(before):
            decision=a.get('research_decisions',{}).get(issue['id'],{})
            if not decision.get('dependency_key') and decision.get('material_key') in (legacy_signature(before),signature(before)):
                decision['dependency_key']=evidence_state.dependency(before,issue)
        previous_research=encode(a.get('research'))
        mutate(a)
        # Attachment associations are part of each upload, never a sticky article flag.
        a.pop('pending_issue_attachments',None)
        material_change=False
        if encode(a.get('research'))==previous_research and encode(a.get('evidence'))==encode(before.get('evidence')):
            material_change=evidence_state.changed(a,before)
        if invalidate=='setup':
            # Expression settings affect writing, not fact verification or its decisions.
            invalidate='topic' if evidence_state.objective(a)!=evidence_state.objective(before) else 'outline'
        if invalidate=='sources' and not material_change and encode(a.get('evidence'))==encode(before.get('evidence')):
            invalidate=None
        if invalidate is not None:
            start = -1 if invalidate == 'setup' else STAGES.index(invalidate)
            for s in STAGES[start+1:]:
                if a['stages'][s] in ('done','needs_input','stale'):
                    a['stages'][s]='stale'
        r=a.get('research',{})
        if r.get('resume_stage') and a['stages'].get('outline' if r['resume_stage']=='sources' else r['resume_stage'])=='done':
            r.pop('resume_job_id',None);r.pop('resume_stage',None)
        from . import review_state
        evidence_state.sync(a)
        if review_action: review_state.finish_action(a)
        else: review_state.present(a)
        review_state.sync_job(db,a)
        a['revision']+=1; a['updated']=now()
        db.execute('UPDATE articles SET data=? WHERE id=?',(encode(a),id))
        index_article(db,a)
        from .flow_state import present
        return present(a)


def versions(id, page=None, page_size=50):
    with connection() as db:
        rows=[dict(r) for r in db.execute('SELECT id,created,label FROM versions WHERE article_id=? ORDER BY rowid DESC LIMIT ? OFFSET ?',(id,100 if page is None else page_size,0 if page is None else (page-1)*page_size))]
        total=db.execute('SELECT count(*) FROM versions WHERE article_id=?',(id,)).fetchone()[0]
        return rows if page is None else dict(items=rows,total=total,page=page,page_size=page_size)


def restore(id, version, revision):
    from .snapshots import decode
    with connection() as db:
        row=db.execute('SELECT data FROM versions WHERE id=? AND article_id=?',(version,id)).fetchone()
        if not row: raise KeyError('历史版本不存在')
        old=decode(row['data'])
    def change(a):
        if any(j['status'] in ('queued','running') for j in jobs(id)):raise Conflict('文章仍有活动任务，不能恢复历史版本')
        identity={k:a[k] for k in ('id','revision','created','updated')}
        defaults=dict(brief=Brief().model_dump(),stages={s:'idle' for s in STAGES},auto={s:False for s in STAGES},
                      visual=VisualSettings().model_dump(),layout=Layout().model_dump(),sources=[],topics=[],evidence={},
                      outline={},content='',review={},suggestions=[],images=[],image_plans=[],layout_advice='',current_stage='topic',title='未命名文章')
        restored={**defaults,**copy.deepcopy(old),**identity}
        for key in ('brief','stages','auto','visual','layout'):restored[key]={**defaults[key],**old.get(key,{})}
        for key in ('materials_state','workflow','pending_issue_attachments'):restored.pop(key,None)
        a.clear();a.update(restored)
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
        return refresh_external(json.loads(r[0]))


def refresh_external(value):
    # A child may finish its already-sent request just after restart recovery.
    if value.get('external_home') and value['status'] in ('interrupted','cancelled'):
        home=Path(value['external_home']).resolve();path=home/'external-receipt.json'
        if home.is_relative_to((DATA/'native').resolve()) and path.is_file():
            try:
                receipt=json.loads(path.read_text('utf-8'));value['external_receipt']=receipt
                if receipt.get('result'):
                    value['result']=receipt['result'];value['message']='已恢复微信回执；请核对远端成果，本地正文没有自动覆盖。'
            except (OSError,ValueError):pass
    return value


def update_job(id, **patch):
    with connection() as db:
        j=job(id); j.update(patch)
        db.execute('UPDATE jobs SET status=?,data=? WHERE id=?',(j['status'],encode(j),id))
    return j


def jobs(article_id):
    with connection() as db:
        return [refresh_external(json.loads(r[0])) for r in db.execute('SELECT data FROM jobs WHERE article_id=? ORDER BY rowid DESC LIMIT 20',(article_id,))]


def active_job_count():
    with connection() as db:
        return db.execute("SELECT count(*) FROM jobs WHERE status IN ('queued','running')").fetchone()[0]


def event(job_id, kind, **payload):
    with connection() as db:
        db.execute('INSERT INTO events(job_id,data) VALUES(?,?)',(job_id,encode(dict(kind=kind,at=now(),**payload))))


def events(job_id, after):
    with connection() as db:
        return [dict(seq=r['seq'],**json.loads(r['data'])) for r in db.execute('SELECT seq,data FROM events WHERE job_id=? AND seq>? ORDER BY seq LIMIT 100',(job_id,after))]


def add_usage(article_id, **value):
    request_id=value.pop('_request_id',None)
    if request_id:
        return update_usage(request_id,**value)
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
            return value


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
        db.execute('DELETE FROM research_cache WHERE expires<=?',(time.time(),))
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
