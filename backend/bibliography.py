"""GB/T 7714—2025 sequential references; metadata is never inferred by an LLM.

Verified against the published standard, clauses 7.1, 8.5, 8.6.3, 8.12,
8.16 and 9.2. Incomplete records remain explicitly incomplete.
"""
import re
from datetime import date
from pydantic import BaseModel, Field
from . import materials

MARKER = re.compile(r'\[(S[a-zA-Z0-9]+(?:\s*[,，;；]\s*S[a-zA-Z0-9]+)*)\]')
FIELDS = ('authors', 'title', 'document_type', 'venue', 'year', 'volume', 'issue',
          'pages', 'article_number', 'doi', 'url', 'access_date', 'published_date', 'version', 'platform', 'publisher', 'publication_place')


class Metadata(BaseModel):
    authors: list[str | dict[str,str]] = Field(default_factory=list,max_length=500)
    title: str = Field('',max_length=3000)
    document_type: str = Field('',max_length=10)
    venue: str = Field('',max_length=1000)
    year: str = Field('',max_length=20)
    volume: str = Field('',max_length=100)
    issue: str = Field('',max_length=100)
    pages: str = Field('',max_length=100)
    article_number: str = Field('',max_length=100)
    doi: str = Field('',max_length=500)
    url: str = Field('',max_length=3000)
    access_date: str = Field('',max_length=50)
    published_date: str = Field('',max_length=50)
    version: str = Field('',max_length=100)
    platform: str = Field('',max_length=500)
    publisher: str = Field('',max_length=1000)
    publication_place: str = Field('',max_length=500)


def metadata(s):
    m = dict(s.get('bibliography') or {})
    for k in ('title', 'doi', 'url', 'published_date'):
        if not m.get(k): m[k] = s.get(k, '')
    m.setdefault('document_type', 'EB' if m.get('url') else '')
    m.setdefault('access_date', (s.get('retrieved_at') or s.get('created') or '')[:10])
    return m


def author_text(authors):
    if isinstance(authors, str): authors = [x.strip() for x in authors.split(';') if x.strip()]
    names = []
    for a in authors or []:
        if isinstance(a, dict):
            family = a.get('family', '')
            given = a.get('given', '')
            # Keep the supplied spelling/case; transliteration cannot be guessed.
            initials = ' '.join(x[0] for x in re.findall(r'[^\W\d_]+', given))
            names.append((family + ' ' + initials).strip() or a.get('literal', ''))
        else: names.append(str(a).strip())
    names = [n for n in names if n]
    if len(names) > 3: names = names[:3] + [('等' if any('\u4e00' <= c <= '\u9fff' for c in ''.join(names)) else 'et al.')]
    return ', '.join(names)


def format_reference(s):
    m = metadata(s); typ = m.get('document_type') or ''; url = m.get('url', '').strip()
    missing = []
    if not m.get('title'): missing.append('题名')
    if typ not in ('J', 'C', 'PP', 'EB', 'M'): missing.append('受支持的文献类型（J/C/PP/EB/M）')
    if not url and typ in ('EB','PP'): missing.append('可追溯网址')
    if typ in ('J', 'C'):
        for field, label in [('authors', '作者'), ('venue', '期刊或会议'), ('year', '年份')]:
            if not m.get(field): missing.append(label)
    if typ in ('EB', 'PP') and not m.get('access_date'): missing.append('访问日期')
    if typ == 'PP' and not m.get('authors'): missing.append('作者')
    if typ == 'M':
        for field,label in [('authors','作者'),('publisher','出版社'),('publication_place','出版地'),('year','年份')]:
            if not m.get(field): missing.append(label)
    if any(isinstance(a,str) and re.search(r'[A-Za-z]{2,}\s+[A-Za-z]{2,}',a) for a in m.get('authors',[])):
        missing.append('西文作者姓、名顺序待核对')
    prefix = author_text(m.get('authors'))
    out = (prefix + '. ' if prefix else '') + m.get('title', '题名待补全').rstrip('.')
    out += '[' + (typ or '?') + ('/OL' if url else '') + ']'
    if typ == 'C': out += '//' + m.get('venue', '')
    else: out += '. '
    if typ == 'M':
        if m.get('version'): out+=m['version'].rstrip('.')+'. '
        out+=m.get('publication_place','')
        if m.get('publisher'): out+=(': ' if m.get('publication_place') else '')+m['publisher']
        if m.get('year'): out+=', '+m['year']
        if m.get('pages'): out+=': '+m['pages']
        if url and m.get('access_date'): out+='['+m['access_date'][:10]+']'
        out=out.rstrip(' ,')+'. '
    elif typ in ('J', 'C'):
        if typ == 'J': out += m.get('venue', '')
        if m.get('year'): out += ', ' + str(m['year'])
        if m.get('volume'): out += ', ' + str(m['volume'])
        if m.get('issue'): out += '(' + str(m['issue']) + ')'
        pages = m.get('pages') or m.get('article_number')
        if pages: out += ': ' + str(pages)
        out = out.rstrip(' ,') + '. '
    else:
        if m.get('version'): out += m['version'].rstrip('.') + '. '
        if m.get('platform'): out += m['platform']
        if m.get('published_date'): out += '(' + m['published_date'][:10] + ')'
        if m.get('access_date'): out += '[' + m['access_date'][:10] + ']'
        out += '. '
    if url: out += url + '. '
    if m.get('doi'): out += 'DOI:' + re.sub(r'^https?://(?:dx\.)?doi.org/', '', m['doi']) + '. '
    out = out.strip()
    if missing: out += ' （文献信息待补全：' + '、'.join(missing) + '）'
    return {'text': out, 'complete': not missing, 'missing': missing, 'metadata': m}


def citations(content, sources):
    lookup = {s['id']: s for s in sources}; order = []; unknown = []
    def replace(match):
        nums = []
        for sid in re.split(r'\s*[,，;；]\s*', match[1]):
            if sid not in lookup:
                unknown.append(sid); nums.append('?'); continue
            if sid not in order: order.append(sid)
            n = str(order.index(sid) + 1)
            if n not in nums: nums.append(n)
        return '<sup style="font-size:0.75em;vertical-align:super;line-height:0">[' + ','.join(nums) + ']</sup>'
    body = MARKER.sub(replace, content)
    refs = [dict(format_reference(lookup[sid]), id=sid, number=i+1) for i, sid in enumerate(order)]
    return body, refs, list(dict.fromkeys(unknown))


def import_records(filename, blob):
    text = blob.decode('utf-8-sig')
    records = []
    if filename.lower().endswith('.bib'):
        import bibtexparser
        for e in bibtexparser.loads(text).entries:
            authors = []
            for a in e.get('author', '').split(' and '):
                if not a.strip(): continue
                parts = a.split(',', 1)
                authors.append({'family': parts[0].strip(), 'given': parts[1].strip()} if len(parts) == 2 else a.strip())
            records.append(dict(title=e.get('title', '').replace('{', '').replace('}', ''), authors=authors,
                document_type='PP' if e.get('eprint') and not e.get('journal') else {'article':'J','inproceedings':'C','conference':'C','book':'M','inbook':'M','incollection':'M','phdthesis':'D','mastersthesis':'D','techreport':'R'}.get(e.get('ENTRYTYPE'), 'EB'),
                venue=e.get('journal') or e.get('booktitle', ''), year=e.get('year', ''), volume=e.get('volume', ''),
                issue=e.get('number', ''), pages=e.get('pages', '').replace('--', '-'), doi=e.get('doi', ''),
                url=e.get('url') or ('https://doi.org/'+e['doi'] if e.get('doi') else ''), access_date=date.today().isoformat(),
                platform=e.get('archiveprefix', ''), version=e.get('edition') or e.get('version', ''),
                publisher=e.get('publisher',''),publication_place=e.get('address','')))
    else:
        entries=[]; entry={}; last=None
        for line in text.splitlines():
            match=re.match(r'^([A-Z0-9]{2})\s{2}-\s?(.*)$', line)
            if match:
                tag,value=match.groups(); last=tag
                if tag=='ER': entries.append(entry);entry={};last=None
                else: entry.setdefault(tag, []).append(value.strip())
            elif last and line.strip(): entry[last][-1]+=' '+line.strip()
        if entry: entries.append(entry)
        for e in entries:
            get=lambda *ks: next((e[k][0] for k in ks if e.get(k)), '')
            identifier=get('DO'); start=get('SP'); end=get('EP')
            records.append(dict(title=get('TI','T1'),authors=e.get('AU', e.get('A1', [])),document_type={'JOUR':'J','CONF':'C','CPAPER':'C','UNPB':'PP','BOOK':'M','CHAP':'M','THES':'D','RPRT':'R'}.get(get('TY'),'EB'),
                venue=get('JO','JF','T2'),year=get('PY','Y1')[:4],volume=get('VL'),issue=get('IS'),pages=start+('-'+end if end else ''),
                doi=identifier,url=get('UR') or ('https://doi.org/'+identifier if identifier else ''),access_date=date.today().isoformat(),
                publisher=get('PB'),publication_place=get('CY'),version=get('ET')))
    if not records or len(records)>200: raise ValueError('请导入包含 1–200 条记录的 BibTeX 或 RIS 文件')
    result=[]
    for m in records:
        s=materials.source(m['title'] or '题名待补全', '', m['url'], 'bibliography')
        s.update(bibliography=m, doi=m.get('doi',''), status='metadata_only', metadata_provenance=[{'provider':'import','file':filename}])
        result.append(s)
    return result
