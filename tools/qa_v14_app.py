"""Isolated simulated UI acceptance server; never imported by the desktop launcher."""
from pathlib import Path
from backend import store
store.DATA=Path('output/test-workspaces/qa-v14').resolve()
store.init()
from tools.qa_research_app import app
from backend import providers,public_network
from backend.models import Settings


async def public(url): return url.startswith('https://fixture.example.org/')
public_network.public_url=public
if not store.get_settings():
    providers.save_settings(Settings.model_validate(dict(
        services=[dict(id='qa-'+str(i),name=name,model=model,protocol='responses',key='offline-fixture-key')
                  for i,(name,model) in enumerate([('模拟 Claude','claude-fixture'),('模拟 Gemini','gemini-fixture'),
                  ('模拟 GPT','gpt-fixture'),('模拟图片服务','image-fixture'),('模拟 DeepSeek','deepseek-fixture')])],
        default_service='qa-0',routes={'image':{'service_id':'qa-3'},'review':{'service_id':'qa-2','model':'review-override'}},
        search={'native_service_id':'qa-1','native_protocol':'gemini','academic_enabled':False},
    )))
if not store.list_articles():
    store.create_article({'topic':'界面验收：证据、素材与归档'})
