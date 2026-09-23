import {registerField,notifyFields} from './fieldChanges';
import {useEffect,useRef,useState} from 'react';
import {Check,Copy,Download,Smartphone,Sparkles} from 'lucide-react';
import {api} from './api';
import {type Article,type Save,type Meta,type Theme} from './types';
import {Field,Select,Busy} from './ui';
import {type Action,type Run} from './Panels';

type Preview={html:string;body:string;plaintext:string;references:any[];compatibility:{rule:string;level:string;message:string}[]};
export default function LayoutPanel({a,save,act,run,busy,meta,prepareExport}:{a:Article;save:Save;act:Action;run:Run;busy:boolean;meta:Meta;prepareExport:(open?:boolean)=>Promise<any>}){
 const [preview,setPreview]=useState<{key:string;data:Preview}|null>(null),[loading,setLoading]=useState(false),[copied,setCopied]=useState(false);
 const [saving,setSaving]=useState(0),[layout,setLayout]=useState(a.layout);
 const [retry,setRetry]=useState(0);
 const [saveFailed,setSaveFailed]=useState(false);
 const unsaved=useRef<Partial<Article['layout']>>({}),inFlight=useRef<Promise<unknown>|null>(null);
 const draft=useRef(a.layout),writes=useRef(0),seq=useRef(0),latest=useRef(a);latest.current=a;
 const [archive,setArchive]=useState<{path:string;revision:number}|null>(null);
 const key=a.id+':'+a.revision;
 useEffect(()=>{if(writes.current===0&&!Object.keys(unsaved.current).length){draft.current=a.layout;setLayout(a.layout)}},[a.id,a.revision]);
 useEffect(()=>{
  const n=++seq.current;setCopied(false);
  if(!a.content||saving||saveFailed){setLoading(false);return}
  setLoading(true);
  const timer=setTimeout(()=>{void act(async()=>{const p=await api<Preview>('/articles/'+a.id+'/preview','POST');if(n===seq.current)setPreview({key,data:p})}).finally(()=>{if(n===seq.current)setLoading(false)})},250);
  return()=>{clearTimeout(timer);seq.current++};
 },[key,saving,retry,saveFailed]);
 const ready=!!preview&&preview.key===key&&!saving&&!loading&&!saveFailed;
 async function commit(patch:Partial<Article['layout']>){
  unsaved.current={...unsaved.current,...patch};const sent={...unsaved.current};notifyFields();
  const next={...draft.current,...patch};
  draft.current=next;setLayout(next);writes.current++;setSaving(writes.current);setCopied(false);seq.current++;
  const task=save(current=>({layout:{...current.layout,...sent}}),'layout');inFlight.current=task;try{await task;for(const k of Object.keys(sent) as (keyof Article['layout'])[]){if(unsaved.current[k]===sent[k])delete unsaved.current[k]}setSaveFailed(false)}catch(e){setSaveFailed(true);throw e}finally{writes.current--;setSaving(writes.current);notifyFields()}
 }
 const flushLayout=useRef(async()=>{});flushLayout.current=async()=>{if(writes.current)await inFlight.current;if(Object.keys(unsaved.current).length)await commit({})};
 useEffect(()=>registerField(()=>flushLayout.current(),()=>!!Object.keys(unsaved.current).length),[]);
 const change=(k:keyof Article['layout'],v:string|number)=>commit({[k]:v});
 function choose(theme:Theme){return commit({theme:theme.id,...theme.defaults})}
 const theme=meta.themes.find(t=>t.id===layout.theme);
 async function copy(){if(!ready||!preview)return;await navigator.clipboard.write([new ClipboardItem({'text/html':new Blob([preview.data.body],{type:'text/html'}),'text/plain':new Blob([preview.data.plaintext],{type:'text/plain'})})]);setCopied(true)}
 async function download(kind:string){const info=await prepareExport();setArchive(info);const link=document.createElement('a');link.href=`/api/articles/${a.id}/exports/${info.digest}/${kind}`;link.download='';link.click()}
 return <div className="layout-workspace"><div className="layout-controls">
  <span className="eyebrow">文章的最后一公里</span><h3>让好内容，读起来更舒服</h3>
  <Select label="排版主题" value={layout.theme} onChange={v=>{const t=meta.themes.find(t=>t.id===v);if(t)return choose(t)}}>{meta.themes.map(t=><option key={t.id} value={t.id}>{t.name}</option>)}</Select>
  <div className="theme-swatches">{meta.themes.slice(0,12).map(t=><button title={t.name} aria-label={t.name} key={t.id} style={{background:t.colors.primary||'#243e38'}} className={layout.theme===t.id?'selected':''} onClick={()=>void choose(t).catch(()=>{})}/>)}</div>
  <div className="form-grid"><Field label="正文字号" type="number" min={12} max={24} value={layout.font_size} onCommit={v=>change('font_size',Number(v))}/><Field label="行距倍数" type="number" min={1.2} max={3} value={layout.line_height} onCommit={v=>change('line_height',Number(v))}/></div>
  <Field label="段落间距 / px" type="number" min={4} max={40} value={layout.paragraph_gap} onCommit={v=>change('paragraph_gap',Number(v))}/>
  <p className="muted small-text">切换主题会采用推荐字号与间距。<button className="text-button" disabled={!theme||saving>0} onClick={()=>{if(theme)void choose(theme).catch(()=>{})}}>恢复推荐设置</button></p>
  <Field label="署名" value={layout.author} placeholder="可选" onCommit={v=>change('author',v)}/>
  <details className="reading-advice"><summary>阅读与结构建议（AI，可选）</summary><p className="muted small-text">只针对段落、层级与图片位置给建议，不会应用主题或修改正文。</p><button className="button secondary full" disabled={busy||saving>0||!a.content} onClick={()=>run('layout_advice',{chain:false})}><Sparkles size={15}/>获取阅读与结构建议</button>{a.layout_advice&&<div className="layout-advice">{a.layout_advice}</div>}</details>
  <div className="export-group"><button className="button primary full" disabled={!ready||busy} onClick={()=>act(copy)}>{copied?<Check size={16}/>:<Copy size={16}/>} {copied?'已复制':'复制公众号排版'}</button><button className="button secondary full" disabled={busy||saving>0||!a.content} onClick={()=>act(()=>download('zip'))}><Download size={16}/>下载文章分享包</button><div className="row"><button className="text-button" disabled={busy||saving>0||!a.content} onClick={()=>act(()=>download('md'))}>Markdown</button><span className="muted">·</span><button className="text-button" disabled={busy||saving>0||!a.content} onClick={()=>act(()=>download('html'))}>HTML</button></div></div>
  {archive&&<div className="small-text"><p style={{overflowWrap:'anywhere'}}>已归档 r{archive.revision}：{archive.path}</p><button className="text-button" disabled={busy} onClick={()=>act(async()=>setArchive(await prepareExport(true)))}>打开归档文件夹</button></div>}
  <p className="muted small-text">ZIP 仅含文章、采用图片和实际引用的文献信息，不含素材全文及内部备注，不是创作数据备份。复制到公众号后，本地图片需在微信编辑器中上传。</p>
  {ready&&preview&&<details><summary>公众号排版校验</summary>{preview.data.compatibility?.length?preview.data.compatibility.map(i=><p key={i.rule}>{i.level}：{i.message}</p>):<p>通过上游兼容性校验；已应用复制粘贴加固。封面独立保留在分享包中。</p>}</details>}
  {preview?.data.references.some(r=>!r.complete)&&<div className="notice amber small-text">部分文献信息待补全。请点击编辑器中的引用或素材，核对作者、年份及出处。</div>}
  {a.stages.review==='done'&&a.review.completion==='human'&&<p className="muted small-text">本轮意见已处理；可按需再次审核。</p>}
  {a.stages.review!=='done'&&<div className="notice amber small-text">当前正文尚未通过最新审核。可导出当前文章，正式使用前请核对。</div>}
 </div><div className="preview-area"><div className="row between preview-label"><span><Smartphone size={15}/>手机阅读预览</span>{loading||saving?<Busy text="更新预览"/>:<span className="muted">375 px</span>}</div>
 <div className="phone-frame"><div className="phone-status">9:41 <span>● ▰</span></div><div className="phone-title">{a.title}</div>{ready&&preview?<iframe title="公众号排版预览" sandbox="" srcDoc={preview.data.html}/>:<div className="preview-empty">{!a.content?<>写好正文后，排版会出现在这里。</>:saving||loading?<Busy text={saving?'正在保存排版':'更新预览'}/>:saveFailed?<div><p>排版未保存，输入已保留，请重试。</p><button className="button secondary" onClick={()=>void commit(draft.current).catch(()=>{})}>重试保存排版</button></div>:<div><p>预览未能更新，文章已保留。</p><button className="button secondary" onClick={()=>setRetry(n=>n+1)}>重新加载预览</button></div>}</div>}</div></div></div>;
}
