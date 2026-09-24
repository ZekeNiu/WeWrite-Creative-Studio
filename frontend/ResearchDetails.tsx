import {useEffect,useRef,useState} from 'react';
import {api} from './api';
import {type Article,type Job,LABELS,type ResearchStats,type ResearchIssue} from './types';
import SearchStrategy from './SearchStrategy';
import ResearchTrace from './ResearchTrace';
import {Pager,readView,remember} from './MaterialList';

const STATUS:Record<string,string>={needs_input:'待处理',completed:'已完成',failed:'未完成',cancelled:'已停止',interrupted:'运行中断',conflict:'内容已变化，需重新开始',queued:'等待执行',running:'进行中'};
const APPLICATION={applied:'正文／大纲已更新',partial:'部分已更新，仍有位置待处理',pending:'约束已保存，现有稿件仍待处理',not_needed:'约束已保存，目前没有稿件需要修改'};
const COVERAGE:Record<string,string>={supported:'已有支持',limited:'有限支持',contradicted:'发现反证',unresolved:'尚未解决'};
function category(x:ResearchIssue){if(x.application_state==='partial'||x.application_state==='pending')return 'pending';if(['open','stale'].includes(x.status))return x.kind==='limitation'?'boundaries':'pending';return 'handled'}
function Activity({r}:{r:any}){
 const s:ResearchStats|undefined=r.stats;
 return <>{s?<><p>{s.search_requests===0?(s.search_cache_hits?'本次复用已有检索结果':'本次仅核对已有材料'):`本次新增搜索 ${s.search_requests} 次`} · 检查已有材料 {s.existing_checked} 条</p><p>搜索缓存复用 {s.search_cache_hits} 次 · 网页读取尝试 {s.page_attempts} 次 · 页面缓存复用 {s.page_cache_hits} 次</p><p>取得全文 {s.fulltext} 篇 · 取得摘要 {s.abstracts} 篇 · 文献信息查询 {s.metadata_requests} 次（缓存 {s.metadata_cache_hits} 次）</p></>:<p>旧版记录：{r.calls??0} 次调用，{r.pages??0} 次读取计数。</p>}{s&&s.version>=2&&<p>供应商内部子查询 {s.provider_queries??0} 次（与搜索请求分别记录）</p>}<ResearchTrace value={r}/><details><summary>策略与执行记录</summary><SearchStrategy value={r.strategy}/>{r.plan?.reason&&<p>{r.plan.reason}</p>}{r.log?.map((x:any,i:number)=><p key={i}>{x.message} {x.query} {x.reason} {x.provider_queries?.join("；")}</p>)}</details></>;
}

export default function ResearchDetails({a,busy,act,update,onJob,run,onSupply,focus,prepare,onInspect}:{a:Article;busy:boolean;act:(fn:()=>Promise<void>)=>Promise<void>;update:(a:Article)=>void;onJob:(j:Job)=>void;run:(stage:string,extra?:Record<string,unknown>)=>Promise<void>;onSupply:(ids:string[])=>void;onInspect:(id:string)=>void;focus?:{token:number;id?:string};prepare:()=>Promise<Article>}){
 const [history,setHistory]=useState<any[]>([]),[error,setError]=useState(''),[selected,setSelected]=useState<string[]>([]);const lock=useRef(false),root=useRef<HTMLDivElement>(null);
 const key='materials-issues:'+a.id;const [view,setView]=useState(()=>readView(key,{filter:'pending',page:1,open:[] as string[]}));
 const change=(patch:Partial<typeof view>)=>{if(patch.filter!==undefined||patch.page!==undefined)setSelected([]);setView(old=>{const next={...old,...patch};remember(key,next);return next})};
 const r=a.research,rows=[...(r?.issues||[])].sort((x,y)=>Number(y.priority==='high')-Number(x.priority==='high'));
 useEffect(()=>{setSelected([]);let active=true;void api<any[]>(`/articles/${a.id}/research/history`).then(v=>{if(active){setHistory(v);setError('')}}).catch(e=>{if(active)setError(String(e))});return()=>{active=false}},[a.id,r?.job_id,a.revision]);
 useEffect(()=>{if(!focus?.token)return;const issue=rows.find(x=>x.id===focus.id)||rows.find(x=>category(x)==='pending');if(issue){const filter=category(issue),items=rows.filter(x=>category(x)===filter);change({filter,page:Math.floor(items.findIndex(x=>x.id===issue.id)/10)+1,open:[...new Set([...view.open,issue.id])]});setTimeout(()=>root.current?.querySelector('[data-issue="'+CSS.escape(issue.id)+'"]')?.scrollIntoView({block:'nearest',behavior:'smooth'}),0)}},[focus?.token]);
 if(!r)return null;
 const filtered=rows.filter(x=>category(x)===view.filter),page=Math.min(view.page,Math.max(1,Math.ceil(filtered.length/10))),visible=filtered.slice((page-1)*10,page*10);
 const eligible=visible.filter(x=>['open','stale'].includes(x.status)&&x.kind==='blocking').map(x=>x.id);
 const action=(kind:string,ids:string[])=>{if(lock.current||busy)return;if(kind==='attach'){onSupply(ids);return}lock.current=true;void act(async()=>{const current=await prepare();const result=await api<{article:Article;job:Job|null}>(`/articles/${a.id}/research/issues/actions`,'POST',{revision:current.revision,issue_ids:ids,action:kind==='bound'?'bound_auto':kind,action_id:crypto.randomUUID()});update(result.article);if(result.job)onJob(result.job)}).finally(()=>{lock.current=false})};
 return <div className="research-details" ref={root}>
 {r.coverage?.length?<section className="service-card" aria-label="核心问题覆盖"><h4>核心问题与依据</h4><p role="status">{r.stale?'文章目标或依据已变化，以下是历史核对结果':r.coverage_sufficient?'各核心问题已有可定位依据，请保留反证和适用条件':'部分核心问题尚未解决；你仍可继续创作，但不能将它们视为已核实'}</p>{r.coverage.map(q=><details key={q.question_id}><summary>{q.required?'核心':'补充'} · {COVERAGE[q.status]||'待复核'} · {q.question}</summary><p>{q.reason}</p>{q.source_ids.map(id=><button className="text-button" key={id} onClick={()=>onInspect(id)}>{a.sources.find(s=>s.id===id)?.title||'来源已删除'}</button>)}</details>)}</section>:<p className="muted">这份记录尚无逐问题独立核查结果；继续创作不等于所有主张已核实。</p>}
 {rows.length>0&&<>
  <div className="row between"><h4>创作建议</h4><span className="muted">建议不阻止创作；研究局限作为写作条件保留</span></div>
  <div className="material-toolbar wrap">{[['pending','待处理'],['handled','已处理'],['boundaries','写作边界']].map(([id,label])=><button key={id} className={'button '+(view.filter===id?'secondary':'ghost')} aria-pressed={view.filter===id} onClick={()=>change({filter:id,page:1})}>{label} · {rows.filter(x=>category(x)===id).length}</button>)}</div>
  {view.filter==='pending'&&eligible.length>0&&<div className="material-toolbar wrap"><label><input type="checkbox" aria-label="全选当前页待处理项" disabled={busy} checked={eligible.every(id=>selected.includes(id))} onChange={e=>setSelected(e.target.checked?eligible:[])}/>全选当前页待核实项</label><span className="muted">已选 {selected.length} 项</span><button className="button secondary" disabled={busy||!selected.length} onClick={()=>action('verify',selected)}>核实所选问题（{selected.length}）</button><button className="text-button" disabled={busy||!selected.length||r.stale} onClick={()=>action('exclude',selected)}>本篇不使用所选主张（{selected.length}）</button></div>}
  {view.filter==='boundaries'&&<p className="muted">这些条件应在写作中保留，无需为清空待办反复查找。</p>}
  {!filtered.length&&<p className="muted">此分类暂无问题。</p>}
  {visible.map(x=>{const open=view.open.includes(x.id),decided=['waived','bounded','excluded'].includes(x.status);return <article className="advice-row research-issue" data-issue={x.id} key={x.id}>
   <div className="row">{eligible.includes(x.id)&&<input type="checkbox" disabled={busy} aria-label={'准备批量处理：'+x.text} checked={selected.includes(x.id)} onChange={e=>setSelected(v=>e.target.checked?[...v,x.id]:v.filter(id=>id!==x.id))}/>}<strong>{x.status==='excluded'?'本篇不使用':decided?'采用有边界表述':x.status==='stale'?'相关依据已变化':x.status==='resolved'?'已核实':x.kind==='limitation'?'写作条件':'需要核实'}</strong><button className="text-button" aria-expanded={open} onClick={()=>change({open:open?view.open.filter(id=>id!==x.id):[...view.open,x.id]})}>{open?'收起问题':'展开问题'}</button></div>
   <p className={open?'':'preview-clamp'}>{x.text}</p>
   {x.application_state&&<p role="status" className={'notice '+(['pending','partial'].includes(x.application_state)?'amber':'')}>{APPLICATION[x.application_state]}{x.application?` · 修改 ${x.application.edits.length} 处 · 未定位 ${x.application.unapplied.length} 处`:''}</p>}
   {open&&<>{x.wording&&<p>后续写作约束：{x.wording}</p>}{x.resolution&&<p className="muted">核实结果：{x.resolution}</p>}<div className="advice-sources">{x.source_ids.map(id=><button className="text-button source-reference" key={id} onClick={()=>onInspect(id)}>{a.sources.find(s=>s.id===id)?.title||'来源已删除'}</button>)}</div>
    {x.application&&<details><summary>查看正文／大纲改动 · {x.application.edits.length} 处</summary><p>{x.application.explanation}</p>{x.application.edits.map((e,i)=><div key={i}><p className="muted">修改前：{e.original}</p><p>修改后：{e.replacement||'（已删除）'}</p></div>)}{x.application.unapplied.map((e,i)=><p className="notice amber" key={i}>未应用：{e.original}{e.reason&&` · ${e.reason}`}</p>)}</details>}
    <div className="row wrap">{decided?<><button className="text-button" disabled={busy} onClick={()=>action('undo',[x.id])}>撤销处理决定</button>{category(x)==='pending'&&<button className="button secondary" onClick={()=>void run('review',{chain:false})} disabled={busy||!a.content}>审核当前正文</button>}</>:x.status==='resolved'?<span className="muted">已有对应原文及适用性评估</span>:<>{x.kind!=='limitation'&&<button className="button secondary" disabled={busy} onClick={()=>action('verify',[x.id])}>AI 核实</button>}<button className="text-button" disabled={busy} onClick={()=>action('bound',[x.id])}>采用限定表述</button>{x.kind!=='limitation'&&<button className="text-button" disabled={busy} onClick={()=>action('exclude',[x.id])}>本篇不使用</button>}<button className="text-button" disabled={busy} onClick={()=>action('attach',[x.id])}>补充资料</button></>}</div>
   </>}
  </article>})}<Pager page={page} total={filtered.length} onChange={page=>change({page})}/>
 </>}
 {r.resume_stage&&['outline','review','topic'].includes(r.resume_stage)&&r.resume_job_id&&!r.pending&&!r.stale&&a.stages[r.resume_stage]!=='done'&&<button className="button primary" disabled={busy||!a.workflow?.[r.resume_stage]?.allowed} onClick={()=>run(r.resume_stage!,{resume_job_id:r.resume_job_id})}>继续{r.resume_stage==='outline'?'生成大纲':LABELS[r.resume_stage]}</button>}
 <details className="research-history"><summary>本次资料核对{r.stale?'（历史结果）':''}</summary><Activity r={r}/></details>
 <details className="research-history"><summary>历次检索与核对 · {history.length} 次任务</summary>{error&&<p role="alert">{error}</p>}{history.map(h=><details key={h.id}><summary>{new Date(h.created).toLocaleString()} · {LABELS[h.stage]||h.stage} · {STATUS[h.status]||h.status}</summary><Activity r={h.research}/></details>)}</details>
 </div>;
}
