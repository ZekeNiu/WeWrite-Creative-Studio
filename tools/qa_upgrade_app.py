"""Isolated visual fixture. Never loads or changes production settings."""
from pathlib import Path
from backend import store
store.DATA=Path('output/qa-upgrade-data').resolve()
store.init()
from backend.app import app
if not store.list_articles():
    a=store.create_article({'topic':'界面验收 · 引用顺序与文献表'})
    def seed(a):
        a['sources']=[dict(id=sid,title=title,text='用于界面验证的模拟材料，不能作为真实研究依据。',url='https://example.org/'+sid,kind='user',pages=[],status='user_provided',selected=True,summary='模拟材料，仅供界面验收',use='',bibliography=dict(title=title,authors=[{'family':'Smith','given':'Alex'}],document_type='J',venue='Fixture Journal',year='2025',volume='1',issue='2',pages='10-20',url='https://example.org/'+sid)) for sid,title in [('Sa','模拟文献 A'),('Sb','模拟文献 B')]]
        a['content']='## 引用验收\n\n先引用第二份资料[Sb]，随后引用第一份资料[Sa]。再次引用第二份资料[Sb]。\n\n旧稿编号[7]等待人工关联。'
        a['current_stage']='write';a['stages']['write']='done'
    store.save_article(a['id'],0,seed,'模拟界面验收')
