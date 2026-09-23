"""Require a traceable answer to every requested part and every requested list item."""
import re
from .evidence_scope import normal

INSTRUCTION = (
    '这是回答完整性核查，不生成新的研究结论。逐个核对candidates.coverage中的用户问题与evidence中已经核实的回答。不要信任旧coverage的状态与理由，也不以来源已经下载当作该问题已经得到回答。'
    'parts逐项列出该问题原句中全部实际要求，request_quote逐字引用原句，evidence_ids仅选当前candidate_evidence_ids中确实回答该要求的证据，缺失标missing。不要把用户未问的细化内容增加为新要求，纯文献定位不要求核对题名里的研究结果。'
    '若用户要求说明或列出某组条件、标准、规则、步骤或要求，enumeration_requested=true，须从已经读到的相应原文清单按条核对source_lists；不得按现有回答挑选几项反过来假装完整清单。'
    '执行摘要中的概述、几个典型例子、介绍页只列的主要条件不等于正式条件全集。完整列表仍在未展示章节时complete_read=false；没有读取整份条件列表不能判断每项都已覆盖。'
    '有编号的清单必须按原文顺序每个编号单列一个items，source_quote保留原编号，不得将多个编号合成一项；检查编号跳跃及清单末尾的定义和例外。不同清单分别列出source_lists。'
    '每个items.source_quote逐字摘录实际已读原文的相应连续条件，不拼接或加省略号；answer_quote逐字摘录evidence_ids对应的同来源已核实claim或boundary中实际回答该条件的连续文字。没有实际回答时answer_quote为空，covered=false。'
    '逐对比较source_quote与answer_quote中的对象、关系、前提、例外、阈值及候补顺序；范围缩窄或泛化、把家庭/机构/个体等不同层次混作同一对象都不匹配。引文里存在条件但主张没解释，仍未完成回答。'
    '用户明确只要求主要条件、举例或摘要概览时按其较窄范围验收；用户只是定位文献时enumeration_requested=false且source_lists为空。要求核对实验系统时，分子/工具名称不能替代原文明确的实验场景。'
    'parts任何一项missing、清单未读完整或有未覆盖项，complete=false；同时说明真正缺少的要求。没有排除条件等结论也需要原文明示，不以空items宣称完整。'
    '解释范围只针对原始用户要求，不要求用户未问的机制实验证明或额外研究；已经明确的观察/因果边界可以回答边界问题。'
    '问题用“为什么”引入现象，不自动表示要求已经被实验证明的微观因果机制。依据原研究解释已知现象、反例与适用边界，并明确哪些原因尚未确定，可以完整回答相应研究问题；不能编造机制来满足问题，也不能把尚无定论的机制增加为必需条件。用户明确要求查证某条因果链时仍须逐项核验该要求。'
    '若必需信息仍在已下载来源未展示的章节，read_requests用来源提供的准确source_id与section_id请求回读，最多2段；未提供章节不能编造编号。输出简短可审计对照，不输出思考过程。'
)


def numbered_list_errors(items):
    """A positive model verdict cannot hide grouped or skipped numbered items."""
    previous=None;errors=[]
    for item in items:
        numbers=[int(x) for x in re.findall(r'(?m)^\s*(\d{1,3})[.)、]\s+(?=\S)',item['source_quote'])]
        if len(numbers)>1:errors.append('多个编号条目尚未逐项核对')
        for number in numbers:
            if previous is not None and number!=1 and number!=previous+1:
                errors.append('原文清单编号不连续，尚未核对缺失或重复条目')
            previous=number
    return errors


def apply(rows,judgements,pools,spans,read_sources,pdf_source_ids=()):
    pool={r['question_id']:set(r['candidate_evidence_ids']) for r in pools}
    evidence={e['evidence_id']:e for e in spans}
    # Saved notebook quotes are also shown verbatim in this request. Their free
    # commentary is not original text and cannot satisfy a source-list check.
    texts={s['id']:[s.get('text','')]+[n.get('quote','') for n in s.get('source_notes',[])] for s in read_sources}
    # These exact, located quotes are also provided in candidates.evidence. A
    # later context window need not repeat them for the checker to read them.
    for e in spans:
        if e.get('verification')=='quote_matched' and e.get('quote_origin')=='source_text':
            texts.setdefault(e['source_id'],[]).append(e['quote'])
    for row in rows:
        matches=[r for r in judgements if r['question_id']==row['question_id']]
        check=matches[0] if len(matches)==1 else None
        reasons=[];valid=pool.get(row['question_id'],set())
        if not check or not check.get('reason'):
            reasons.append('尚未完成各项要求的回答完整性核查')
        else:
            if not check['complete']:reasons.append(check['reason'])
            if not check['parts']:reasons.append('核查未列出原问题的要求')
            for part in check['parts']:
                if not part['request_quote'] or part['request_quote'] not in row['question']:
                    reasons.append('核查要求未能对应用户原句')
                if part['status']!='answered':reasons.append(part['reason'] or '仍有要求未回答')
                if not part['evidence_ids'] or set(part['evidence_ids'])-valid:
                    reasons.append('部分要求尚无有效的核实证据')
            if check['enumeration_requested'] and not check['source_lists']:
                reasons.append('尚未逐项核对所要求的完整清单')
            for source_list in check['source_lists']:
                sid=source_list['source_id'];pdf=sid in pdf_source_ids
                reasons.extend(numbered_list_errors(source_list['items']))
                if not source_list['complete_read']:
                    reasons.append(source_list['reason'] or '尚未读全所要求的原文清单')
                if not source_list['items']:reasons.append('原文清单尚无逐项回答对照')
                for item in source_list['items']:
                    quote=normal(item['source_quote'],pdf);ids=item['evidence_ids']
                    if not quote or not any(quote in normal(text,pdf) for text in texts.get(sid,[])):
                        reasons.append('清单条目未能定位到实际已读原文')
                    if not item['covered']:reasons.append(item['reason'] or '清单仍有未回答条目')
                    answer=normal(item['answer_quote'])
                    if not ids or set(ids)-valid or not answer or not any(evidence.get(eid,{}).get('source_id')==sid and any(answer in normal(evidence[eid].get(k,'')) for k in ('claim','boundary')) for eid in ids):
                        reasons.append('清单条目尚未关联同来源的实际回答：'+item['source_quote'][:100])
        row['answer_scope']=check
        if reasons:row.update(status='unresolved',reason='；'.join(dict.fromkeys(reasons)))
    return rows
