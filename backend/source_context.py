"""Task-focused excerpts; stored source text is never shortened or rewritten."""
import re

POLICY_VERSION = 2
POLICY = '''按具体主张判断来源是否适用，不能仅凭域名、论文身份或用户上传就认定可靠。
科研和健康结论优先原始研究、系统综述、专业书籍和权威机构资料；技术实践和产品能力优先官方文档、原始研究、有明确作者与可核对依据的专业博客。
维基百科可支持背景与概念梳理；关键数字、因果关系和争议性判断尽量追溯其参考文献中的原始出处。营销转载、无署名聚合页和搜索摘要只能作为发现线索，不能因重复出现而增加证据强度。
区分同行评议、预印本、摘要和全文；书目、目录和售书页面不能证明书中结论。核对作者、出版方、日期、版本、研究设计、适用人群与利益相关性，缺失信息如实说明，不推测补全。
证据充分性同时考虑原文支持与来源质量。仅对无法省略的核心主张缺口定向补查；非核心证据不足可删去断言或保留边界，不按来源数量凑材料，不固定追加论文检索。
保留独立研究、不同版本、反方与局限。source_type 写实际来源类别，adoption_reason 说明为何能支持这一条主张，use_scope 写适用范围；quality 用 suitable/limited/insufficient 表示适用/有限/不足，不以出处声望代替原文核实。
输入的 excerpt_only 和 excerpts 表示只读取部分原文；不得声称已读全文，也不能从未提供的部分推断事实。'''


def terms(a, questions=()):
    pieces = [a['brief'].get(k, '') for k in ('topic', 'purpose', 'include')]
    pieces += list(questions)
    pieces += [str(s.get(k, '')) for s in a.get('outline', {}).get('sections', []) for k in ('title','purpose','points')]
    words = re.findall(r'[a-zA-Z][a-zA-Z0-9_-]{2,}|[\u4e00-\u9fff]{2,}', ' '.join(pieces).lower())
    tokens = set(words)
    for word in words:
        if re.fullmatch(r'[\u4e00-\u9fff]+', word):
            tokens.update(word[i:i+2] for i in range(len(word)-1))
    return tokens


def excerpts(source, keywords, limit=12000):
    text = source.get('text', '')
    if len(text) <= limit:
        return [dict(start=0,end=len(text),text=text)] if text else []
    candidates = []
    for e in source.get('evidence_spans', []):
        quote = e.get('quote', '')
        start = e.get('offset', -1)
        if not isinstance(start,int) or text[start:start+len(quote)] != quote:
            start = text.find(quote) if quote else -1
        if start >= 0 and quote:
            candidates.append((1000, max(0,start-350), min(len(text),start+len(quote)+350)))
    # Scan the whole material, including the tail, instead of clipping its head.
    for start in range(0,len(text),1400):
        end = min(len(text),start+1800)
        chunk = text[start:end].lower()
        score = sum(min(chunk.count(k),3) for k in keywords)
        candidates.append((score, start, end))
    # Include orientation, but evidence and task matches take precedence.
    candidates.append((0.5,0,min(900,len(text))))
    chosen = []
    for _, start, end in sorted(candidates, key=lambda x:(-x[0],x[1])):
        merged = []
        for lo,hi in sorted(chosen+[(start,end)]):
            if merged and lo<=merged[-1][1]: merged[-1]=(merged[-1][0],max(hi,merged[-1][1]))
            else: merged.append((lo,hi))
        if sum(hi-lo for lo,hi in merged)<=limit:
            chosen=merged
    return [dict(start=lo,end=hi,text=text[lo:hi]) for lo,hi in chosen]


def sources(a, questions=(), total=65000, per_source=12000):
    extra=list(a.get('research',{}).get('evidence',[]))
    for claim in a.get('evidence',{}).get('claims',[]): extra.extend(claim.get('evidence',[]))
    selected=[]
    for s in a['sources']:
        if not s.get('selected'): continue
        spans=[];seen=set()
        for e in list(s.get('evidence_spans',[]))+[e for e in extra if e.get('source_id')==s['id']]:
            key=(e.get('quote'),e.get('claim'),e.get('boundary'))
            if key not in seen: spans.append(e);seen.add(key)
        selected.append(dict(s,evidence_spans=spans))
    claim_ids = {c for section in a.get('outline',{}).get('sections',[]) for c in section.get('claim_ids',[])}
    preferred = {sid for c in a.get('evidence',{}).get('claims',[]) if c.get('id') in claim_ids for sid in c.get('source_ids',[])}
    selected.sort(key=lambda s:(s['id'] not in preferred,not bool(s.get('evidence_spans'))))
    result=[]; remaining=total; keywords=terms(a,questions)
    for i,s in enumerate(selected):
        # Share available context across sources so early long books cannot hide others.
        allowance=min(per_source,remaining,max(1800,remaining//max(1,len(selected)-i)))
        chunks=excerpts(s,keywords,max(0,allowance)) if allowance else []
        remaining-=sum(len(c['text']) for c in chunks)
        row={k:s.get(k) for k in ('id','title','url','kind','status','published_date','bibliography')}
        row.update(text='\n\n[…原文中间部分未展示…]\n\n'.join(c['text'] for c in chunks),
                   excerpts=[dict(start=c['start'],end=c['end']) for c in chunks],
                   excerpt_only=sum(len(c['text']) for c in chunks)<len(s.get('text','')),
                   use=s.get('use',''),author_experience_allowed=bool(s.get('personal_material')),
                   evidence_spans=[{k:v for k,v in e.items() if k!='quote'} for e in s.get('evidence_spans',[])])
        result.append(row)
    return result


def evidence(a):
    value=a.get('evidence') or {}
    return {**value,'claims':[{k:v for k,v in claim.items() if k!='evidence'} for claim in value.get('claims',[])]}
