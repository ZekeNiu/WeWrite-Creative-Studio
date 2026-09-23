"""Task-focused excerpts; stored source text is never shortened or rewritten."""
import re

POLICY_VERSION = 37
TEMPORAL_SCOPE_POLICY = ('时间和版本也是适用范围：用户问首次发布、某年或某版时，当前帮助页与后续更新不能证明当时已具备全部功能。'
    '区分首次记录、后续技术解释和当前行为，核对来源日期与所述功能的生效版本；没有当时依据的新增能力不得混入早期结论，scope必须unknown并保留缺口。')
QUOTE_PROVENANCE_POLICY = ('verification=quote_matched表示系统已将该条quote逐字定位到对应来源的实际正文/摘要（bibliography另标为书目题名）。'
    '因此candidates.quote本身就是本次提供的、已定位的原文，即使context.sources.text的当前章节切片没有重复包含它，仍须依据这段引文核查，不能仅以当前切片没重复引文为由宣称原文未提供。'
    '逐字定位只证明引文真实存在，不证明claim或boundary得到支持；仍须核实全部事实、数字、条件及因果强度，不能让quote_matched覆盖缺据、矛盾或二手出处问题。')
COVERAGE_COMPLETENESS_POLICY = ('reported_limits 是本轮整理报告明确披露的摘要、缺口、冲突与限制，必须与已核实证据一起交叉核对，不能在整体覆盖审查时丢弃。'
    '这些陈述及其blocking/limitation标签不是裁决，需回到用户原句判断是否关联其明确要求。'
    'reported_limits中的自由摘要、claim及resolution不是已核实事实；rejected_evidence是未获支持的主张，不能从这些内容重新引入被否定的事实或解释。'
    '覆盖reason只能依据evidence中已核实的判断及其边界，不得新增事实或因果链。解释因果边界时，观察性数据只能支持观察关系；必须明确哪些机制没有被直接测量或验证，不能以另一条未验证的中介机制替代原假说并称已核实。'
    '用户明确要求说明一组入选/排除条件、适用标准或条件清单时，必须核查这组条件，不能把当前摘要列出的几个示例当成完整集合；'
    '如果报告同时承认该要求的条件细则仍在未取得的正文/附录中，对应要求必须unresolved，不能以普通研究局限或额外可选问题的名义宣布已经充分。'
    '只有用户明确限定为摘要概览或局部说明时，才能按该较窄范围验收。'
    '这不等于一律要求全文：纯文献定位仍可由书目确认；摘要明确包含所问全部信息时也可通过。'
    '模型自行扩展的旁支问题与研究自身的适用边界仍不增加必需要求；未要求的机制证明或后续复现不因出现在reported_limits而阻塞。')
LOOKUP_SCOPE_POLICY = ('先依据用户完整原句的任务动词区分文献定位与事实核查。用户仅要求查找或定位文献时，作者、年份、题名内的人数等属于书目识别线索；'
    '纯定位只整理身份确认与可访问范围，不自行增加用户未要求的结果数字、实验解释或机制。用户同时要求其他事实时先独立确认身份，再分别核查实际要求。'
    '已核验书目足以确认与这些线索匹配，不得将其拆成额外的样本分布、绝对发生率或数字原始数据核验要求。'
    '此时可以requires_source_content=false，但只能确认文献身份，不能另行声称研究数字、效果或机制已经核实。'
    '用户同时要求说明研究对象、结果，或明确要求查证数字出处、分母与因果时，对这些明确要求仍必须以实际正文/摘要证据核验，书目题名不能替代；'
    '不同研究或子组的相近比例仍不代表完成数字溯源。每个子问题需回到完整原句理解，不能把识别线索提升成用户未要求的核验任务。')
COVERAGE_PROVENANCE_POLICY = ('溯源一个数字必须对应同一统计对象、分母、分组和原始出处，数值相近不代表完成溯源。'
    '不得把另一研究或不同子组的比例四舍五入后，当成用户所问数字的原始依据；也不能把不同子组拼成并不存在的总体结果。'
    '只有找到原始表述，或能从同一原始数据及一致口径透明复算，才可以确认数字出处。'
    '若只找到相关但不同的数字，应明确目标数字仍未查证，而不是默默用更容易支持的表述替换它。')
CLAIM_SUPPORT_POLICY = ('核查对象是 claim 和 boundary 中每一个可核对的事实，包括括号里的专有名词、附加解释和限定条件；boundary不是可免于核查的备注。'
    '主体结论有据不能掩盖其中一项缺据；任何具体事实在所给原文或书目中没有依据时，对应 checks 必须为 unknown 且 support=unsupported，reason 点明缺项。'
    'limited 仅表示完整判断已有依据、但研究设计或适用范围有限，不能用于放行部分内容缺据的主张。'
    '边界中的实验系统、测试条件或人群也须有对应来源；不能从分子组成推断实验场景，不能将另一指标的脚注测试条件移给本指标。'
    '翻译研究条件时准确保留对象层级和关系，使用直接表述，不以成语、比喻或近义概括替换原文的具体单位与范围；存在翻译歧义时保留关键原词并明确不确定。'
    '外部常识中正确也不等于当前材料已支持，不得凭记忆补全名称或因果解释。'+TEMPORAL_SCOPE_POLICY)
NUMERIC_POLICY = ('对 claim 和 boundary 中每一项数字（包括括号、约数、分数分母、单位和时间窗）逐项与实际给出的原文或书目核对，'
    '不能只核对主要结论而忽略附加数字。不能从四舍五入的百分比反推实际人数或样本分母，也不能用“约/左右”补全缺失数字；'
    '这种情况 quantity=unknown 且 support=unsupported，reason 必须点明缺失数字。'
    '明确区分原文实测值与可复算的精确算术/单位换算：有原文分子分母时可计算比例、两周可换算14天；'
    '必须说明推导且不能增加原文没有的测量精度或改变统计口径。概率值要同时核对事件与给定前提，不能把假设成立时观察到数据的概率写成假设成立的概率。')
POLICY = '''按具体主张判断来源是否适用，不能仅凭域名、论文身份或用户上传就认定可靠。
先区分原始发布者、当前托管页面与实际发言者。original_url是读取入口，read_url是实际读到的地址，url或bibliography.url可能是文献定位地址；metadata_provenance记录元数据出处，不是正文出处。identity_verified仅表示公开副本与文献身份匹配，不保证页面由原发布者运营或其中每句话都是原始结果。
source_origin逐条区分primary原始研究/原始官方记录、secondary二手解读或转引、background背景资料、unassessed归属未确认。结合实际读取地址、页面署名、出版信息与元数据说明归属依据；相似标题、文风或域名不能证明官方身份，翻译/转载页不能直接称为官方原页，官方站点的论坛发言仍按实际作者和发言性质判断。无法确认时保留unassessed并说明缺口，不凭记忆补全归属。原始研究的已核对公开副本可以支持本研究结果；机构介绍另一研究仍为二手，系统综述自身的综合分析与其转述单项试验分开。
待处理建议不阻止创作，但不能因此视为已核实。对 open/stale 或缺少支持的具体数字、机制断言，限定或省略；不要自动联网或将假设写成事实。遵守 bounded 的实际限定说法和 excluded 的弃用决定。保留文章的问题价值，核心方向无法成立时明确原因，不静默改题。
科研和健康结论优先原始研究、系统综述、专业书籍和权威机构资料；技术实践和产品能力优先官方文档、原始研究、有明确作者与可核对依据的专业博客。
维基百科可支持背景与概念梳理；关键数字、因果关系和争议性判断尽量追溯其参考文献中的原始出处。营销转载、无署名聚合页和搜索摘要只能作为发现线索，不能因重复出现而增加证据强度。
区分同行评议、预印本、摘要和全文；书目、目录和售书页面不能证明书中结论。核对作者、出版方、日期、版本、研究设计、适用人群与利益相关性，缺失信息如实说明，不推测补全。
证据充分性同时考虑原文支持与来源质量。仅对无法省略的核心主张缺口定向补查；非核心证据不足可删去断言或保留边界，不按来源数量凑材料，不固定追加论文检索。
保留独立研究、不同版本、反方与局限。source_type 写实际来源类别，adoption_reason 说明为何能支持这一条主张，use_scope 写适用范围；quality 用 suitable/limited/insufficient 表示适用/有限/不足，不以出处声望代替原文核实。
输入的 excerpt_only 和 excerpts 表示只读取部分原文；不得声称已读全文，也不能从未提供的部分推断事实。已有 claim.stale=true 的依据已变化，只供定位待核对内容，不得直接用作已核实事实。
研究中的病例计数或构成比不等于风险率；没有暴露分母不能比较哪类人、地点、行为更危险。回顾性观察不等于测得神经或组织机制，机制推测必须逐处写明假设，不能只在文末加一句局限后通篇肯定。原作者讨论的外部研究与本研究实测结果分开。
训练、治疗或干预启示不等于验证有效性，不得仅凭观察性研究断言必须使用某个方案或宣布既有方法无效。吸引力应来自具体问题、解释和读者用途；未经证实的生理因果链不能用强烈比喻替代。'''+ '\n'+CLAIM_SUPPORT_POLICY+'\n'+NUMERIC_POLICY


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
    for i,section in enumerate(reversed(source.get('_requested_sections',[]))):
        # Keep earlier requested sections when they still fit in the same budget.
        candidates.append((2000 if i<2 else 1900,section['start'],section['end']))
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
    from .evidence_state import current_spans,SOURCE_IDENTITY_FIELDS
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
        row={k:s.get(k) for k in ('id','kind','status','published_date','bibliography')+SOURCE_IDENTITY_FIELDS}
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
