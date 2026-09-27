import {useEffect,useRef,useState} from 'react';
import {api} from './api';
import {Modal,Select} from './ui';
import ActionTaskView from './ActionTaskView';
import {useActionTask,type ToolContext} from './useActionTask';
import type {Article} from './types';

function Input({label,value,onChange,multiline=false}:{label:string;value:string;onChange:(v:string)=>void;multiline?:boolean}){
 return <label className="field"><span>{label}</span>{multiline?<textarea aria-label={label} rows={4} value={value} onChange={e=>onChange(e.target.value)}/>:<input aria-label={label} value={value} onChange={e=>onChange(e.target.value)}/>}</label>;
}
type DialogProps=ToolContext&{onClose:()=>void};
export function PersonaDialog({onClose,...context}:DialogProps){
 const task=useActionTask([],context);
 const [value,setValue]=useState({id:'user-'+crypto.randomUUID().slice(0,8),label:'',base:'industry-observer',description:'',opening_style:'',closing_tendency:'',uncertainty_expressions:'',avoid:''});
 return <Modal title="管理自定义人格" wide onClose={onClose}><div className="account-panel">
  <p className="muted">以现有人格为基础保存个人版本；保存后在“写作人格”中选择使用。</p>
  {task.data&&<><Select label="人格基础" value={value.base} onChange={base=>setValue({...value,base})}>{task.data.personas.map(p=><option key={p.id} value={p.id}>{p.name}</option>)}</Select>
   <details><summary>高级：人格编号</summary><Input label="自定义人格编号" value={value.id} onChange={id=>setValue({...value,id})}/></details>
   {([['label','人格显示名称'],['description','人格与语感'],['opening_style','开头方式'],['closing_tendency','收尾倾向'],['uncertainty_expressions','不确定性表达示例（每行一条）'],['avoid','避免的表达（每行一条）']] as const).map(([key,label])=><Input key={key} label={label} value={value[key]} onChange={v=>setValue({...value,[key]:v})} multiline={key!=='label'}/>)}
   <button className="button primary" disabled={task.busy||!value.label||!value.description} onClick={()=>void task.act(async()=>{const d=await task.reload();const definition:any={description:value.description};for(const k of ['opening_style','closing_tendency'] as const)if(value[k])definition[k]=value[k];for(const k of ['uncertainty_expressions','avoid'] as const)if(value[k])definition[k]=value[k].split('\n').filter(Boolean);await api('/extensions/personas','POST',{...value,definition,revision:d.account_revision});await task.reload();await context.refresh()})}>保存自定义人格</button>
   {task.data.custom_personas.map(p=><p key={p.id}>{p.label} · {p.id}<button className="text-button" disabled={task.busy} onClick={()=>setValue({id:p.id,label:p.label,base:p.id,description:p.definition.description,opening_style:p.definition.opening_style||'',closing_tendency:p.definition.closing_tendency||'',uncertainty_expressions:(p.definition.uncertainty_expressions||[]).join('\n'),avoid:(p.definition.avoid||[]).join('\n')})}>编辑人格</button></p>)}
  </>}<ActionTaskView task={task}/>
 </div></Modal>;
}

export function ThemeDialog({onClose,...context}:DialogProps){
 const task=useActionTask(['theme'],context);
 const [value,setValue]=useState({url:'',name:'user-'+crypto.randomUUID().slice(0,8),label:''});
 return <Modal title="从文章学习排版" wide onClose={onClose}><div className="account-panel">
  <p className="muted">读取公开公众号文章中的原始样式，不调用模型。保存后在原有排版下拉框中选择新主题。</p>
  <Input label="公众号排版参考链接" value={value.url} onChange={url=>setValue({...value,url})}/>
  <details><summary>高级：主题编号</summary><Input label="新主题编号" value={value.name} onChange={name=>setValue({...value,name})}/></details>
  <Input label="新主题显示名称" value={value.label} onChange={label=>setValue({...value,label})}/>
  <button className="button primary" disabled={!task.data||task.busy||!value.url||!value.label} onClick={()=>void task.act(()=>task.start('theme',value))}>学习并保存主题</button>
  {task.data?.themes.map(t=><p key={t.id}>{t.label} · {t.id}</p>)}<ActionTaskView task={task}/>
 </div></Modal>;
}

export function RewriteDialog({article,onClose,...context}:DialogProps&{article:Article}){
 const task=useActionTask(['rewrite'],context),[targets,setTargets]=useState(['xiaohongshu','douyin']);
 return <Modal title="多平台改写" wide onClose={onClose}><div className="account-panel">
  <p>当前源稿：{article.title}</p><p className="muted">按目标平台规范改写，保留人格与来源。平台稿独立保存；使用写作模型，调用会计费。</p>
  {task.data?.platforms.map(p=><label className="check" key={p.id}><input type="checkbox" checked={targets.includes(p.id)} onChange={e=>setTargets(e.target.checked?[...targets,p.id]:targets.filter(x=>x!==p.id))}/>{p.label}</label>)}
  <button className="button primary" disabled={!task.data||task.busy||!article.content||!targets.length} onClick={()=>void task.act(()=>task.start('rewrite',{platforms:targets}))}>生成独立平台稿</button><ActionTaskView task={task}/>
 </div></Modal>;
}

export function PublishDialog({article,onClose,onConnection,suspended=false,...context}:DialogProps&{article:Article;onConnection:()=>void;suspended?:boolean}){
 const task=useActionTask(['publish','image_post','draft_read'],context);
 const [kind,setKind]=useState('publish'),[digest,setDigest]=useState(''),[description,setDescription]=useState(''),[preview,setPreview]=useState<any>(null);
 const previewSequence=useRef(0),live=useRef(true);
 useEffect(()=>{live.current=true;return()=>{live.current=false;previewSequence.current++}},[]);
 useEffect(()=>{previewSequence.current++;setPreview(null)},[kind,digest,description,suspended]);
 useEffect(()=>{setPreview(null)},[article.revision,task.data?.credential_id,task.data?.account_revision]);
 useEffect(()=>{if(!suspended)void task.act(()=>task.reload())},[suspended]);
 async function showPreview(){
  const n=++previewSequence.current;
  const a=await context.prepare!();if(a.id!==article.id)throw new Error('文章已切换，请重新打开推送预览');
  // Read settings first; a changed connection/account makes an older preview unusable.
  const d=await task.reload();
  const p=await api('/extensions/preview','POST',{article_id:a.id,action:kind,digest,description});
  if(live.current&&n===previewSequence.current)setPreview({...p,credential_id:d.credential_id,account_revision:d.account_revision});
 }
 const valid=preview&&preview.revision===article.revision&&preview.credential_id===task.data?.credential_id&&preview.account_revision===task.data?.account_revision;
 if(suspended)return null;
 return <Modal title="推送微信草稿" wide onClose={onClose}><div className="account-panel">
  <p>当前文章：{article.title}</p><p className="muted">查看预览后主动推送到公众号草稿箱。完整制作流程不会自动推送。</p>
  <div className="row wrap"><span>{task.data?.configured?'公众号连接已配置':'尚未配置公众号连接'}</span><button className="text-button" disabled={task.pending} onClick={onConnection}>{task.data?.configured?'管理公众号连接':'配置公众号连接'}</button></div>
  <Select label="草稿类型" value={kind} onChange={setKind}><option value="publish">文章草稿</option><option value="image_post">图片帖草稿</option></Select>
  {kind==='publish'?<Input label="微信摘要" value={digest} onChange={setDigest} multiline/>:<Input label="图片帖说明" value={description} onChange={setDescription} multiline/>}
  <button className="button secondary" disabled={!task.data||task.busy} onClick={()=>void task.act(showPreview)}>查看推送预览</button>
  {valid&&<div className="service-card"><p>{preview.title} · r{preview.revision} · 采用图片 {preview.images} 张</p>{kind==='publish'&&<p>微信摘要：{preview.digest}</p>}{preview.issues.map((x:string)=><p className="notice amber" key={x}>{x}</p>)}<iframe title="微信推送预览" sandbox="" srcDoc={preview.html} style={{width:'100%',height:360,border:0}}/><button className="button primary" disabled={task.busy||!task.data?.configured||!!preview.issues.length} onClick={()=>void task.act(async()=>{try{await task.start(kind as 'publish'|'image_post',{preview_hash:preview.preview_hash,digest,description})}finally{setPreview(null)}})}>{kind==='publish'?'将此文章推送到微信草稿箱':'将采用图片推送为图片帖'}</button></div>}
  {article.extensions?.filter(x=>x.action==='publish'&&x.result?.media_id).map(x=><p key={x.job_id}>草稿 {x.result.media_id}<button className="text-button" disabled={task.busy||!task.data?.configured} onClick={()=>void task.act(()=>task.start('draft_read',{media_id:x.result.media_id}))}>读取微信草稿副本</button></p>)}<ActionTaskView task={task}/>
 </div></Modal>;
}

export function WechatConnection({focus=false,onSaved}:{focus?:boolean;onSaved:()=>Promise<void>}){
 const task=useActionTask([],{refresh:onSaved}),[value,setValue]=useState({appid:'',secret:''}),[open,setOpen]=useState(focus);
 const box=useRef<HTMLDetailsElement>(null);
 useEffect(()=>{if(focus){setOpen(true);requestAnimationFrame(()=>{box.current?.scrollIntoView({block:'nearest'});box.current?.querySelector('input')?.focus()})}},[focus]);
 return <details className="wechat-connection" ref={box} open={open} onToggle={e=>setOpen(e.currentTarget.open)}><summary>公众号连接 · {task.data?.configured?'已保存凭证':'尚未配置'}</summary>
  <p className="muted">用于微信草稿箱与在线效果，需要公众号提供相应接口权限和网络白名单。凭证在本机加密保存。</p>
  <Input label="公众号 AppID" value={value.appid} onChange={appid=>setValue({...value,appid})}/><label className="field"><span>公众号 AppSecret</span><input aria-label="公众号 AppSecret" type="password" autoComplete="off" value={value.secret} onChange={e=>setValue({...value,secret:e.target.value})}/></label>
  <button className="button secondary" disabled={!task.data||task.busy||!value.appid||!value.secret} onClick={()=>void task.act(async()=>{await api('/extensions/wechat','PUT',{...value,credential_id:task.data!.credential_id});setValue({appid:'',secret:''});await task.reload();await onSaved()})}>保存公众号连接</button>
  {task.data?.configured&&<button className="text-button" disabled={task.busy} onClick={()=>void task.act(async()=>{await api('/extensions/wechat','PUT',{remove:true,credential_id:task.data!.credential_id});setValue({appid:'',secret:''});await task.reload();await onSaved()})}>移除公众号凭证</button>}<ActionTaskView task={task}/>
 </details>;
}

export function OnlineEffects({onConnection,...context}:ToolContext&{onConnection:()=>void}){
 const task=useActionTask(['stats','stats_review'],context);
 const [day,setDay]=useState(new Date(Date.now()-86400000).toISOString().slice(0,10)),[msgid,setMsgid]=useState('');
 return <section className="online-effects" aria-label="微信数据与复盘"><h3>微信数据与复盘</h3>
  <p className="muted">选择关联文章，再填写微信统计文章编号。草稿编号与统计编号不同，同名文章不会自动匹配。复盘会参考账号已有历史与效果数据。</p>
  {!context.articleId&&<p>请先选择关联文章。</p>}
  <Input label="微信统计文章编号（msgid）" value={msgid} onChange={setMsgid}/>
  <button className="button secondary" disabled={!task.data||task.busy||!context.articleId||!msgid} onClick={()=>void task.act(async()=>{const d=await task.reload();await api('/extensions/bindings','POST',{revision:d.account_revision,article_id:context.articleId,msgid});await task.reload();await context.refresh()})}>关联所选文章</button>
  <label className="field"><span>文章群发日期</span><input aria-label="文章群发日期" type="date" value={day} onChange={e=>setDay(e.target.value)}/></label>
  <div className="row wrap"><button className="button primary" disabled={task.busy||!context.articleId||!task.data?.configured||!day} onClick={()=>void task.act(()=>task.start('stats',{date:day}))}>拉取并回填在线效果</button><button className="button secondary" disabled={!task.data||task.busy||!context.articleId} onClick={()=>void task.act(()=>task.start('stats_review'))}>复盘已有数据（AI）</button></div>
  <p className="muted">复盘使用分析模型，调用会计费。缺少公众号连接时仍可复盘本地已有记录。</p>
  {!task.data?.configured&&<p className="notice">在线拉取需要配置公众号连接。<button className="text-button" onClick={onConnection}>配置公众号连接</button></p>}
  {task.data?.bindings.filter(x=>x.article_id===context.articleId).map(x=><p key={x.msgid}>{x.title} · {x.msgid}</p>)}
  {task.data?.online_metrics.filter(x=>x.article_id===context.articleId).map((x,i)=><p key={i}>{x.msgid} · {x.observed_at}：阅读 {x.stats.read_count??'未知'}，分享 {x.stats.share_count??'未知'}，点赞 {x.stats.like_count??'未知'}</p>)}<ActionTaskView task={task}/>
 </section>;
}
