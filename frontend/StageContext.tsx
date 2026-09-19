import type {Article,Stage} from './types';
import {Tag} from './ui';

export type ContextSelection={kind:'source'|'section';id:string}|null;
export type FocusTarget={kind:'section'|'plan'|'image';id:string};
export type IssueFocus={token:number;id?:string};
type Props={a:Article;step:Stage;selection:ContextSelection;clear:()=>void;inspect:(id:string)=>void;locate:(target:FocusTarget)=>void;issue:(id:string)=>void};

function Summary({title,text}:{title:string;text?:string}){
 if(!text)return null;
 return <details className="context-section"><summary>{title}</summary><p className="context-text">{text}</p></details>;
}
function Text({value}:{value:string}){
 return value.length>180?<details className="context-long"><summary>{value.slice(0,140)}… <small>展开完整内容</small></summary><p className="context-text">{value}</p></details>:<p className="context-text">{value}</p>;
}

export default function StageContext({a,step,selection,clear,inspect,locate,issue}:Props){
 const claims:any[]=a.evidence?.claims||[];
 const sections=a.outline.sections||[];
 const stale=a.stages.sources==='stale'||!!a.research?.stale;
 const source=(id:string)=>a.sources.find(s=>s.id===id);
 function sourceLink(id:string){const s=source(id);return <div className="context-source" key={id}>{s?<><button className="text-button" onClick={()=>inspect(id)}>{s.title}</button>{!s.selected&&<Tag tone="amber">未采用</Tag>}<small>{s.status==='metadata_only'?'仅文献信息':s.status==='abstract_only'?'仅摘要':s.status==='excerpt_only'?'仅搜索片段':s.status==='unreadable'?'无法读取':'已有来源内容'}</small></>:<p className="muted">来源已删除 · {id}</p>}</div>}
 function claimList(ids:string[]){return ids.length?ids.map(id=>{const c=claims.find(c=>c.id===id);return <div className="context-section" key={id}>{c?<><Tag tone={c.status==='unsupported'?'amber':''}>{c.status==='unsupported'?'缺少支持':c.status==='bounded'?'有适用边界':c.status==='supported'?'已有支持记录':'支持状态未记录'}</Tag><Text value={c.text||''}/>{c.boundary&&<Summary title="适用边界" text={c.boundary}/>}<details><summary>关联来源 · {c.source_ids?.length||0}</summary>{c.source_ids?.length?c.source_ids.map(sourceLink):<p className="muted">尚无来源关联。</p>}</details></>:<p className="muted">主张已不存在 · {id}</p>}</div>}):<p className="muted">尚无关联主张；这不等于主张已被否定。</p>}
 const history=<>{stale&&<p className="notice amber">资料已变化，以下为历史依据，需更新后再判断。</p>}{a.stages.outline==='stale'&&<p className="muted">大纲关联待更新。</p>}</>;
 if(step==='sources'){
  const s=selection?.kind==='source'?source(selection.id):undefined;
  const related=s?claims.filter(c=>c.source_ids?.includes(s.id)):[];
  const relatedSections=sections.filter(section=>section.claim_ids?.some(id=>related.some(c=>c.id===id)));
  const issues=a.materials_state?[...a.materials_state.required,...a.materials_state.boundaries]:(a.research?.issues||[]).filter(i=>['open','stale'].includes(i.status));
  return <div className="stage-context">{s?<><button className="text-button" onClick={clear}>返回素材概况</button><h3>{s.title}</h3><Tag tone={s.selected?'':'amber'}>{s.selected?'已采用':'未采用'}</Tag>{history}<button className="button secondary full" onClick={()=>inspect(s.id)}>引用详情与原文依据</button><h4>关联主张</h4>{claimList(related.map(c=>c.id))}<h4>关联章节</h4>{relatedSections.length?relatedSections.map(section=><p key={section.id}>{section.title}</p>):<p className="muted">尚无关联章节。</p>}</>:<><h3>本篇素材</h3>{a.materials_state&&<p>{a.materials_state.message}</p>}<p>已采用 {a.sources.filter(s=>s.selected).length} / {a.sources.length} 条</p>{history}<p className="muted">展开主区的一条素材，可在这里对照关联主张与章节。</p><h4>待核实与写作边界</h4>{issues.length?<div className="context-nav">{issues.map(i=><button key={i.id} onClick={()=>issue(i.id)}><small>{i.kind==='blocking'?'需要处理':'写作局限'}</small><span>{i.text}</span></button>)}</div>:<p className="muted">暂无待处理记录{!a.research?'，尚未进行资料核实':''}。</p>}</>}<p className="context-footnote">关联来自已有资料整理与大纲，不代表正文已实际引用。完整编辑在主区进行。</p></div>;
 }
 if(step==='outline'){
  const section=selection?.kind==='section'?sections.find(s=>s.id===selection.id):undefined;
  return <div className="stage-context"><h3>章节导航</h3>{sections.length?<div className="context-nav">{sections.map((s,i)=><button key={s.id} aria-current={s.id===section?.id?'true':undefined} onClick={()=>locate({kind:'section',id:s.id})}>{i+1}. {s.title}</button>)}</div>:<p className="muted">生成或添加章节后，可以在这里对照依据。</p>}{history}{section?<><div className="row between"><h4>当前章节依据</h4><button className="text-button" onClick={clear}>返回概况</button></div><p>{section.title}</p>{claimList(section.claim_ids||[])}</>:<p className="muted">点击章节或在主区编辑章节，查看对应主张与来源。</p>}<Summary title="读者最终获得什么" text={a.outline.takeaway}/><Summary title="反方观点 / 替代解释" text={a.outline.counterpoint}/><Summary title="文章适用边界" text={a.outline.boundary}/><p className="context-footnote">有来源关联不等于事实已经核实；请对照原文和适用范围。</p></div>;
 }
 if(step==='visual'){
  const images=a.images.filter(im=>im.selected);
  const headings=[...a.content.matchAll(/^#{1,6}\s+(.+)$/gm)].map(m=>m[1]);
  return <div className="stage-context"><h3>配图概况</h3><p>{a.image_plans.length} 个方案 · {images.length} 张用于排版</p><p className="muted">AI 配图{a.visual.enabled?'已启用':'未启用'}；上传、生成和编辑均在主区完成。</p>{a.stages.visual==='stale'&&<p className="notice amber">正文已变化，配图方案与位置需重新核对。</p>}<h4>用于排版的图片</h4>{images.length?<div className="context-nav">{images.map(im=><button key={im.id} onClick={()=>locate({kind:'image',id:im.id})}><small>{im.role==='cover'?'封面':im.after_heading?'章节之后：'+im.after_heading:'文章末尾'}</small><span>{im.caption||'未填写图注'}</span>{im.role!=='cover'&&im.after_heading&&!headings.includes(im.after_heading)&&<small className="context-warning">对应章节已不存在，请在主区调整位置。</small>}</button>)}</div>:<p className="muted">尚无用于排版的图片。没有配图也可继续完成文章。</p>}{a.image_plans.length>0&&<details className="context-section"><summary>配图方案 · {a.image_plans.length}</summary><div className="context-nav">{a.image_plans.map((p,i)=><button key={p.id} onClick={()=>locate({kind:'plan',id:p.id})}>{p.role==='cover'?'封面方案':`插图方案 ${i}`} · {p.caption||'未填写图注'}</button>)}</div></details>}</div>;
 }
 return null;
}
