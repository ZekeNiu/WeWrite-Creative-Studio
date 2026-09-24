import {useRef} from 'react';
import {api} from './api';
import type {Article} from './types';

export function SynthesisSummary({a}:{a:Article}){
 const s=a.argument_synthesis;if(!s)return null;
 return <details className="service-card"><summary>论证综合：判断、证据与反方</summary><p><strong>{s.thesis}</strong></p>{s.chain.map(x=><details key={x.id}><summary>{x.judgement}</summary><p>{x.reasoning}</p><p>{x.boundary}</p><p className="muted">{x.source_ids.map(id=>a.sources.find(v=>v.id===id)?.title||'来源已移除').join('；')}</p></details>)}<p>最强反方：{s.strongest_counterargument}</p><p>读者所得：{s.reader_value}</p>{s.conflicts.map((x,i)=><p key={i}>证据冲突：{x}</p>)}{s.boundaries.map((x,i)=><p key={i}>适用边界：{x}</p>)}{s.unresolved.map((x,i)=><p className="notice amber" key={i}>{x}</p>)}</details>;
}

export default function EditorialPanel({a,busy,run,act,update,prepare}:{a:Article;busy:boolean;run:(stage:string,extra?:Record<string,unknown>)=>Promise<void>;act:(fn:()=>Promise<void>)=>Promise<void>;update:(a:Article)=>void;prepare:()=>Promise<Article>}){
 const lock=useRef(false);
 async function action(path:string,body:Record<string,unknown>={}){
  if(lock.current||busy)return;lock.current=true;
  try{await act(async()=>{const current=await prepare();update(await api<Article>(`/articles/${current.id}/${path}`,'POST',{revision:current.revision,...body}))})}finally{lock.current=false}
 }
 const kinds:Record<string,string>={initial:'初稿',edited:'编辑稿',human_final:'人工定稿'};
 return <section className="editorial-panel" aria-label="稿件操作"><div className="editorial-actions"><button className="button secondary" disabled={busy||!a.content} onClick={()=>run('edit',{chain:false})}>生成整体编辑候选</button><button className="text-button" disabled={busy||!a.content} onClick={()=>action('drafts/final')}>记录人工定稿</button><details className="editorial-help"><summary>操作说明</summary><p className="muted">整体编辑可以调整章节与论证。先保存候选并核查，再由你查看差异；人工定稿与 AI 核查通过分别记录。</p></details></div>
 {(a.editorial_candidates||[]).filter(c=>c.status==='pending').map(c=><details key={c.id} className="editorial-candidate"><summary>整体编辑候选 · {c.checked?'已完成复审':'核查尚未完成'} · {new Date(c.created).toLocaleString()}</summary><p>{c.explanation}</p>{c.changes.map((x,i)=><p key={i}>{x}</p>)}<p role="status">{c.checked?(c.review.decision==='pass'?'候选通过当前核查':`候选仍有 ${c.review.issues?.length||0} 项需处理`):'正文已保存为候选，核查完成后可采用。'}</p>{c.review.issues?.map((x:any)=><p className="notice amber" key={x.id}>{x.reason}</p>)}<details><summary>查看完整候选稿</summary><pre className="editorial-text">{c.content}</pre></details><details><summary>逐段查看差异</summary>{c.diff.map((d,i)=>d.kind==='equal'?<details key={i}><summary>未改变的段落</summary><pre className="editorial-text">{d.after}</pre></details>:<div className="editorial-diff" key={i}>{d.before&&<div><strong>修改前</strong><pre className="editorial-text">{d.before}</pre></div>}{d.after&&<div><strong>修改后</strong><pre className="editorial-text">{d.after}</pre></div>}</div>)}</details><div className="row wrap"><button className="button secondary" disabled={busy||!c.checked} onClick={()=>action(`editorial/${c.id}`,{action:'accept'})}>采用整体编辑稿</button><button className="text-button" disabled={busy} onClick={()=>action(`editorial/${c.id}`,{action:'reject'})}>不采用此候选</button></div></details>)}
 {a.draft_versions?.length?<details><summary>稿件记录 · {a.draft_versions.length} 份</summary>{[...a.draft_versions].reverse().map(v=><details key={v.id}><summary>{kinds[v.kind]||v.kind} · {new Date(v.created).toLocaleString()} {v.review_state||''}</summary><pre className="editorial-text">{v.content}</pre></details>)}</details>:null}</section>;
}
