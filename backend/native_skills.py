"""Pinned, unmodified upstream instructions and their required reading."""
import hashlib
import json
from pathlib import Path
from . import store

ROOT = store.ROOT / 'vendor/wewrite'
SKILLS = ROOT / 'skills'
MODULES = dict(topic='wewrite-topic', sources='wewrite-write', outline='wewrite-write', write='wewrite-write',
    review='wewrite-review', edit='wewrite-review', revise='wewrite-write', visual='wewrite-visual',
    style='wewrite-style', learn='wewrite-learn', exemplar='wewrite-learn', theme='wewrite-learn',
    rewrite='wewrite-rewrite', publish='wewrite-publish', layout_advice='wewrite-publish', image_post='wewrite-publish', stats='wewrite-stats')
REFERENCES = {
    'wewrite-write': ['references/article-brief.md','references/editorial-quality.md','references/frameworks-quick.md','references/content-enhance.md'],
    'wewrite-review': ['../wewrite-write/references/article-brief.md','../wewrite-write/references/editorial-quality.md','references/seo-rules.md'],
    'wewrite-topic': ['references/topic-selection.md'], 'wewrite-visual': ['references/visual-guide.md'],
    'wewrite-style': ['references/onboard.md','references/style-template.md'],
    'wewrite-learn': ['references/learn-edits.md'], 'wewrite-stats': ['references/effect-review.md'],
    'wewrite-publish': ['references/wechat-constraints.md'],
    'wewrite-rewrite': ['references/multiplatform-rewrite.md'],
}


def verify():
    manifest = json.loads((ROOT/'UPSTREAM_MANIFEST.json').read_text('utf-8'))
    if manifest['revision'] != (ROOT/'UPSTREAM_REVISION').read_text('utf-8').strip():
        raise ValueError('上游版本与校验清单不一致')
    for name, expected in manifest['files'].items():
        path = ROOT/name
        actual = hashlib.sha256(path.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
        if actual != expected: raise ValueError('上游文件已改变，请核对版本：'+name)
    return manifest['revision']


def documents(stage, persona):
    module = MODULES[stage]
    paths = [SKILLS/'wewrite/SKILL.md', SKILLS/module/'SKILL.md']
    paths += [(SKILLS/module/name).resolve() for name in REFERENCES[module]]
    if stage in ('sources','outline','write','review','edit','revise','rewrite'):
        p = SKILLS/'wewrite-write/personas'/f'{persona}.yaml'
        if p.is_file() and p.resolve().is_relative_to(SKILLS.resolve()): paths.append(p)
    result=[]
    for path in dict.fromkeys(paths):
        content=path.read_text('utf-8')
        result.append(dict(path='skills/'+path.relative_to(SKILLS).as_posix(),content=content,
                           sha256=hashlib.sha256(content.encode()).hexdigest()))
    return result
