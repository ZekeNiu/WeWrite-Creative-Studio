import {useRef,useState} from 'react';
import {ChevronDown,ExternalLink,FileText,Trash2} from 'lucide-react';
import type {Article,Save} from './types';
import {Field,Tag} from './ui';

export function readView<T>(key:string,fallback:T):T{try{return {...fallback,...JSON.parse(sessionStorage.getItem(key)||'{}')}}catch{return fallback}}
export function remember(key:string,value:unknown){try{sessionStorage.setItem(key,JSON.stringify(value))}catch{/* Browsing still works without storage. */}}
export function Pager({page,total,onChange}:{page:number;total:number;onChange:(p:number)=>void}){
 const pages=Math.max(1,Math.ceil(total/10));return <div className="material-pager"><span>共 {total} 条 · 第 {page} / {pages} 页</span><button className="button secondary" disabled={page<=1} onClick={()=>onChange(page-1)}>上一页</button><button className="button secondary" disabled={page>=pages} onClick={()=>onChange(page+1)}>下一页</button></div>
}

export default function MaterialList({a,save,busy,act,inspect}:{a:Article;save:Save;busy:boolean;act:(fn:()=>Promise<void>)=>Promise<void>;inspect:(id:string)=>void}){
 const key='materials-list:'+a.id;
 const [view,setView]=useState(()=>readView(key,{query:'',filter:'all',page:1,open:[] as string[]}));
 const lock=useRef(false);const [saving,setSaving]=useState(false);const disabled=busy||saving;
 const change=(patch:Partial<typeof view>)=>setView(old=>{const next={...old,...patch};remember(key,next);return next});
 const rows=a.sources.filter(s=>(view.filter==='all'||(view.filter==='selected'?s.selected:!s.selected))&&(s.title+' '+s.summary).toLocaleLowerCase().includes(view.query.trim().toLocaleLowerCase()));
 const page=Math.min(view.page,Math.max(1,Math.ceil(rows.length/10)));const visible=rows.slice((page-1)*10,page*10);
 async function commit(ids:string[],patch:Record<string,unknown>,remove=false){
  if(lock.current||busy)return;lock.current=true;setSaving(true);
  try{await act(async()=>{await save({sources:a.sources.filter(s=>!remove||!ids.includes(s.id)).map(s=>({id:s.id,...(ids.includes(s.id)?patch:{})})) as Article['sources']},'sources')})}
  finally{lock.current=false;setSaving(false)}
 }
 return <><div className="material-toolbar"><input aria-label="搜索本篇素材" placeholder="搜索标题或摘要" value={view.query} onChange={e=>change({query:e.target.value,page:1})}/><select aria-label="素材采用筛选" value={view.filter} onChange={e=>change({filter:e.target.value,page:1})}><option value="all">全部素材</option><option value="selected">已采用</option><option value="excluded">未采用</option></select></div>
 <div className="material-toolbar wrap"><span className="muted">全部筛选结果 {rows.length} 条（含其他页）</span><button className="text-button" disabled={disabled||!rows.some(s=>!s.selected)} onClick={()=>commit(rows.map(s=>s.id),{selected:true})}>全部采用</button><button className="text-button" disabled={disabled||!rows.some(s=>s.selected)} onClick={()=>commit(rows.map(s=>s.id),{selected:false})}>全部不采用</button><button className="text-button" disabled={!visible.length} onClick={()=>change({open:[...new Set([...view.open,...visible.map(s=>s.id)])]})}>展开本页</button><button className="text-button" disabled={!visible.length} onClick={()=>change({open:view.open.filter(id=>!visible.some(s=>s.id===id))})}>收起本页</button></div>
 {!rows.length&&<p className="muted">{a.sources.length?'没有符合筛选条件的素材。':'还没有素材，可以上传文件、添加链接或粘贴文字。'}</p>}
 <div className="source-list">{visible.map(s=>{const open=view.open.includes(s.id);const manual=!!s.use?.trim();const use=manual?s.use:s.ai_use_current?s.ai_use?.text:'';return <article key={s.id} className={'source-card compact-source '+(!s.selected?'excluded':'')}>
 <div className="row"><input type="checkbox" aria-label={'采用 '+s.title} disabled={disabled} checked={s.selected} onChange={e=>commit([s.id],{selected:e.target.checked})}/><FileText size={18}/><button className="source-title grow" aria-expanded={open} aria-controls={'source-'+s.id} onClick={()=>change({open:open?view.open.filter(id=>id!==s.id):[...view.open,s.id]})}>{s.title}<ChevronDown size={16} className={open?'rotated':''}/></button><button className="text-button" onClick={()=>inspect(s.id)}>引用详情</button>{s.url&&<a href={s.url} target="_blank" rel="noreferrer" className="icon-button" title="查看原网页"><ExternalLink size={16}/></a>}<button className="icon-button" disabled={disabled} title="移除素材" onClick={()=>commit([s.id],{},true)}><Trash2 size={15}/></button></div>
 <div className="row wrap material-tags"><Tag>{s.status==='metadata_only'?'仅文献信息':s.status==='abstract_only'?'研究摘要':s.status==='excerpt_only'?'搜索片段':s.status==='unreadable'?'无法读取':s.kind==='user'?'用户提供':'已读正文'}</Tag>{s.personal_material&&<Tag>已授权个人经历</Tag>}<small className="muted">{s.id}</small></div>
 <p className={open?'':'preview-clamp'}>{s.summary||'暂无摘要'}</p><p className="material-use preview-clamp"><strong>{manual?'人工指定':s.ai_use_current?'AI 判断':s.ai_use?'用途待更新':'素材用途'}：</strong>{use||(s.ai_use?'主题或材料已改变，重新整理后更新用途。':'整理后自动判断用途')}</p>
 {open&&<div id={'source-'+s.id} className="material-expanded"><fieldset disabled={disabled}><Field label="这份素材的用途" value={s.use||''} placeholder={s.ai_use_current?s.ai_use?.text:'可选：人工指定用途，优先于 AI 判断'} hint="留空时采用当前有效的 AI 判断；用途不代表事实已经核实。" onCommit={use=>commit([s.id],{use})}/>{manual&&<button className="text-button" onClick={()=>commit([s.id],{use:''})}>恢复 AI 判断</button>}{s.ai_use&&!s.ai_use_current&&<details><summary>查看历史 AI 用途</summary><p>{s.ai_use.text}</p></details>}{s.kind==='user'&&<div className="experience-consent"><strong>个人经历授权</strong><label><input type="checkbox" checked={!!s.personal_material} onChange={e=>commit([s.id],{personal_material:e.target.checked})}/>这是我的真实经历，可用于第一人称叙述</label><small className="muted">上传的论文、范文或他人经历不等于你的亲身经历。AI 不会自动开启此项。</small></div>}</fieldset></div>}</article>})}</div><Pager page={page} total={rows.length} onChange={page=>change({page})}/></>
}
