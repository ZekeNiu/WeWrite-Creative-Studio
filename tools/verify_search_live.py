"""Explicit, real end-to-end acceptance against the running local workbench.

Uses saved user configuration and may incur text/search charges. No mocks.
"""
import json
import sys
import time
from pathlib import Path
Path('output/diagnostics').mkdir(parents=True,exist_ok=True)
import httpx

sys.stdout.reconfigure(encoding='utf-8')
output=Path('output/diagnostics/search-check-real.json')
output.parent.mkdir(exist_ok=True)
records=json.loads(output.read_text('utf-8')) if output.exists() else []
with httpx.Client(base_url='http://127.0.0.1:8765',trust_env=False,timeout=30,headers={'X-Studio-Request':'1'}) as client:
    for column,without_tavily in [('AI',True),('运动科学',False),('运动科学',True),('运动健康',True)]:
        response=client.post('/api/search/check',json={'column':column,'without_tavily':without_tavily})
        response.raise_for_status()
        job=response.json();previous=''
        deadline=time.monotonic()+1200
        while job['status'] in ('queued','running') and time.monotonic()<deadline:
            time.sleep(3)
            response=client.get('/api/search/check/'+job['id']);response.raise_for_status();job=response.json()
            if job['message']!=previous:
                print(column, '无 Tavily' if without_tavily else '现有配置', job['message'],flush=True)
                previous=job['message']
        if job['status'] in ('queued','running'):
            client.post('/api/jobs/'+job['id']+'/cancel')
            raise SystemExit('Acceptance deadline reached; task stopped. No automatic retry.')
        records.append(job)
        output.write_text(json.dumps(records,ensure_ascii=False,indent=2),'utf-8')
        print('RESULT',column,without_tavily,job.get('passed'),job.get('steps'),flush=True)
