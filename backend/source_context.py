"""Task-focused excerpts; stored source text is never shortened or rewritten."""
import re

POLICY_VERSION = 9
POLICY = '''按具体主张判断来源是否适用，不能仅凭域名、论文身份或用户上传就认定可靠。
待处理建议不阻止创作，但不能因此视为已核实。对 open/stale 或缺少支持的具体数字、机制断言，限定或省略；不要自动联网或将假设写成事实。遵守 bounded 的实际限定说法和 excluded 的弃用决定。保留文章的问题价值，核心方向无法成立时明确原因，不静默改题。
科研和健康结论优先原始研究、系统综述、专业书籍和权威机构资料；技术实践和产品能力优先官方文档、原始研究、有明确作者与可核对依据的专业博客。
维基百科可支持背景与概念梳理；关键数字、因果关系和争议性判断尽量追溯其参考文献中的原始出处。营销转载、无署名聚合页和搜索摘要只能作为发现线索，不能因重复出现而增加证据强度。
区分同行评议、预印本、摘要和全文；书目、目录和售书页面不能证明书中结论。核对作者、出版方、日期、版本、研究设计、适用人群与利益相关性，缺失信息如实说明，不推测补全。
证据充分性同时考虑原文支持与来源质量。仅对无法省略的核心主张缺口定向补查；非核心证据不足可删去断言或保留边界，不按来源数量凑材料，不固定追加论文检索。
保留独立研究、不同版本、反方与局限。source_type 写实际来源类别，adoption_reason 说明为何能支持这一条主张，use_scope 写适用范围；quality 用 suitable/limited/insufficient 表示适用/有限/不足，不以出处声望代替原文核实。
输入的 excerpt_only 和 excerpts 表示只读取部分原文；不得声称已读全文，也不能从未提供的部分推断事实。已有 claim.stale=true 的依据已变化，只供定位待核对内容，不得直接用作已核实事实。
研究中的病例计数或构成比不等于风险率；没有暴露分母不能比较哪类人、地点、行为更危险。回顾性观察不等于测得神经或组织机制，机制推测必须逐处写明假设，不能只在文末加一句局限后通篇肯定。原作者讨论的外部研究与本研究实测结果分开。
训练、治疗或干预启示不等于验证有效性，不得仅凭观察性研究断言必须使用某个方案或宣布既有方法无效。吸引力应来自具体问题、解释和读者用途；未经证实的生理因果链不能用强烈比喻替代。'''


def terms(a, questions=()):
    pieces = [a['brief'].get(k, '') for k in ('topic', 'purpose', 'include')]
    from .creative import intent
    plan=intent(a).get('selected',{})
    pieces += [str(plan.get(k,'')) for k in ('angle','reader_question','novelty','takeaway','key_claims')]
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
    for section in source.get('_requested_sections',[])[-2:]:
        candidates.append((2000,section['start'],section['end']))
    for note in source.get('notebook',{}).get('notes',[]):
        if text[note['start']:note['end']]==note['quote']:
            candidates.append((900,max(0,note['start']-250),min(len(text),note['end']+250)))
    # Design/results/limitations are mandatory reading landmarks across languages.
    headings=r'(?im)^\s*(?:\d+[.\s]+)?(?:methods?|methodology|results?|discussion|conclusions?|limitations?|weaknesses(?: of (?:the )?study)?|方法|结果|讨论|结论|局限性?)\s*[:：]?\s*$'
    for m in re.finditer(headings,text):
        candidates.append((700,max(0,m.start()-80),min(len(text),m.end()+1600)))
    candidates.append((650,max(0,len(text)-1800),len(text)))
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
    candidates.append((600,0,min(900,len(text))))
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
    from .evidence_state import current_spans
    canonical='claims' in a.get('evidence',{})
    extra=current_spans(a) if canonical else list(a.get('research',{}).get('evidence',[]))
    selected=[]
    for s in a['sources']:
        if not s.get('selected'): continue
        spans=[];seen=set()
        for e in ([] if canonical else list(s.get('evidence_spans',[])))+[e for e in extra if e.get('source_id')==s['id']]:
            key=(e.get('quote'),e.get('claim'),e.get('boundary'))
            if key not in seen: spans.append(e);seen.add(key)
        selected.append(dict(s,evidence_spans=spans))
    claim_ids = {c for section in a.get('outline',{}).get('sections',[]) for c in section.get('claim_ids',[])}
    preferred = {sid for c in a.get('evidence',{}).get('claims',[]) if c.get('id') in claim_ids for sid in c.get('source_ids',[])}
    selected.sort(key=lambda s:(not bool(s.get('_requested_sections')),s['id'] not in preferred,not bool(s.get('evidence_spans'))))
    result=[]; remaining=total; keywords=terms(a,questions)
    for i,s in enumerate(selected):
        # Share available context across sources so early long books cannot hide others.
        allowance=min(per_source,remaining,max(1800,remaining//max(1,len(selected)-i)))
        requested=sum(x['end']-x['start'] for x in s.get('_requested_sections',[])[-2:])
        allowance=min(per_source,remaining,max(allowance,requested))
        chunks=excerpts(s,keywords,max(0,allowance)) if allowance else []
        remaining-=sum(len(c['text']) for c in chunks)
        row={k:s.get(k) for k in ('id','title','url','kind','status','published_date','bibliography')}
        from .source_notebook import sections,pointers
        row.update(sections=sections(s),source_notes=s.get('notebook',{}).get('notes',[]),table_supplement_pointers=pointers(s),supplementary_material=s.get('supplementary_material',[]))
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
