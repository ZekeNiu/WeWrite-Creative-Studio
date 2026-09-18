"""Idempotently relocate known legacy outputs; unknown files are left untouched."""
import argparse
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def planned_moves():
    output=ROOT/'output'
    for path in sorted(output.iterdir()) if output.exists() else []:
        if path.name in ('articles','diagnostics','test-workspaces'): continue
        if path.is_dir() and (path.name.startswith('qa-') or path.name=='research-network'):
            yield path,output/'test-workspaces'/path.name
        elif path.name=='playwright': yield path,output/'diagnostics'/'screenshots'/'legacy'
        elif path.name=='standards': yield path,output/'diagnostics'/'references'
        elif path.is_file() and path.suffix in ('.json','.log'):
            yield path,output/'diagnostics'/'legacy'/path.name
    legacy=ROOT/'data'/'connection-tests'
    for path in legacy.glob('*.png') if legacy.exists() else []:
        yield path,output/'diagnostics'/'connection-tests'/path.name


def organize(apply=False):
    result=[]
    for source,target in planned_moves():
        source=source.resolve();target=target.resolve()
        if not source.is_relative_to(ROOT) or not target.is_relative_to(ROOT/'output'):
            raise ValueError('Migration path is outside the project output roots')
        status='already-exists' if target.exists() else 'planned'
        if apply and not target.exists():
            target.parent.mkdir(parents=True,exist_ok=True)
            source.rename(target);status='moved'
        result.append(dict(source=str(source.relative_to(ROOT)),target=str(target.relative_to(ROOT)),status=status))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--apply',action='store_true')
    print(json.dumps(organize(parser.parse_args().apply),ensure_ascii=False,indent=2))
