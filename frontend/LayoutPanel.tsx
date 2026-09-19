import {useEffect,useRef,useState} from 'react';
import {Check,Copy,Download,Smartphone,Sparkles,SlidersHorizontal,ArrowUpRight} from 'lucide-react';
import {api} from './api';
import {type Article,type Save,type Meta,type Theme} from './types';
import {Field,Select,Busy} from './ui';
import {type Action,type Run} from './Panels';

function ThemeCard({theme,selected,onSelect}:{theme:Theme;selected:boolean;onSelect:()=>void}){
 const [html,setHtml]=useState('');
 useEffect(()=>{let active=true;void api<{html:string}>(`/themes/${theme.id}/preview`).then(p=>{if(active)setHtml(p.html)}).catch(()=>{});return()=>{active=false}},[theme.id]);
 return <button className={'editorial-card '+(selected?'selected':'')} aria-pressed={selected} aria-label={'应用'+theme.name} onClick={onSelect}>
  <div className="theme-thumbnail" aria-hidden="true">{html?<iframe title={theme.name+'示例'} sandbox="" tabIndex={-1} srcDoc={html}/>:<div className="theme-placeholder" style={{borderColor:theme.colors.primary}}>文字，自在展开。</div>}</div>
  <div className="theme-card-copy"><div><strong>{theme.name}</strong>{selected?<Check size={15}/>:<ArrowUpRight size={14}/>}</div><p>{theme.description}</p></div>
 </button>;
}

type Preview={html:string;body:string;plaintext:string;references:any[]};
export default function LayoutPanel({a,save,act,run,busy,meta,prepareExport}:{a:Article;save:Save;act:Action;run:Run;busy:boolean;meta:Meta;prepareExport:(open?:boolean)=>Promise<any>}){
 const [preview,setPreview]=useState<{key:string;data:Preview}|null>(null),[loading,setLoading]=useState(false),[copied,setCopied]=useState(false);
 const [saving,setSaving]=useState(0),[layout,setLayout]=useState(a.layout),[width,setWidth]=useState(375);
 const [retry,setRetry]=useState(0);
 const [saveFailed,setSaveFailed]=useState(false);
 const draft=useRef(a.layout),writes=useRef(0),seq=useRef(0),latest=useRef(a);latest.current=a;
 const [archive,setArchive]=useState<{path:string;revision:number}|null>(null);
 const key=a.id+':'+a.revision;
 useEffect(()=>{if(writes.current===0){draft.current=a.layout;setLayout(a.layout)}},[a.id,a.revision]);
 useEffect(()=>{
  const n=++seq.current;setCopied(false);
  if(!a.content||saving||saveFailed){setLoading(false);return}
  setLoading(true);
  const timer=setTimeout(()=>{void act(async()=>{const p=await api<Preview>('/articles/'+a.id+'/preview','POST');if(n===seq.current)setPreview({key,data:p})}).finally(()=>{if(n===seq.current)setLoading(false)})},250);
  return()=>{clearTimeout(timer);seq.current++};
 },[key,saving,retry,saveFailed]);
 const ready=!!preview&&preview.key===key&&!saving&&!loading&&!saveFailed;
 function commit(next:Article['layout']){
  draft.current=next;setLayout(next);writes.current++;setSaving(writes.current);setCopied(false);seq.current++;
  void act(async()=>{let saved:Article|undefined;try{saved=await save({layout:next},'layout')}finally{writes.current--;setSaving(writes.current);if(!writes.current){setSaveFailed(!saved);draft.current=(saved||latest.current).layout;setLayout(draft.current)}}});
 }
 const change=(k:keyof Article['layout'],v:string|number)=>commit({...draft.current,[k]:v});
 function choose(theme:Theme){commit({...draft.current,theme:theme.id,...theme.defaults})}
 const theme=meta.themes.find(t=>t.id===layout.theme);
 async function copy(){if(!ready||!preview)return;await navigator.clipboard.write([new ClipboardItem({'text/html':new Blob([preview.data.body],{type:'text/html'}),'text/plain':new Blob([preview.data.plaintext],{type:'text/plain'})})]);setCopied(true)}
 async function download(kind:string){const info=await prepareExport();setArchive(info);const link=document.createElement('a');link.href=`/api/articles/${a.id}/exports/${info.digest}/${kind}`;link.download='';link.click()}
 return <div className="layout-workspace editorial-workspace"><div className="layout-controls">
  <div className="editorial-heading"><span className="eyebrow">精编排版</span><h3>为文字，找到合适的气质</h3><p>完整设计，一键应用。无需 AI。</p></div>
  <div className="editorial-grid">{meta.themes.filter(t=>t.group==='editorial').map(t=><ThemeCard key={t.id} theme={t} selected={layout.theme===t.id} onSelect={()=>choose(t)}/>)}</div>
  <p className="theme-selection-hint">切换主题会采用推荐字号、行距与段距，正文和署名保留。</p>
  <details className="layout-details" open={theme?.group==='classic'||undefined}><summary>经典主题 <span>18 套原有风格</span></summary><Select label="经典排版主题" value={theme?.group==='classic'?layout.theme:''} onChange={v=>{const t=meta.themes.find(t=>t.id===v);if(t)choose(t)}}><option value="" disabled>选择经典主题</option>{meta.themes.filter(t=>t.group==='classic').map(t=><option key={t.id} value={t.id}>{t.name}</option>)}</Select></details>
  <details className="layout-details"><summary><SlidersHorizontal size={14}/>排版微调 <span>{layout.font_size}px · {layout.line_height} 倍行距</span></summary><div className="form-grid"><Field label="正文字号" type="number" min={12} max={24} value={layout.font_size} onCommit={v=>change('font_size',Number(v))}/><Field label="行距倍数" type="number" min={1.2} max={3} value={layout.line_height} onCommit={v=>change('line_height',Number(v))}/></div><Field label="段落间距 / px" type="number" min={4} max={40} value={layout.paragraph_gap} onCommit={v=>change('paragraph_gap',Number(v))}/><button className="text-button" disabled={!theme||saving>0} onClick={()=>theme&&choose(theme)}>恢复主题推荐设置</button></details>
  <Field label="署名" value={layout.author} placeholder="可选" onCommit={v=>change('author',v)}/>
  <details className="layout-details reading-advice"><summary><Sparkles size={14}/>阅读与结构建议 <span>AI，可选</span></summary><p className="muted small-text">只针对段落、层级与图片位置给建议，不会应用主题或修改正文。</p><button className="button secondary full" disabled={busy||saving>0||!a.content} onClick={()=>run('layout_advice',{chain:false})}>获取阅读与结构建议</button>{a.layout_advice&&<div className="layout-advice">{a.layout_advice}</div>}</details>
  <div className="export-group"><button className="button primary full" disabled={!ready||busy} onClick={()=>act(copy)}>{copied?<Check size={16}/>:<Copy size={16}/>} {copied?'已复制':'复制公众号排版'}</button><button className="button secondary full" disabled={busy||saving>0||!a.content} onClick={()=>act(()=>download('zip'))}><Download size={16}/>下载完整文章包</button><div className="row"><button className="text-button" disabled={busy||saving>0||!a.content} onClick={()=>act(()=>download('md'))}>Markdown</button><span className="muted">·</span><button className="text-button" disabled={busy||saving>0||!a.content} onClick={()=>act(()=>download('html'))}>HTML</button></div></div>
  {archive&&<div className="small-text"><p style={{overflowWrap:'anywhere'}}>已归档 r{archive.revision}：{archive.path}</p><button className="text-button" disabled={busy} onClick={()=>act(async()=>setArchive(await prepareExport(true)))}>打开归档文件夹</button></div>}
  <p className="muted small-text">完整文章包含图片请下载 ZIP。复制到公众号后，本地图片需在微信编辑器中上传。</p>
  {preview?.data.references.some(r=>!r.complete)&&<div className="notice amber small-text">部分文献信息待补全。请点击编辑器中的引用或素材，核对作者、年份及出处。</div>}
  {a.stages.review==='done'&&a.review.completion==='human'&&<p className="muted small-text">本轮意见已处理；可按需再次审核。</p>}
  {a.stages.review!=='done'&&<div className="notice amber small-text">当前正文尚未通过最新审核。可导出备份，正式使用前请核对。</div>}
 </div><div className="preview-area"><div className="row between preview-label" style={{width}}><span><Smartphone size={15}/>阅读预览</span><div className="preview-width">{[375,430].map(w=><button key={w} className={width===w?'active':''} aria-label={w+'像素预览'} aria-pressed={width===w} onClick={()=>setWidth(w)}>{w}</button>)}</div></div>
 <div className="phone-frame" style={{width}}><div className="phone-status">9:41 <span>● ▰</span></div><div className="phone-title">{a.title}</div>{ready&&preview?<iframe title="公众号排版预览" sandbox="" srcDoc={preview.data.html}/>:<div className="preview-empty">{!a.content?<>写好正文后，排版会出现在这里。</>:saving||loading?<Busy text={saving?'正在保存排版':'更新预览'}/>:saveFailed?<div><p>排版未保存，请先查看最新文章。</p><button className="button secondary" onClick={()=>window.location.reload()}>刷新查看最新文章</button></div>:<div><p>预览未能更新，文章已保留。</p><button className="button secondary" onClick={()=>setRetry(n=>n+1)}>重新加载预览</button></div>}</div>}</div><p className="preview-theme-name">{theme?.name} <span>· 仅改变呈现，原文完整保留</span></p></div></div>;
}
