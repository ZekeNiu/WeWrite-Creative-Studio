"""Conservative guards for explicit numeric durations, never a semantic pass."""
import re
from decimal import Decimal


UNITS={
    'milliseconds':('s','0.001'),'millisecond':('s','0.001'),'ms':('s','0.001'),'毫秒':('s','0.001'),
    'seconds':('s','1'),'second':('s','1'),'s':('s','1'),'秒':('s','1'),
    'minutes':('s','60'),'minute':('s','60'),'min':('s','60'),'分钟':('s','60'),
    'hours':('s','3600'),'hour':('s','3600'),'小时':('s','3600'),
    'days':('s','86400'),'day':('s','86400'),'天':('s','86400'),
    'weeks':('s','604800'),'week':('s','604800'),'周':('s','604800'),
    'months':('month','1'),'month':('month','1'),'个月':('month','1'),
}
NUMBER=r'\d+(?:\.\d+)?'
DURATION=re.compile(r'(?<![\d.])('+NUMBER+r')\s*('+ '|'.join(sorted(UNITS,key=len,reverse=True))+r')(?![a-z])',re.I)
APPROX=r'(?:approximately\s*|about\s*|roughly\s*|约\s*|大约\s*)?'


def expressions(text):
    results=[]
    for match in DURATION.finditer(text):
        unit,factor=UNITS[match[2].lower()];factor=Decimal(factor)
        before=text[:match.start()].lower();after=text[match.end():]
        relation=('point',)
        interval=re.search(r'(?:between\s+|from\s+)?('+NUMBER+r')\s*(?:and|to|至|到|[–—-])\s*$',before)
        if interval:relation=('range',Decimal(interval[1])*factor)
        elif re.search(r'(?:within\s+(?:(?:the\s+)?(?:past|following|next|last)\s+)?|(?:the\s+)?(?:past|last)\s+|at most\s+|no more than\s+|不超过|至多|最多|过去|最近|[≤<])\s*'+APPROX+r'$',before) or re.match(r'\s*(?:以?内|以内|以下)',after):relation=('upper',)
        elif re.search(r'(?:at least\s+|no less than\s+|至少|不少于|[≥>])\s*'+APPROX+r'$',before) or re.match(r'\s*(?:以上|以外)',after):relation=('lower',)
        elif re.search(r'近\s*$',before):relation=('ambiguous',)
        results.append(((Decimal(match[1])*factor,unit),relation))
    return results


def errors(evidence,conditions):
    expected=expressions(evidence.get('claim',''))+expressions(evidence.get('boundary',''))
    shown=[item for c in conditions for item in expressions(c['claim_condition'])]
    reasons=[]
    if any(item not in shown for item in expected):
        reasons.append('主张或边界中的时间条件尚未逐项对照，须保留时间点、上下限或时间窗口')
    for condition in conditions:
        original=expressions(condition['source_condition'])
        counterpart=expressions(condition['claim_condition'])
        for quantity,relation in counterpart:
            same=[kind for value,kind in original if value==quantity]
            if same and relation!=('ambiguous',) and ('ambiguous',) not in same and any(kind!=relation for kind in same):
                reasons.append('时间点、上下限或时间窗口的对照不一致；不同时间条件须分别引用')
    return reasons
