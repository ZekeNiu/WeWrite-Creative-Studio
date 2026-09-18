import {useEffect,useState} from 'react';
import {api} from './api';
import {type Article,type Job,LABELS,type ResearchStats} from './types';
import SearchStrategy from './SearchStrategy';

function Activity({r}:{r:any}){
 const s:ResearchStats|undefined=r.stats;
 return <>{s?<><p>{s.search_requests===0?(s.search_cache_hits?'本次复用已有检索结果':'本次仅核对已有材料'):`本次新增搜索 ${s.search_requests} 次`} · 检查已有材料 {s.existing_checked} 条</p><p>搜索缓存复用 {s.search_cache_hits} 次 · 网页读取尝试 {s.page_attempts} 次 · 页面缓存复用 {s.page_cache_hits} 次</p><p>取得全文 {s.fulltext} 篇 · 取得摘要 {s.abstracts} 篇 · 文献信息查询 {s.metadata_requests} 次（缓存 {s.metadata_cache_hits} 次）</p></>:<p>旧版记录：{r.calls??0} 次调用（可能含文献信息查询），{r.pages??0} 次读取计数；未分别记录成功篇数。</p>}<details><summary>策略与执行记录</summary><SearchStrategy value={r.strategy}/>{r.plan?.reason&&<p>本次判断：{r.plan.reason}</p>}{r.log?.map((x:any,i:number)=><p key={i}>{x.message} {x.query} {x.reason}</p>)}</details></>;
}

export default function ResearchDetails({a,busy,act,update,onJob,run,onSupply}:{a:Article;busy:boolean;act:(fn:()=>Promise<void>)=>Promise<void>;update:(a:Article)=>void;onJob:(j:Job)=>void;run:(stage:string,extra?:Record<string,unknown>)=>Promise<void>;onSupply:()=>void}){
 const [history,setHistory]=useState<any[]>([]);const [error,setError]=useState('');
 const [selected,setSelected]=useState<string[]>([]);
 const r=a.research;const rows=r?.issues||[];
 useEffect(()=>{setSelected([]);void api<any[]>(`/articles/${a.id}/research/history`).then(setHistory).catch(e=>setError(String(e)))},[a.id,r?.job_id,a.revision]);
 if(!r)return null;
 const action=(kind:string,ids:string[])=>act(async()=>{const result=await api<{article:Article;job:Job|null}>(`/articles/${a.id}/research/issues/actions`,'POST',{revision:a.revision,issue_ids:ids,action:kind,action_id:crypto.randomUUID()});update(result.article);if(result.job)onJob(result.job);if(kind==='attach')onSupply()});
 const target=r.resume_stage||r.stage;const resume=r.resume_job_id||r.job_id;
 return <div className="research-details">{rows.length>0&&<><div className="row between"><h4>核实与写作边界{r.stale?'（材料已改变，需重新核实）':''}</h4><span className="muted">忽略不等于证实</span></div><div className="row wrap"><button className="button secondary" disabled={busy||!selected.length} onClick={()=>action('verify',selected)}>核实所选问题</button><button className="button secondary" disabled={busy||!selected.length||r.stale} onClick={()=>action('waive',selected)}>忽略所选并保留边界</button></div>{rows.map(x=><article className="research-issue" key={x.id}><label className="row"><input type="checkbox" disabled={busy||x.status==='resolved'} aria-label={'选择问题：'+x.text} checked={selected.includes(x.id)} onChange={e=>setSelected(v=>e.target.checked?[...v,x.id]:v.filter(id=>id!==x.id))}/><strong>{x.status==='waived'?'已忽略，保留边界':x.status==='resolved'?'已核实':x.kind==='blocking'?'需要处理':'写作时保留的局限'}</strong></label><p>{x.text}</p>{x.resolution&&<p className="muted">核实结果：{x.resolution}</p>}<div className="row wrap">{x.status==='resolved'?<span className="muted">已找到对应原文依据</span>:x.status==='waived'?<button className="text-button" disabled={busy||r.stale} onClick={()=>action('undo',[x.id])}>撤销忽略</button>:<><button className="button secondary" disabled={busy} onClick={()=>action('verify',[x.id])}>AI 核实</button><button className="text-button" disabled={busy||r.stale} onClick={()=>action('waive',[x.id])}>忽略并继续</button><button className="text-button" disabled={busy} onClick={()=>action('attach',[x.id])}>补充资料</button></>}</div></article>)}</>}
 {target&&['outline','review','topic'].includes(target)&&resume&&!r.pending&&!r.stale&&a.stages[target]!=='done'&&<button className="button primary" disabled={busy||!a.workflow?.[target]?.allowed} onClick={()=>run(target,{resume_job_id:resume})}>继续{target==='outline'?'生成大纲':LABELS[target]}</button>}
 <details className="research-history"><summary>本次资料核对{r.stale?'（历史结果）':''}</summary><Activity r={r}/></details>
 <details className="research-history"><summary>历次检索与核对 · {history.length} 次任务</summary>{error&&<p role="alert">{error}</p>}{history.map(h=><details key={h.id}><summary>{new Date(h.created).toLocaleString()} · {LABELS[h.stage]||h.stage} · {h.status==='needs_input'?'待处理':h.status==='completed'?'已完成':h.status==='failed'?'未完成':h.status==='cancelled'?'已停止':'进行中'}</summary><Activity r={h.research}/></details>)}</details>
 </div>;
}
