"""Review rounds distinguish human decisions from the model's verdict."""
import hashlib
import json


def signature(a):
    from .flow_state import material_sources
    from .evidence_state import current_spans
    decisions={k:{f:v.get(f) for f in ('handling','wording','dependency_key','application_state')} for k,v in a.get('research_decisions',{}).items()}
    return hashlib.sha256(json.dumps([a['content'], a['title'], a['brief'], material_sources(a),current_spans(a),decisions],
                                    sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def handled(review):
    rows = review.get('issues', [])
    return bool(rows) and all(x.get('status') in ('accepted', 'rejected') for x in rows)


def present(a):
    review = a.get('review') or {}
    if review.get('reviewed_key') and review['reviewed_key'] != signature(a):
        a['stages']['review'] = 'stale'
        review.pop('completion', None)
    return a


def finish_action(a):
    review = a['review']
    review['reviewed_key'] = signature(a)
    if handled(review):
        review['completion'] = 'human'
        a['stages']['review'] = 'done'
    else:
        review.pop('completion', None)
        a['stages']['review'] = 'needs_input'


def label(a):
    if a['stages']['review'] == 'done':
        return '本轮意见已处理' if a.get('review', {}).get('completion') == 'human' else 'AI 审核通过'
    return '正文已更新，审核需要更新' if a['stages']['review'] == 'stale' else '审核尚未完成'


def sync_job(db, a):
    """Use the same transaction as the final decision; never resume a chain."""
    review = a.get('review') or {}
    jid = review.get('job_id')
    if not jid or review.get('completion') != 'human' or a['stages']['review'] != 'done':
        return
    row = db.execute('SELECT data FROM jobs WHERE id=? AND article_id=?', (jid, a['id'])).fetchone()
    if not row:
        return
    job = json.loads(row[0])
    if job.get('stage') != 'review' or job.get('status') != 'needs_input' or job.get('current_step') != 'generation':
        return
    if job.get('review_round_id') != review.get('round_id'):
        return
    job.update(status='completed', message='本轮意见已处理', review_completion='human')
    db.execute('UPDATE jobs SET status=?,data=? WHERE id=?', ('completed', json.dumps(job, ensure_ascii=False), jid))


def legacy(a, db):
    """Recover a handled old round only when its last decision snapshot matches."""
    review = a.get('review') or {}
    if review.get('round_id') or not handled(review):
        return a
    rows = db.execute("SELECT data,label FROM versions WHERE article_id=? AND label IN ('接受审核修改','拒绝审核意见') ORDER BY rowid DESC LIMIT 1", (a['id'],)).fetchall()
    if not rows:
        return a
    from .snapshots import decode
    before = decode(rows[0]['data'])
    prior = before.get('review') or {}
    pending = [x for x in prior.get('issues', []) if x.get('status') == 'pending']
    if len(pending) != 1 or prior.get('content_revision') != review.get('content_revision'):
        return a
    final = next((x for x in review['issues'] if x['id'] == pending[0]['id']), None)
    if not final:
        return a
    if final['status'] == 'accepted':
        quote = final.get('quote', '')
        if not quote or before['content'].count(quote) != 1:
            return a
        before['content'] = before['content'].replace(quote, final.get('applied_replacement', final.get('suggestion', '')), 1)
    if signature(before) != signature(a):
        return a
    review.update(completion='human', reviewed_key=signature(a))
    a['stages']['review'] = 'done'
    return a
