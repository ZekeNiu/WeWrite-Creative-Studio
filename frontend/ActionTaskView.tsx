import {JOB_STATUS} from './TaskStatus';
import {date} from './api';
import {Busy} from './ui';
import NativeTrace from './NativeTrace';
import type {Job} from './types';
import type {ActionTask} from './useActionTask';

export const ACTION_LABELS:Record<string,string>={rewrite:'多平台改写',theme:'学习排版',publish:'微信草稿推送',image_post:'图片帖草稿推送',stats:'在线效果',stats_review:'效果复盘',draft_read:'读取草稿副本'};
function download(name:string,text:string){const url=URL.createObjectURL(new Blob([text],{type:'text/markdown;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
function Outputs({job:j}:{job:Job}){
 return <>{!!j.external_receipt&&<details><summary>微信请求回执</summary><pre className="editorial-text">{JSON.stringify(j.external_receipt,null,2)}</pre></details>}
  {j.result?.outputs?.map((x:any)=><details key={x.platform}><summary>{x.platform==='xiaohongshu'?'小红书':'抖音'} · {x.characters} 字 · 质量提示 {x.quality_score}</summary><pre className="editorial-text">{x.content}</pre><button className="button secondary" onClick={()=>download(x.filename,x.content)}>下载平台稿</button></details>)}
  {j.result?.max_similarity!==undefined&&<p>与源稿／其他平台最大相似度：{j.result.max_similarity} · {j.result.needs_input?'仍需处理':'通过数值检查'}</p>}
  {j.result?.content&&<><pre className="editorial-text">{j.result.content}</pre><button className="button secondary" onClick={()=>download(j.stage==='draft_read'?'微信草稿副本.md':'效果复盘.md',j.result.content)}>下载副本</button></>}
  {j.partial&&!j.result?.content&&!['queued','running','completed'].includes(j.status)&&<details><summary>保留的分析结果</summary><pre className="editorial-text">{j.partial}</pre></details>}
  {j.result?.media_id&&<p>微信草稿编号：<code>{j.result.media_id}</code>；请到公众号草稿箱查看。</p>}
  {j.result?.rows&&<><p>已匹配 {j.result.matched??0} 条统计；未关联的条目不会按标题自动回填。</p>{j.result.unmatched?.map((x:any)=><p key={x.msgid}>{x.title} · 微信文章编号 {x.msgid}</p>)}</>}
  {j.result?.theme&&<p>主题已加入排版下拉框：{j.result.theme}</p>}
 </>;
}
export default function ActionTaskView({task:t}:{task:ActionTask}){
 const current=t.records.active.length?t.records.active:t.job?[t.job]:[];
 return <div className="action-task-view">
  {t.error&&<p className="notice amber" role="alert">{t.error}<button className="text-button" disabled={t.pending} onClick={()=>void t.act(()=>t.reload())}>刷新当前功能</button></p>}
  {!t.data&&<Busy/>}
  {current.map(j=><div className="notice" key={j.id}><p><strong>{ACTION_LABELS[j.stage]||'任务'} · {JOB_STATUS[j.status]}</strong></p><p>{['queued','running'].includes(j.status)?<Busy text={j.message}/>:j.message}</p>{['queued','running'].includes(j.status)&&<button className="button secondary" disabled={t.pending} onClick={()=>void t.act(()=>t.cancel(j.id))}>停止此任务</button>}<Outputs job={j}/>{j.native?.id&&<NativeTrace job={j}/>}</div>)}
  {!!t.records.total&&<details className="action-history"><summary>任务记录 · {t.records.total} 条</summary>{t.records.items.filter(j=>!current.some(c=>c.id===j.id)).map(j=><details key={j.id}><summary>{ACTION_LABELS[j.stage]} · {date(j.created)} · {JOB_STATUS[j.status]}</summary><p>{j.message}</p><Outputs job={j}/>{j.native?.id&&<NativeTrace job={j}/>}</details>)}<div className="row wrap"><button className="text-button" disabled={t.pending||t.records.page<=1} onClick={()=>void t.act(()=>t.reload(t.records.page-1))}>上一页任务</button><span>{t.records.page} / {Math.max(1,Math.ceil(t.records.total/t.records.page_size))}</span><button className="text-button" disabled={t.pending||t.records.page*t.records.page_size>=t.records.total} onClick={()=>void t.act(()=>t.reload(t.records.page+1))}>下一页任务</button></div></details>}
 </div>;
}
