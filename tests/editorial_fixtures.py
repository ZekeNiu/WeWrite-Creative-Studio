"""Explicit synthetic replies for editorial flow tests, not a production fallback."""
from backend.research_contract import CHECKS

SCORES=dict(accuracy=4,viewpoint=4,usefulness=4,voice=4,readability=4)


def reply(kind,context):
    if kind=='ArgumentSynthesis':
        return dict(thesis='先核对条件再作判断',chain=[],strongest_counterargument='简化表达不能替代证据',conflicts=[],boundaries=['仅讨论已有材料'],reader_value='理解适用范围',unresolved=[])
    if kind=='FactAudit':
        rows=[]
        for part in context['segments']:
            source=next((s for s in context['sources'] if '研究只支持关联。' in s['text'] and '研究只支持关联。' in part['text']),None)
            facts=[]
            if source:facts=[dict(quote='研究只支持关联。',status='supported',reason='Synthetic source states association only',source_id=source['id'],source_quote='研究只支持关联。',basis='observed',checks=dict.fromkeys(CHECKS,'matched'),boundary='')]
            elif part['mandatory']:facts=[dict(quote=part['text'],status='unsupported',reason='No synthetic evidence for this empirical statement')]
            rows.append(dict(segment_id=part['id'],no_factual_claim=not facts,reason='General editorial guidance or heading',facts=facts))
        return dict(segments=rows)
    if kind=='EditedDraft':
        content=context['article']
        for issue in context.get('review',{}).get('issues',[]):
            if issue.get('quote') and content.count(issue['quote'])==1 and issue.get('suggestion'):content=content.replace(issue['quote'],issue['suggestion'],1)
        return dict(content=content,explanation='Synthetic whole-draft revision',changes=['Apply located review suggestions'],unresolved=[])
    return None
