"""Derived writing purposes; author instructions and experience consent stay separate."""
import hashlib
import json


def fingerprint(a,s):
    value=[a['brief'],a['title'],{k:s.get(k) for k in ('id','title','text','status','bibliography','personal_material')}]
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def current(a,s):
    value=s.get('ai_use') or {}
    return bool(value.get('text') and value.get('input_key')==fingerprint(a,s))


def effective(a,s):
    return s.get('use','').strip() or (s['ai_use']['text'] if current(a,s) else '')


def apply(a,rows,read_ids):
    lookup={s['id']:s for s in a['sources'] if s['selected'] and s['id'] in read_ids}
    for row in rows:
        s=lookup.get(row['source_id'])
        if not s or s.get('status')=='unreadable': continue
        text=row['text'].strip()
        if not text: continue
        if s.get('status')=='metadata_only': text='仅作为文献查找线索，取得原文后再判断其支持的观点。'
        s['ai_use']=dict(text=text,input_key=fingerprint(a,s))
