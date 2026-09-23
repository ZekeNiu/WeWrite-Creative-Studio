"""Child process bridge: upstream commands use one isolated home and run.

Never imported by the web process: upstream modules cache home paths at import.
"""
import contextlib
import io
import json
import os
import sys
from pathlib import Path


def main():
    packet=json.load(sys.stdin)
    home=Path(packet['home']).resolve()
    os.environ['WEWRITE_HOME']=str(home)
    os.environ['WEWRITE_RUN_ID']=packet.get('run_id','')
    os.chdir(home)
    # Import the pinned source, never a possibly stale installed distribution.
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'vendor'/'wewrite'/'src'))
    from wewrite.sources import load_sources,save_sources
    previous=load_sources()['sources'] if packet['args'][:2]==['sources','add'] else []
    from wewrite.cli import main as upstream
    output=io.StringIO()
    with contextlib.redirect_stdout(output):
        sys.argv=['wewrite',*packet['args']]
        try:upstream()
        except SystemExit as exc:
            if exc.code not in (0,None):raise
    result=output.getvalue()
    if packet['args'][:2]==['sources','add']:
        ledger=load_sources()
        merged={row['id']:row for row in previous}
        for row in ledger['sources']:
            old=next((s for s in previous if s['url']==row['url']),None)
            if old:
                claims=list(dict.fromkeys([*old.get('claims',[]),old.get('claim',''),row.get('claim','')]))
                row={**old,**row,'id':old['id'],'claims':[c for c in claims if c]}
            elif not row['id'].startswith('S'):row['id']='S'+row['id']
            merged[row['id']]=row
        ledger['sources']=list(merged.values())
        save_sources(ledger)
        result=json.dumps(ledger,ensure_ascii=False)
    print(result,end='')


if __name__=='__main__':main()
