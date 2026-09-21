"""Check the reported condition alignment without trusting its aggregate verdict."""
import re


INSTRUCTION = (
    '只审查candidates每条主张及boundary的条件逻辑与适用范围，不重复研究概述。原context完整保留。'
    '从quote先逐项列出支持本条判断所必需的全部前提、程度、判断主体、例外、并且/或者关系、仅当前项不可用时采用后项的顺序。'
    'source_condition逐字摘录quote中的完整条件片段；claim_condition逐字摘录claim或boundary中表达同一条件的片段，缺失必须空串。'
    '每个条件分别标matched/missing/changed及简短理由；只要一项missing/changed，整条scope必须unknown/mismatch。'
    '不要用主张里的泛称替代原文的具体程度门槛，不把阈值列表误当作已保留使用前提。条件从原文提取，不按主张是否提及来选择条件。'
    '用户未要求完整清单且主张明确只介绍其中部分时，不要求介绍无关项目，但已介绍的每一项必须保留自己的全部限定。'
    '核对条件所限定的具体指标、对象和来源；一个指标的测试条件不能借给另一指标。概率必须保留给定前提和所指事件，不倒置条件概率。'
    '假说、可能、推测和观察相关不能强化为已验证因果；这种强度限定同样属于条件。没有适用条件时conditions为空，不能编造条件。'
    '不得凭常识补全；引用、条件或范围不确定时scope=unknown。仅逐条返回可核对的原文对照和结论，不输出思考过程。'
)


def normal(text):
    return re.sub(r'\s+', '', text)


def apply(spans, judgements):
    for e in spans:
        rows=[r for r in judgements if r['evidence_id']==e['evidence_id']]
        row=rows[0] if len(rows)==1 else None
        reasons=[]
        if not row or not row.get('reason'):
            reasons.append('适用条件尚未完成独立对照')
        else:
            if row['scope']!='matched':reasons.append(row['reason'])
            for condition in row['conditions']:
                original=normal(condition['source_condition'])
                counterpart=normal(condition['claim_condition'])
                if not original or original not in normal(e['quote']):
                    reasons.append('条件对照未能定位到本条原文')
                if condition['status']!='matched':
                    reasons.append(condition['reason'] or '主张遗漏或改变了原文条件')
                elif not counterpart or not any(counterpart in normal(e.get(k,'')) for k in ('claim','boundary')):
                    reasons.append('条件对照未能定位到实际主张或边界')
        e['scope_alignment']=row
        if reasons:
            e['support']='unsupported';e['quality']='insufficient'
            e['support_checks']={**e.get('support_checks',{}),'scope':'unknown'}
            e['support_reason']='；'.join(dict.fromkeys(reasons))
    return spans
