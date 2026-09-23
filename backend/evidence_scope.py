"""Bind independent condition judgments to source and claim; never infer meaning from a word list."""
import re
from . import temporal_scope


INSTRUCTION = (
    '只审查candidates每条主张及boundary的条件逻辑与适用范围，不重复研究概述。原context完整保留。'
    '覆盖claim和boundary中的每一项可核对判断，先定位支持该事实的完整原文句，再逐项列出全部前提、程度、判断主体、例外、并且/或者关系、仅当前项不可用时采用后项的顺序。不能只审quote的主体而跳过boundary里的附加判断。'
    'source_condition逐字摘录quote或context中同一来源实际提供的完整条件片段；claim_condition逐字摘录claim或boundary中表达同一条件的片段，缺失必须空串。其他来源的条件不能借用。'
    '正文条件source_field=text。书目身份另列条件，source_field指向同来源实际书目字段（如bibliography.title、bibliography.year、bibliography.authors.0.family），source_condition必须等于该单字段的完整原值；多个字段拆开核对，不能自行拼装引文格式或省略原值。'
    '书目字段只核验文献身份、作者、发表信息，不作为实验结果、机制、因果或效果的证据；此类内容仍须用实际已读正文或摘要，不能由题名推断。'
    '引用必须连续，不能用省略号拼接；多处条件分成多条对照。'
    '每个条件分别标matched/missing/changed及简短理由；只要一项missing/changed，整条scope必须unknown/mismatch。'
    '不要用主张里的泛称替代原文的具体程度门槛，不把阈值列表误当作已保留使用前提。条件从原文提取，不按主张是否提及来选择条件。'
    '用户未要求完整清单且主张明确只介绍其中部分时，不要求介绍无关项目，但已介绍的每一项必须保留自己的全部限定。'
    '核对条件所限定的具体指标、对象和来源；一个指标的测试条件不能借给另一指标。概率必须保留给定前提和所指事件，不倒置条件概率。'
    '人数和样本量对照必须包含实际被计数的人群：某组病例人数不能改称包含对照组在内的研究总样本。不能仅因数字相同就认定分母对象一致。'
    'claim或boundary含时间数字时，每一项单列条件对照，引用须包含完整时间关系与界限；约某时点不等于该时限内，至少持续某时长不等于恰好该时长，范围不能只取一个端点。单位换算保留原界限，不能只核对数字相同。'
    '假说、可能、推测和观察相关不能强化为已验证因果；这种强度限定同样属于条件。没有适用条件时conditions为空，不能编造条件。'
    '逐个分句核对推测强度；保留“若/如果”的前提，并不允许把该前提下“可能发生”的结果写成“将/必然发生”。另一分句中的可能性或boundary中笼统的假说标签，不能代替本分句的限定。'
    '先判断每个claim_condition与source_condition的逻辑关系：直接转述须保留原文的确定程度、否定范围和量纲；说明证据不能推出什么，须核对被限制的结论是否确实超出原文。不能要求否定推断重复原文的可能性用词，也不能因字词相似就把程度降低当完全消失、非必然当确定否定。'
    '主张或边界中的附加事实若找不到同来源依据，或其所需条件没有读到，scope=unknown；不以空conditions略过缺据的附加判断。'
    '不得凭常识补全；引用、条件或范围不确定时scope=unknown。仅逐条返回可核对的原文对照和结论，不输出思考过程。'
)


def normal(text,pdf=False):
    if pdf:
        from .research import pdf_match_text
        return pdf_match_text(text)[0]
    return re.sub(r'\s+', '', text)


def bibliographic_value(source,field):
    """Resolve one scalar metadata field, without synthesizing citation text."""
    if not field.startswith('bibliography.'):return None
    value=source
    for part in field.split('.'):
        if isinstance(value,dict):value=value.get(part)
        elif isinstance(value,list) and part.isdigit() and int(part)<len(value):value=value[int(part)]
        else:return None
    return str(value) if isinstance(value,(str,int,float)) and not isinstance(value,bool) else None


def apply(spans, judgements, pdf_source_ids=(), read_sources=()):
    sources={s['id']:s for s in read_sources}
    texts={s['id']:[s.get('text','')]+[n.get('quote','') for n in s.get('source_notes',[])] for s in read_sources}
    for e in spans:
        pdf=e.get('source_id') in pdf_source_ids
        rows=[r for r in judgements if r['evidence_id']==e['evidence_id']]
        row=rows[0] if len(rows)==1 else None
        reasons=[]
        if not row or not row.get('reason'):
            reasons.append('适用条件尚未完成独立对照')
        else:
            if row['scope']!='matched':reasons.append(row['reason'])
            reasons.extend(temporal_scope.errors(e,row['conditions']))
            for condition in row['conditions']:
                original=normal(condition['source_condition'],pdf)
                counterpart=normal(condition['claim_condition'])
                field=condition.get('source_field','text')
                if field!='text':
                    value=bibliographic_value(sources.get(e.get('source_id'),{}),field)
                    located=bool(value and normal(condition['source_condition'])==normal(value))
                else:located=bool(original and any(original in normal(t,pdf) for t in [e['quote']]+texts.get(e.get('source_id'),[])))
                if not located:
                    reasons.append('条件对照未能定位到本条原文')
                if condition['status']!='matched':
                    reasons.append(condition['reason'] or '主张遗漏或改变了原文条件')
                elif not counterpart or not any(counterpart in normal(e.get(k,'')) for k in ('claim','boundary')):
                    reasons.append('条件对照未能定位到实际主张或边界')
                source=condition['source_condition'];claim=condition['claim_condition']
                # Reject explicit substitutions between distinct physical quantities;
                # this does not infer a conversion or independently approve a claim.
                for original,substitute,required in [('force','应力','stress'),('strain','应力','stress'),('stress','应变','strain')]:
                    target=re.search(r'应变(?!能力|技巧)',claim) if substitute=='应变' else substitute in claim
                    if re.search(r'\b'+original+r'\b',source,re.I) and target and not re.search(r'\b'+required+r'\b',source,re.I):
                        reasons.append('物理量名称不一致：'+original+'不能直接改为'+substitute)
        e['scope_alignment']=row
        if reasons:
            e['support']='unsupported';e['quality']='insufficient'
            e['support_checks']={**e.get('support_checks',{}),'scope':'unknown'}
            e['support_reason']='；'.join(dict.fromkeys(reasons))
    return spans
