"""Isolated reader-workflow fixture; model responses and all data are synthetic."""
import json
import os
from tools.qa_reliability_app import app,store,providers,materials

base_generate=providers.generate
async def generate(service,system,prompt,emit=None):
    data=json.loads(prompt)
    if data.get('schema',{}).get('title')=='EvidenceResult':
        job=store.job(service['_job_id']);a=store.get_article(job['article_id'])
        source=next(s for s in a['sources'] if s['selected'])
        result=dict(summary='围绕家常做法，介绍备料、炒蛋和收汁三个步骤。',gaps=[],claims=[
            dict(id='Crecipe',text='先炒鸡蛋盛出，再炒番茄，最后合炒收汁',type='fact',status='supported',boundary='',source_ids=[source['id']])])
        return json.dumps(result,ensure_ascii=False),dict(status='completed',model='synthetic',input_tokens=0,output_tokens=0)
    return await base_generate(service,system,prompt,emit)
providers.generate=generate

a=store.create_article(dict(topic='如何做番茄炒蛋'))
def seed(v):
    v['sources']=[dict(materials.source('家常做法参考 '+str(i+1),'先炒鸡蛋盛出，再炒番茄，最后合炒收汁。'),id='Srecipe'+str(i)) for i in range(14)]
    v['sources'][1]['selected']=False
    v['evidence']=dict(engine='wewrite-native',summary='家常做法的准备资料',claims=[dict(id='Crecipe',text='先炒鸡蛋盛出，再炒番茄，最后合炒收汁',status='supported',type='fact',source_ids=['Srecipe0'])])
    selected=dict(id='Trecipe',title=v['title'],reader_question='怎样炒出蓬松的鸡蛋和浓稠的番茄汁？',source_ids=['Srecipe0','Srecipe1'])
    v['creative_intent']=dict(version=1,original_request=v['title'],selected=selected,adopted_plan=selected,batches=[dict(id='batch',topics=[dict(id='Told',title='青椒土豆丝的做法',source_ids=['Srecipe2'])])])
    v['research']=dict(summary='OLD_INTERNAL_AUDIT',superseded_by='previous-preparation',pending=True,issues=[dict(id='old',text='OLD_OPTIONAL_CHECK',kind='blocking',source_ids=[],status='open',claim='')])
    v['stages']['sources']='done';v['current_stage']='sources'
a=store.save_article(a['id'],a['revision'],seed,'Synthetic reader fixture')
app.state.fixture_id=a['id']

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=int(os.environ.get('QA_PORT','8978')),access_log=False)
