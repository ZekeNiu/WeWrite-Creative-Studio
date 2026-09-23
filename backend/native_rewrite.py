"""Platform artifacts are independent of the source and use upstream quality tools."""
import json
import yaml
from . import native_runtime,workflow


async def finish(session):
    platforms=list(dict.fromkeys(session.request.get('platforms',[])))
    if not platforms:raise ValueError('未选择改写平台')
    directory=session.directory.relative_to(session.home).as_posix()
    outputs=[];paths=[directory+'/source.md']
    for platform in platforms:
        filename=platform+'.md';path=session.directory/filename
        content=path.read_text('utf-8').strip()
        if not content:raise ValueError('平台稿为空：'+platform)
        workflow.validate_result('write',content,dict(session.article,sources=session.sources))
        score=json.loads(await session.cli(['score',directory+'/'+filename,'--json']))
        from .native_skills import SKILLS
        spec=yaml.safe_load((SKILLS/'wewrite-rewrite/platforms'/(platform+'.yaml')).read_text('utf-8'))
        length_ok=(not spec['min_chars'] or len(content)>=spec['min_chars']) and (not spec['max_chars'] or len(content)<=spec['max_chars'])
        paths.append(directory+'/'+filename)
        outputs.append(dict(platform=platform,filename=filename,content=content,characters=len(content),quality_score=score['quality_score'],score=score,
                            length_ok=length_ok,versions=len(session.rewrite_versions[filename])))
    similarity=json.loads(await session.cli(['similarity',*paths,'--json']))
    result=dict(outputs=outputs,max_similarity=similarity['max_similarity'],needs_input=similarity['max_similarity']>.6 or any(x['quality_score']<60 or not x['length_ok'] for x in outputs))
    native_runtime.dump(session.directory/'rewrite-report.json',result)
    session.result=result;session.finished=True
    return dict(finished=True,needs_input=result['needs_input'])
