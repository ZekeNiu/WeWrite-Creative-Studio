"""Exercise the shipped launcher using only this workspace's process and state."""
import json
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def launch(*args):
    subprocess.run([sys.executable,str(ROOT/'launcher.pyw'),'--no-browser',*args],cwd=ROOT,check=True)


def state(): return json.loads((ROOT/'data/server.json').read_text('utf-8'))


def alive(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health',timeout=.7) as r: return json.load(r).get('app')=='wewrite-studio'
    except Exception: return False


launch();first=state();assert alive(first['port'])
launch();second=state();assert first['pid']==second['pid']
launch('--stop')
for _ in range(30):
    if not alive(first['port']):break
    time.sleep(.1)
assert not alive(first['port'])
with socket.socket() as occupied:
    occupied.bind(('127.0.0.1',8765));occupied.listen(1)
    launch();third=state();assert third['port']!=8765 and alive(third['port'])
    launch('--stop')
    for _ in range(30):
        if not alive(third['port']):break
        time.sleep(.1)
launch();final=state();assert alive(final['port'])
report={'initial_launch':True,'repeated_launch_reuses_process':True,'stop_preserves_data':True,'occupied_port_fallback':True,'restart':True,'final_port':final['port']}
dest=ROOT/'output/launcher-check.json';dest.parent.mkdir(exist_ok=True);dest.write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report))
