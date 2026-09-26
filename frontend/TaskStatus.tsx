import {useEffect,useState} from 'react';
import {type Article,type Job,type Stage,type Settings,STAGES,LABELS} from './types';
import {Busy} from './ui';
import {FailureDetails,ResponseDetails,SearchDetails} from './ServiceDetails';

export const JOB_STATUS:Record<string,string>={queued:'等待执行',running:'正在运行',failed:'运行失败',conflict:'结果待核对',interrupted:'运行已中断',cancelled:'已停止',needs_input:'待你确认',completed:'运行完成'};
export function stageOf(stage:string):Stage|undefined{
 const key=({research:'sources',source_import:'sources',bound:'sources',revise:'write',edit:'review',image:'visual',layout_advice:'layout'} as Record<string,string>)[stage]||stage;
 return STAGES.includes(key as Stage)?key as Stage:undefined;
}
export function taskAttention(a:Article,job:Pick<Job,'stage'|'status'>|null|undefined){
 if(!job)return '';
 if(['queued','running','failed','conflict','interrupted'].includes(job.status))return JOB_STATUS[job.status];
 if(job.status!=='needs_input')return '';
 const stage=stageOf(job.stage);
 let pending=!!stage&&a.stages[stage]==='needs_input';
 if(stage==='topic')pending=!a.brief.topic;
 if(stage==='sources')pending=pending||!!a.research?.pending;
 if(job.stage==='revise')pending=pending||!!a.suggestions?.length;
 if(job.stage==='edit')pending=pending||!!a.editorial_candidates?.some(c=>c.status==='pending');
 return pending?'待你确认':'';
}
export function effectiveService(cfg:Settings,stage:string){
 if(stage==='search'){
  const service=cfg.services.find(s=>s.id===(cfg.search.native_service_id||cfg.default_service));
  return {service,model:cfg.search.native_model||service?.model||'',origin:'各环节共用，独立于规划与分析模型'};
 }
 const key=stage==='edit'?'review':stage;
 const own=cfg.routes[key]||{};
 const inherited=key==='research'&&!own.service_id?cfg.routes.sources:undefined;
 const id=own.service_id||inherited?.service_id||cfg.default_service;
 const service=cfg.services.find(s=>s.id===id);
 return {service,model:own.model||inherited?.model||service?.model||'',origin:own.service_id?'本环节单独分配':inherited?.service_id?'继承素材服务':'共享默认服务'};
}
export function StageService({cfg,stage,onSettings}:{cfg:Settings;stage:Stage;onSettings:(stage:string)=>void}){
 if(stage==='layout')return <p className="stage-service">排版预览随保存自动更新</p>;
 return <>{(stage==='sources'?['sources','research','search']:[stage,'search']).map(key=>{
  const {service,model}=effectiveService(cfg,key),label=key==='search'?'联网搜索':key==='research'?'检索规划与整理':key==='sources'?'素材分析':LABELS[key];
  return <div className="stage-service" key={key}><span className="service-name">{label}：{key==='search'&&!cfg.search.enabled?'已关闭':service?`${service.name} · ${model||'未填写模型'}`:'尚未配置模型服务'} </span><button className="text-button" onClick={()=>onSettings(key)}>调整{label}服务</button></div>;
 })}</>;
}
export default function TaskStatus({job,step,busy,onRetry,onSettings,navigate,onCancel}:{job:Job;step:Stage;busy:boolean;onRetry:(j:Job)=>void;onSettings:(stage:string)=>void;navigate:(stage:Stage)=>void;onCancel:()=>void}){
 const [now,setNow]=useState(Date.now());
 const active=['running','queued'].includes(job.status),failed=['failed','conflict','interrupted'].includes(job.status);
 useEffect(()=>{if(!active&&!job.failure?.retry_at)return;const t=setInterval(()=>setNow(Date.now()),1000);return()=>clearInterval(t)},[active,job.failure?.retry_at]);
 const target=stageOf(job.stage);if(!target||job.stage==='source_import')return null;
 const wait=Math.max(0,Math.ceil((Date.parse(job.failure?.retry_at||'')-now)/1000))||0;
 const seconds=Math.max(0,Math.floor((now-Date.parse(job.created))/1000));
 const requestSeconds=job.active_request_started_at?Math.max(0,Math.floor((now-Date.parse(job.active_request_started_at))/1000)):0;
 const completedSeconds=job.last_completed_at?Math.max(0,Math.floor((now-Date.parse(job.last_completed_at))/1000)):0;
 const progress=active&&job.active_request_started_at&&job.active_request_label?`本次${job.active_request_label}已进行 ${requestSeconds} 秒`:active&&job.last_completed_at&&job.last_completed_label?`最近完成：${job.last_completed_label} · ${completedSeconds} 秒前`:'';
 const service=job.failure?.service||job.service;
 const searchFailure=job.failure?.operation==='search'||!!job.failure?.search_diagnostic;
 if(target!==step)return active||failed?<div className="task-brief" role="status"><span>{LABELS[job.stage]}：{JOB_STATUS[job.status]}</span><button className="text-button" onClick={()=>navigate(target)}>查看{LABELS[job.stage]}任务</button></div>:null;
 return <>
 {(active||failed||job.status==='cancelled')&&<section className={'task-status notice '+(active?'active':failed?(job.status==='conflict'?'amber':'error'):'')} aria-label="当前任务状态" role="status">
 <div className="row between wrap"><strong>{LABELS[job.stage]} · {JOB_STATUS[job.status]}</strong>{active&&<button className="button secondary" onClick={onCancel}>停止</button>}</div>
 <p>{active?<Busy text={job.activity||job.message}/>:job.message}</p>
 {service&&<p className="muted">实际调用：{service.name} · {service.model}</p>}
 <p className="muted">{active?`已用 ${seconds} 秒 · `:''}已请求 {job.execution_usage?.requests??0} 次{progress?` · ${progress}`:''}</p>
 {failed&&<><div className="row wrap">{job.stage==='bound'?<span>请回到对应建议重新选择处理方式。</span>:<button className="button secondary" disabled={busy||wait>0} onClick={()=>onRetry(job)}>{wait?`${wait} 秒后可重新运行`:`重新运行${LABELS[job.stage]}`}</button>}{job.stage!=='bound'&&<button className="text-button" disabled={busy} onClick={()=>onSettings(searchFailure?'search':job.stage==='edit'?'review':job.stage)}>调整{searchFailure?'联网搜索':LABELS[job.stage]}服务</button>}</div>
 <p className="muted">重新运行会创建新任务，可能再次计费；保留的文件不表示可从中断处续跑。</p>
 <details><summary>查看错误详情</summary>{job.failure?<><FailureDetails value={job.failure}/>{!job.failure.parameters&&<ResponseDetails value={job.response_diagnostic}/>}</>:<p>历史记录未保存具体原因。</p>}</details></>}
 {!!job.tool_corrections&&<p className="muted">已尝试 {job.tool_corrections} 次工具调用纠正。</p>}{job.partial&&!active&&<details><summary>查看已保留的生成结果</summary><pre className="partial-result">{job.partial}</pre></details>}
 </section>}
 <SearchDetails value={job.search_diagnostic||job.failure?.search_diagnostic}/>
 </>;
}
