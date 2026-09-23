"""Local source sections and quote-anchored notes, never independent evidence."""
import hashlib
import re

VERSION=2
HEADINGS=re.compile(r'(?im)^\s*(?:\d+[.\s]+)?(?:abstract|introduction|background|methods?|methodology|materials and methods|results?|discussion|conclusions?|limitations?|references|supplement\w*.*|acknowledg\w*|方法|结果|讨论|结论|局限性?|参考文献|补充材料)\s*[:：]?\s*$')
NUMBERED_HEADING=re.compile(r'(?i)^(?:chapter\s+\d+\s*[-–—:.]?\s+|\d+(?:\.\d+)+[.)]?\s+|[a-z]\)\s+|第[一二三四五六七八九十\d]+[章节]\s*)[A-Za-z\u4e00-\u9fff]')


def heading_starts(text):
    starts={m.start():m.group().strip() for m in HEADINGS.finditer(text)}
    offset=0
    for line in text.splitlines(keepends=True):
        title=line.strip()
        if re.match(r'(?i)^[a-z]\) ',title):
            words=title[3:].split()
            if len(words)>8 or not all(w[:1].isupper() or w in {'and','or','of','the','for','in','to','with','at','on'} for w in words):
                offset+=len(line);continue
        # Descriptive protocol/manual headings, without treating TOC leaders,
        # numbered prose sentences or page footers as complete sections.
        if (len(title)<=110 and NUMBERED_HEADING.match(title)
                and not re.search(r'\.{3,}|…|[.;。；]$|\s\d+$',title)):
            starts[offset]=title
        offset+=len(line)
    return sorted(starts.items())


def sections(source):
    text=source.get('text','');starts=[(0,'开头')]
    for offset,title in heading_starts(text):
        if offset>0:starts.append((offset,title))
        else:starts[0]=(0,title)
    pages=[(m.start(),int(m.group(1))) for m in re.finditer(r'\[第\s*(\d+)\s*页\]',text)]
    result=[]
    for i,(start,title) in enumerate(starts):
        end=starts[i+1][0] if i+1<len(starts) else len(text)
        for part,offset in enumerate(range(start,end,5000)):
            stop=min(end,offset+5000)
            row=dict(id='sec'+str(offset),title=title+(' · '+str(part+1) if end-start>5000 else ''),start=offset,end=stop)
            before=[page for at,page in pages if at<=offset]
            within=[page for at,page in pages if offset<at<stop]
            if before or within:row['pages']=list(dict.fromkeys(before[-1:]+within))
            result.append(row)
    return result


def pointers(source):
    text=source.get('text','')
    return [dict(label=m.group().strip(),start=m.start()) for m in re.finditer(r'(?im)^\s*(?:table\s+\d+|fig(?:ure)?[. ]+\d+|footnotes?|supplement\w*[^\n]{0,100}|表\s*\d+|补充材料[^\n]{0,100})[^\n]{0,100}',text)][:80]


def save(source,notes,signature,read_ranges=()):
    text=source.get('text','');kept=[]
    for n in notes:
        quote=n.get('quote','').strip()
        if not quote or quote not in text:continue
        start=text.index(quote)
        item=dict(category=n['category'],note=n['note'],quote=quote,start=start,end=start+len(quote))
        if item not in kept:kept.append(item)
    previous=source.get('notebook',{})
    key=hashlib.sha256(text.encode()).hexdigest()
    if previous.get('text_key')==key and previous.get('analysis_signature')==signature:
        keys={(n['category'],n['quote']) for n in kept}
        kept += [n for n in previous.get('notes',[]) if (n['category'],n['quote']) not in keys]
        read_ranges=list(read_ranges)+previous.get('read_ranges',[])
    ranges=[]
    for item in sorted(read_ranges,key=lambda x:x['start']):
        if ranges and item['start']<=ranges[-1]['end']:ranges[-1]['end']=max(ranges[-1]['end'],item['end'])
        else:ranges.append(dict(item))
    source['notebook']=dict(version=VERSION,text_key=key,analysis_signature=signature,notes=kept,
        sections=sections(source),pointers=pointers(source),access_status=source.get('status',''),
        read_ranges=ranges,read_characters=sum(x['end']-x['start'] for x in ranges),total_characters=len(text),
        missing_categories=sorted({'design','results','counterevidence','limitations','scope'}-{n['category'] for n in kept}))


def request_reads(article,requests):
    changed=False
    for r in requests:
        source=next((s for s in article['sources'] if s['id']==r['source_id'] and s.get('selected')),None)
        if not source:continue
        section=next((x for x in sections(source) if x['id']==r['section_id']),None)
        if not section:continue
        ranges=source.setdefault('_requested_sections',[])
        if section not in ranges:ranges.append(section);changed=True
        elif section not in ranges[-2:]:
            ranges.remove(section);ranges.append(section);changed=True
    return changed
