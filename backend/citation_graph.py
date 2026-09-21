"""Bounded metadata neighbors. A citation edge is a lead, never evidence support."""
import re
from urllib.parse import quote
from . import academic


async def neighbors(source,request):
    depth=source.get('citation_depth',0)
    if depth>=2:return [],[]
    found=[];attempts=[]
    for ref in source.get('references',[]):
        doi=academic.normalized_doi(ref.get('doi',''))
        if doi:
            found.append(dict(title=ref.get('title') or doi,url='https://doi.org/'+doi,doi=doi,content='',academic=True,
                status='metadata_only',provider='references',citation_relation='references'))
    identifier=source.get('openalex_id') or academic.normalized_doi(source.get('doi',''))
    if not identifier:return found,attempts
    try:
        lookup=identifier.rsplit('/',1)[-1] if source.get('openalex_id') else 'doi:'+identifier
        address='https://api.openalex.org/works/'+quote(lookup,safe=':/')
        response=await request('openalex',address,None)
        work=response.json();wid=work.get('id','').split('/')[-1]
        if not re.fullmatch(r'W\d+',wid):raise ValueError('文献关系身份尚未确认')
        # A singleton must refer to the requested identity before traversing edges.
        wanted=academic.normalized_doi(source.get('doi',''))
        if wanted and academic.normalized_doi(work.get('doi',''))!=wanted:raise ValueError('文献关系 DOI 不一致')
        attempts.append(dict(channel='openalex',status='identified',url=address))
        for relation,filter_value in [('references','cited_by:'+wid),('cited_by','cites:'+wid)]:
            try:
                response=await request('openalex','https://api.openalex.org/works',dict(filter=filter_value,per_page=24))
                rows=academic.openalex_records(response.json().get('results',[]))
                found.extend(dict(r,citation_relation=relation) for r in rows)
                attempts.append(dict(channel='openalex',relation=relation,status='candidates' if rows else 'no_results',count=len(rows)))
            except ValueError as exc:attempts.append(dict(channel='openalex',relation=relation,status='failed',reason=str(exc)))
    except ValueError as exc:attempts.append(dict(channel='openalex',status='failed',reason=str(exc)))
    rows=academic.merge_records(found)
    for row in rows:
        row.update(citation_depth=depth+1,citation_paths=[dict(parent_id=source['id'],relation=row.pop('citation_relation','references'),depth=depth+1)])
    return rows,attempts
