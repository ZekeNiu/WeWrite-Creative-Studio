"""Plan uploads reuse placement without requiring any model call."""
import io
import pytest
from PIL import Image
from backend import store,rendering
from tests.test_studio import client,H,new,patch


def upload(client,a,plan_id='',**data):
    blob=io.BytesIO();Image.new('RGB',(32,24),'green').save(blob,'PNG')
    return client.post(f'/api/articles/{a["id"]}/images/upload',headers=H,
        data={'revision':a['revision'],'role':'article','plan_id':plan_id,**data},
        files={'file':('local.png',blob.getvalue(),'image/png')})


@pytest.mark.parametrize('role',['cover','article'])
def test_plan_upload_preserves_placement_caption_and_existing_images(client,role):
    a=new(client)
    a=upload(client,a).json()
    original=a['images'][0]
    a=patch(client,a,{'content':'## 训练方法\n\n循序渐进。\n\n## 注意事项\n\n量力而行。',
        'image_plans':[dict(id='plan-one',role=role,prompt='不应调用的生成提示',caption='自备训练图片',after_heading='训练方法')]})
    assert not a['visual']['enabled']
    previous_revision=a['revision']
    result=upload(client,a,'plan-one');assert result.status_code==200,result.text
    a=result.json();im=a['images'][-1]
    assert a['images'][0]==original
    assert (im['role'],im['caption'],im['after_heading'],im['plan_id'])==(role,'自备训练图片','训练方法','plan-one')
    assert im['selected'] and not im.get('prompt')
    assert a['revision']==previous_revision+1
    assert client.get(f'/api/articles/{a["id"]}/assets/{im["filename"]}').status_code==200
    md=rendering.markdown(a,export=True)
    if role=='article': assert md.index('## 训练方法')<md.index(im['filename'])<md.index('## 注意事项')
    else: assert md.index(im['filename'])<md.index('## 训练方法')
    assert '部分配图由 AI 生成' not in md
    with store.connection() as db: assert db.execute('SELECT count(*) FROM jobs').fetchone()[0]==0
    # The general upload controls must not reuse the previous plan's metadata.
    generic=upload(client,a).json()['images'][-1]
    assert generic['role']=='article' and generic['caption']=='' and generic['after_heading']==''
    assert not generic.get('plan_id')


def test_plan_upload_rejects_stale_revision_or_missing_plan_without_files(client):
    a=new(client)
    assert upload(client,a,'missing').status_code==400
    updated=patch(client,a,{'title':'已修改标题'})
    assert upload(client,a).status_code==409
    assert not list(store.article_dir(a['id']).glob('assets/*'))
    assert client.get('/api/articles/'+a['id']).json()['revision']==updated['revision']


def test_plan_upload_cleans_file_on_concurrent_save_conflict(client,monkeypatch):
    a=new(client)
    def conflict(*args,**kwargs): raise store.Conflict('并发修改')
    monkeypatch.setattr(store,'save_article',conflict)
    assert upload(client,a).status_code==409
    assert not list(store.article_dir(a['id']).glob('assets/*'))
