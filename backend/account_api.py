"""Local account controls, using the existing task and upload infrastructure."""
from fastapi import APIRouter, UploadFile, File, Form, Query
from . import account_memory as memory, store

router = APIRouter(prefix='/api')


@router.get('/account')
def account():
    value = memory.get()
    return dict(value, trends=memory.trends(value), jobs=store.jobs('__account__'))


@router.patch('/account/profile')
def profile(value: dict):
    checked = memory.Profile.model_validate(value.get('profile', {})).model_dump()
    return memory.change(value['revision'], lambda v: v.update(profile=checked), '修改账号定位')


@router.post('/account/undo')
def undo(value: dict): return memory.undo(value['revision'])


@router.get('/account/history')
def history(query: str = '', column: str = '', page: int = Query(1, ge=1), page_size: int = Query(30, ge=1, le=100)):
    return memory.history(query, column, page, page_size)


@router.get('/articles/{id}/account-uses')
def uses(id: str):
    a = store.get_article(id)
    return dict(uses=memory.uses(id), pairs=memory.pairs(a), revision=memory.get()['revision'])


@router.post('/account/jobs')
async def start(value: dict): return memory.start(value.get('kind'), value)


@router.post('/account/import')
async def upload(file: UploadFile = File(), revision: int = Form(), kind: str = Form(), column: str = Form(''), title: str = Form(''), user_authored: bool = Form(False)):
    from pathlib import Path
    blob = await file.read(16*1024*1024+1)
    if len(blob) > 16*1024*1024: raise ValueError('文件超过16MB')
    if kind not in ('example', 'metrics_csv'): raise ValueError('未知导入类型')
    return memory.start(kind, dict(revision=revision, column=column, title=title, user_authored=user_authored, filename=Path(file.filename or '').name), blob)


@router.post('/account/metrics')
def metrics(value: dict): return memory.add_metrics(value['revision'], value.get('rows', []))


@router.post('/account/{collection}/{id}')
def item(collection: str, id: str, value: dict):
    return memory.item_action(value['revision'], collection, id, value.get('action'), value.get('patch'))
