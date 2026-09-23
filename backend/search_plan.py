"""Channel-aware queries and bounded fair scheduling; legacy strings remain valid."""
import re
from .models import ResearchQuery


def query(value):
    if isinstance(value,str):return ResearchQuery(query=value).model_dump()
    return ResearchQuery.model_validate(value).model_dump()


def text(value):return query(value)['query']


def arxiv_query(value):
    value=value.strip()
    if re.search(r'\b(?:ti|au|abs|all|cat|id):',value):return value
    if value.startswith('"') and value.endswith('"'):return 'all:'+value
    words=re.findall(r'[\w-]+',value)
    stop={'in','the','of','a','an','and','or','for','to','on','with','is','how','why'}
    meaningful=[w for w in words if w.lower() not in stop]
    if 2<=len(words)<=12 and meaningful and all(w[0].isupper() for w in meaningful):
        return 'ti:"'+' '.join(words)+'"'
    return ' AND '.join('all:'+w for w in meaningful[:6]) or 'all:"'+value.replace('"','')+'"'


def compile_query(value,channel):
    item=query(value);specific=item['channel_queries'].get(channel)
    if specific:return specific
    raw=item['query']
    if channel=='pubmed' and re.fullmatch(r'(?i)PMID\s*:\s*\d+',raw):return re.search(r'\d+',raw)[0]+'[uid]'
    if channel=='arxiv' and re.fullmatch(r'(?i)(?:arxiv\s*:\s*)?\d{4}\.\d{4,5}(?:v\d+)?',raw):return 'id:'+re.search(r'\d{4}\.\d{4,5}(?:v\d+)?',raw)[0]
    if channel=='arxiv':return arxiv_query(raw)
    if channel in ('crossref','openalex'):
        return re.sub(r'\s+',' ',re.sub(r'\b(?:AND|OR|NOT)\b|[()]',' ',raw)).strip()
    return raw


def channels(worker,item):
    result=['native']
    domain=' '.join((worker.a['brief']['column'],worker.a['brief'].get('domain',''),item['query'])).lower()
    scholarly=worker.academic_needed and worker.cfg['academic_enabled'] and item['source_type'] not in ('official','general')
    if scholarly:
        medical=any(s in domain for s in ('运动','健康','医学','health','sport','medical','exercise','clinical','cardiovascular','injur'))
        computing=bool(re.search(r'\b(?:ai|physics|computer)\b',domain)) or any(s in domain for s in ('人工智能','计算机','machine learning','数学','物理','arxiv'))
        if medical and worker.cfg['pubmed_enabled']:result.append('pubmed')
        if computing and worker.cfg['arxiv_enabled']:result.append('arxiv')
        # A nonempty but irrelevant index result must never veto the other index.
        result += ['crossref','openalex'] if item['purpose']=='known_source' else ['openalex','crossref']
    if worker.cfg.get('allow_fallback',True):result += ['tavily','google','bing','baidu','duckduckgo']
    return result
