import {useEffect,useRef,useState} from 'react';
import {Search,Upload,Link as LinkIcon,Plus,SlidersHorizontal,Square} from 'lucide-react';
import {api,errorText} from './api';
import {Modal,Busy,Tag,Field} from './ui';
import type {Article,Job} from './types';
import type {Common} from './Panels';
import type {IssueFocus} from './StageContext';
import MaterialList,{readView,remember} from './MaterialList';
import ResearchDetails from './ResearchDetails';
import ReferenceDetails from './ReferenceDetails';
import SourceLimits from './SourceLimits';

export default function Sources({a,save,act,update,run,busy,onJob,job,focusRequest,onFocusHandled,onContext,prepare,navigate}:Common&{job:Job|null;focusRequest?:IssueFocus;onFocusHandled?:()=>void;onContext?:(id:string,explicit?:boolean)=>void}){
 const viewKey='materials-tab:'+a.id;
 const [tab,setTab]=useState(()=>readView(viewKey,{tab:a.research?'results':'materials'}).tab);
 const [focus,setFocus]=useState<{token:number;id?:string}>({token:0}),[summaryOpen,setSummaryOpen]=useState(false);
 const [attachmentIds,setAttachmentIds]=useState<string[]>([]),[mode,setMode]=useState(''),[url,setUrl]=useState(''),[title,setTitle]=useState(''),[text,setText]=useState('');
 const [error,setError]=useState(''),[localBusy,setLocalBusy]=useState(false),[receipt,setReceipt]=useState<any>(null),[inspect,setInspect]=useState<string|null>(null);
 const limits=a.research_limits;const [limitsOpen,setLimitsOpen]=useState(false);
 const file=useRef<HTMLInputElement>(null),retry=useRef<(()=>Promise<void>)|null>(null),handled=useRef(''),mounted=useRef(true),cancelRequested=useRef(false);
 const currentImport=job?.stage==='source_import'&&job.article_id===a.id?job:null;
 const importing=!!currentImport&&['queued','running'].includes(currentImport.status);
 const executing=!!job&&['sources','research','bound','source_import'].includes(job.stage)&&job.article_id===a.id&&['running','queued'].includes(job.status);
 const state=a.materials_state;
 const currentApplications=(a.research?.issues||[]).filter(x=>x.application?.job_id===job?.id);
 const changedApplications=job?.result?.applications&&currentApplications.length!==job.result.applications.length;
 const selectTab=(next:string)=>{void act(async()=>{await prepare();setTab(next);remember(viewKey,{tab:next})})};
 const locate=(id?:string)=>{setTab('results');remember(viewKey,{tab:'results'});setFocus({token:Date.now(),id})};
 useEffect(()=>{mounted.current=true;return()=>{mounted.current=false}},[]);
 useEffect(()=>{if(focusRequest?.token){locate(focusRequest.id);onFocusHandled?.()}},[focusRequest?.token]);
 useEffect(()=>{const el=file.current;const cancel=()=>setAttachmentIds([]);el?.addEventListener('cancel',cancel);return()=>el?.removeEventListener('cancel',cancel)},[]);
 useEffect(()=>{
  if(!currentImport||['running','queued'].includes(currentImport.status)||handled.current===currentImport.id)return;
  handled.current=currentImport.id;
  if(currentImport.status==='completed'){setReceipt(currentImport.result);setMode('');setAttachmentIds([]);setUrl('');setError('');const ids=currentImport.result?.issue_ids||[];if(ids.length)locate(ids[0]);else setTab('materials')}
  else if(currentImport.status!=='cancelled'){setError(currentImport.message);setMode('import')}
 },[currentImport?.id,currentImport?.status]);
 async function perform(fn:()=>Promise<void>){setLocalBusy(true);setError('');try{await fn()}catch(e){if(mounted.current)setError(errorText(e))}finally{if(mounted.current)setLocalBusy(false)}}
 async function begin(kind:'url'|'file'|'identify',f?:File,sid?:string){
  const ids=[...attachmentIds];setReceipt(null);setMode('import');cancelRequested.current=false;
  const task=async()=>{const current=await prepare();let next:Job;
   if(kind==='file'){const body=new FormData();body.append('file',f!);body.append('revision',String(current.revision));body.append('issue_ids',JSON.stringify(ids));next=await api('/articles/'+a.id+'/source-imports/file','POST',body)}
   else next=await api('/articles/'+a.id+(kind==='identify'?'/sources/'+sid+'/identify':'/source-imports'),'POST',{revision:current.revision,url,issue_ids:ids});
   if(cancelRequested.current||!mounted.current){next=await api('/jobs/'+next.id+'/cancel','POST');if(mounted.current)onJob(next);return}if(mounted.current){setMode('import');onJob(next)}
  };retry.current=async()=>{cancelRequested.current=false;await task()};await perform(task);
 }
 async function close(){cancelRequested.current=true;if(importing){await perform(async()=>{const next=await api<Job>('/jobs/'+currentImport!.id+'/cancel','POST');onJob(next);if(next.status==='completed')update(await api('/articles/'+a.id))})}setMode('');setAttachmentIds([]);setError('')}
 const openMode=(next:string,ids:string[]=[])=>{setAttachmentIds(ids);setError('');setReceipt(null);setMode(next)};
 async function verifyNew(){await run('research',{issue_ids:receipt?.issue_ids||[],research_limits:limits,chain:false});setReceipt(null)}
 const primary=()=>{locate();void run('research',{research_limits:limits,chain:false})};
 const primaryLabel='查找并整理资料';
 const summary=a.research?.summary||a.evidence.summary;
 return <>
  <section className="material-status" aria-label="资料状态" role="status"><div className="row between"><strong>{importing?currentImport!.message:state?.message||'先检查已有材料，再按需查找'}</strong><button className="text-button" onClick={()=>setLimitsOpen(true)}><SlidersHorizontal size={14}/>检索设置</button></div>
   {importing?<div className="row between"><Busy text={importing?'正在导入资料':'正在处理本次任务'}/><button className="text-button" onClick={()=>void perform(async()=>onJob(await api('/jobs/'+job!.id+'/cancel','POST')))}><Square size={12}/>停止</button></div>:state?.delta&&<p className="muted">上次核实：新增 {state.delta.added_sources} 条素材 · 解决 {state.delta.resolved} 项建议 · 剩余 {state.delta.remaining} 项高优先级建议</p>}
   {!executing&&state?.stop_reason&&<p className="muted">{state.stop_reason}</p>}
   <p className="muted">已采用 {a.sources.filter(s=>s.selected).length} / {a.sources.length} 条素材{state?.pending?.length?` · ${state.pending.length} 项建议待处理，继续创作时保留限定`:''}</p>
  </section>
  {!executing&&job?.stage==='bound'&&job.result?.applications&&<div className="source-receipt" role="status"><strong>{changedApplications?'本次处理已有撤销或更新，请以当前问题状态为准':job.message}</strong>{!changedApplications&&<p>已保存 {job.result.applications.length} 项决定 · 正文／大纲修改 {job.result.changed||0} 处 · 仍有 {job.result.remaining||0} 项需处理</p>}<button className="text-button" onClick={()=>locate(job.result.applications[0]?.issue_id)}>查看本次改动</button></div>}
  {(state?.new_source_ids?.length||0)>0&&!receipt&&<button className="button secondary" disabled={busy} onClick={()=>void verifyNew()}>核实新增资料</button>}
  {a.creative_intent?.direction_change&&<div className="notice amber"><span>原定方向需要核对：{a.creative_intent.direction_change}</span><button className="text-button" onClick={()=>navigate('topic')}>查看选题</button></div>}
  <div className="source-search"><Search size={18}/><Field autoSave label="补充检索要求" value={a.input_drafts?.source_query||""} onCommit={v=>save(current=>({input_drafts:{...current.input_drafts,source_query:v}}))} placeholder="可选：补充需要查证的问题…"/><button className="button primary" disabled={busy||localBusy||!a.brief.topic} onClick={primary}>{primaryLabel}</button></div>
  <div className="row wrap source-actions"><button className="button secondary" disabled={busy||localBusy} onClick={()=>{setAttachmentIds([]);file.current?.click()}}><Upload size={15}/>上传文件</button><button className="button secondary" disabled={busy||localBusy} onClick={()=>openMode('url')}><LinkIcon size={15}/>添加链接</button><button className="button secondary" disabled={busy||localBusy} onClick={()=>openMode('text')}><Plus size={15}/>粘贴文字</button>{<button className="text-button" disabled={localBusy||a.workflow?.outline?.allowed===false} onClick={()=>navigate('outline')}>进入大纲</button>}<span className="muted">PDF / Word / Markdown / TXT / BibTeX / RIS · 20 MB 内</span></div>
  <input ref={file} type="file" hidden accept=".pdf,.docx,.md,.txt,.bib,.ris" onChange={e=>{const f=e.target.files?.[0];if(f)void begin('file',f);e.target.value=''}}/>
  {receipt&&<div className="source-receipt" role="status"><strong>资料已添加，等待核实</strong>{receipt.sources?.map((s:any)=><p key={s.source_id}>{s.title} · {s.operation==='updated'?'已有素材已更新':'已加入'} · {s.scope==='fulltext'?'已取得全文':s.scope==='abstract'?'仅摘要':s.scope==='metadata'?'仅文献信息':'已有正文'}{s.identity_status==='pending'?' · 文献信息待补全':''}</p>)}<div className="row wrap"><button className="button primary" disabled={busy} onClick={()=>void verifyNew()}>核实这批资料</button>{receipt.issue_ids?.length>0&&<button className="text-button" onClick={()=>locate(receipt.issue_ids[0])}>查看对应建议</button>}</div></div>}
  {error&&!mode&&<p className="notice amber" role="alert">{error}</p>}
  <div className="material-tabs" role="tablist" aria-label="素材页面"><button role="tab" aria-selected={tab==='results'} onClick={()=>selectTab('results')}>整理结果</button><button role="tab" aria-selected={tab==='materials'} onClick={()=>selectTab('materials')}>本篇素材 · {a.sources.length}</button></div>
  <div role="tabpanel" aria-label="整理结果" hidden={tab!=='results'}>{summary?<section className="research-summary"><div className="row between"><h3>当前结论</h3>{a.research?.stale&&<Tag tone="amber">相关依据待更新</Tag>}</div><p className={summaryOpen?'':'preview-clamp summary-preview'}>{summary}</p><button className="text-button" aria-expanded={summaryOpen} onClick={()=>setSummaryOpen(v=>!v)}>{summaryOpen?'收起整理总结':'展开完整整理总结'}</button></section>:<p className="muted">尚无整理结论，添加材料后可开始核实；也可以先构建大纲。</p>}
   {a.evidence.claims?.length>0&&<details className="evidence-details"><summary>主张与来源依据</summary>{a.evidence.claims.map((c:any)=><div className="claim" key={c.id}><Tag tone={c.status==='unsupported'||c.stale?'amber':''}>{c.stale?'依据待更新':c.assessment_pending?'适用性待复核':c.status==='unsupported'?'缺少支持':c.status==='bounded'?'适用范围有限':'已有支持记录'}</Tag><p>{c.text}</p><p className="muted">{c.boundary}</p>{c.source_ids.map((id:string)=><button className="text-button source-reference" key={id} onClick={()=>setInspect(id)}>{a.sources.find(s=>s.id===id)?.title||'来源已删除'}</button>)}</div>)}</details>}
   {a.research&&<ResearchDetails a={a} busy={busy||localBusy} act={act} update={update} onJob={onJob} run={run} focus={focus} prepare={prepare} onInspect={setInspect} onSupply={ids=>openMode('supplement',ids)}/>}
  </div>
  <div role="tabpanel" aria-label="本篇素材" hidden={tab!=='materials'}><MaterialList key={a.id} a={a} save={save} busy={busy||localBusy} act={act} inspect={setInspect} onContext={onContext} prepare={prepare}/></div>
  {mode&&<Modal title={mode==='supplement'?'为建议补充资料':mode==='text'?'添加文字素材':mode==='import'?'导入资料':'添加网页资料'} onClose={()=>void close()}>
   {mode==='supplement'?<><p className="modal-intro">材料将关联所选建议，添加成功后可以直接核实。</p><div className="row wrap"><button className="button secondary" onClick={()=>{setMode('');file.current?.click()}}>上传文件</button><button className="button secondary" onClick={()=>setMode('url')}>添加链接</button><button className="button secondary" onClick={()=>setMode('text')}>粘贴文字</button></div></>:mode==='import'?<><p>{currentImport?.message||'准备导入'}</p>{importing&&<Busy text={'已用 '+Math.max(0,Math.floor((Date.now()-Date.parse(currentImport!.created))/1000))+' 秒'}/>}<div className="modal-footer"><button className="button secondary" onClick={()=>void close()}>{importing?'取消导入':'关闭'}</button>{!importing&&url&&<button className="text-button" onClick={()=>{setError('');setMode('url')}}>修改链接</button>}{!importing&&retry.current&&<button className="button primary" disabled={localBusy||busy} onClick={()=>void perform(retry.current!)}>重试导入</button>}</div></>:<>
    {mode==='url'?<label className="field"><span>网页链接</span><input aria-label="网页链接" value={url} onChange={e=>setUrl(e.target.value)} placeholder="https://…"/></label>:<><label className="field"><span>素材名称</span><input value={title} onChange={e=>setTitle(e.target.value)}/></label><label className="field"><span>素材正文</span><textarea value={text} onChange={e=>setText(e.target.value)} rows={8}/></label></>}
    <div className="modal-footer"><span className="muted">仅用于本篇文章</span><button className="button primary" disabled={busy||localBusy||(mode==='url'?!url.trim():!text.trim())} onClick={()=>mode==='url'?void begin('url'):void perform(async()=>{const current=await prepare();const next=await api<Article>('/articles/'+a.id+'/sources/text','POST',{revision:current.revision,title,text,issue_ids:attachmentIds});if(!mounted.current)return;update(next);setReceipt({sources:[{source_id:'text',title:title||'文字素材',operation:'added',scope:'file'}],issue_ids:attachmentIds});if(attachmentIds.length)locate(attachmentIds[0]);setMode('');setAttachmentIds([]);setText('')})}>{localBusy?<Busy text="正在保存"/>:'添加素材'}</button></div>
   </>}{error&&<p className="notice amber" role="alert">{error}</p>}
  </Modal>}
  {limitsOpen&&<SourceLimits a={a} initial={limits} busy={busy} onClose={()=>setLimitsOpen(false)} onApply={async(value,go)=>{await prepare();const current=await save({research_limits:value},'preferences');if(go){await run('research',{research_limits:value,research_parent_id:current.research?.job_id||'',issue_ids:state?.required.map(i=>i.id)||[],chain:false});locate()}}}/>}
  {inspect&&a.sources.find(s=>s.id===inspect)&&<ReferenceDetails key={inspect} source={a.sources.find(s=>s.id===inspect)!} onClose={()=>setInspect(null)} onSave={s=>save(current=>({sources:current.sources.map(x=>x.id===s.id?{...x,bibliography:s.bibliography}:x)}),'sources')} onIdentify={()=>{const id=inspect;setInspect(null);return begin('identify',undefined,id)}} onLookup={async doi=>{const current=await prepare();update(await api(`/articles/${a.id}/sources/${inspect}/metadata`,'POST',{revision:current.revision,doi}))}}/>}
 </>;
}
