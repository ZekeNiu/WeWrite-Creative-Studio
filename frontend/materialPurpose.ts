import type {Article,Source} from './types';

const short=(text:string,limit=96)=>text.length>limit?text.slice(0,limit)+'…':text;

// Explain recorded relationships; never invent a source's relevance from its title.
export function materialPurpose(a:Article,s:Source){
 const claims=(a.evidence.claims||[]).filter((c:any)=>c.source_ids?.includes(s.id));
 const current=claims.find((c:any)=>!c.stale&&!c.assessment_pending&&c.status!=='unsupported');
 const selected=a.creative_intent?.selected;
 const plans=[...(a.creative_intent?.batches||[]).flatMap(b=>b.topics),...a.topics];
 const origin=plans.find(t=>t.source_ids?.includes(s.id));
 let purpose='';
 if(s.use?.trim())purpose='使用要求：'+short(s.use.trim());
 else if(current&&a.stages.sources!=='stale')purpose='用于说明：'+short(current.text);
 else if(selected?.source_ids?.includes(s.id))purpose='当前选题的依据线索，具体结论待核实';
 else if(origin)purpose='选题探索时收集：'+short(origin.title,64);
 else if(claims.length)purpose='已有相关判断待核实：'+short(claims[0].text,76);
 else purpose=s.summary?.trim()?'内容摘要：'+short(s.summary.trim()):s.kind==='user'?'你为本篇添加的材料，整理后确认用途':'已收集，尚未建立与当前选题的关联';
 return {purpose,excluded:!s.selected};
}
