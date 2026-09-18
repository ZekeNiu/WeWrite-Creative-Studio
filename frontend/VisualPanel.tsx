import {useRef,useState} from 'react';
import {ImagePlus,Sparkles,Upload,Trash2} from 'lucide-react';
import {api} from './api';
import {type Article,type Save} from './types';
import {type Action,type Run} from './Panels';
import {Field,Select,Toggle,Tag,Empty} from './ui';

type Props={a:Article;save:Save;act:Action;update:(a:Article)=>void;run:Run;busy:boolean};
const METHODS:Record<string,string>={generate:'生成图片',search:'寻找图片',upload:'自行上传'};
const TYPES:Record<string,string>={scene:'场景摄影',concept:'概念解释',action:'动作教学',anatomy:'解剖说明',equipment:'器械细节',research:'研究原图'};

function BillRow({row,a,act,update}:{row:any;a:Article;act:Action;update:(a:Article)=>void}){
 const [amount,setAmount]=useState(''),[note,setNote]=useState(''),[saving,setSaving]=useState(false);
 return <details className="picture-bill"><summary>{row.model} · {new Date(row.at).toLocaleString()} · {row.billing_status==='confirmed'?'账单已核对':row.estimated_cost==null?'待核算':'预估'} ¥{(row.estimated_cost??row.reserved_cost??0).toFixed(4)}{row.status==='unknown'?'（请求结果未知）':''}</summary><p className="muted small-text">预算预留不等于实际扣费。请核对服务商账单后填写；只有确认没有扣费时才填 0。原记录会保留。</p><label className="field"><span>账单金额 / 元</span><input aria-label="账单金额 / 元" type="number" min="0" step="0.001" value={amount} onChange={e=>setAmount(e.target.value)}/></label><label className="field"><span>核对依据</span><input aria-label="核对依据" value={note} onChange={e=>setNote(e.target.value)} placeholder="对应账单记录或确认未扣费的依据"/></label><button className="button secondary" disabled={saving||row.status==='reserved'||!amount.trim()||!note.trim()||Number(amount)<0} onClick={()=>{setSaving(true);void act(async()=>update(await api(`/articles/${a.id}/usage/${row.id}/settle`,'POST',{amount:Number(amount),note,billing_revision:row.billing_revision||0}))).finally(()=>setSaving(false))}}>按账单核对这笔费用</button></details>
}

export default function VisualPanel({a,save,act,update,run,busy}:Props){
 const file=useRef<HTMLInputElement>(null),uploadTarget=useRef({role:'article',plan_id:''}),savingRef=useRef(false);
 const [saving,setSaving]=useState(false);const locked=busy||saving;
 const headings=[...a.content.matchAll(/^#{1,6}\s+(.+)$/gm)].map((m,index)=>({index,heading:m[1].trim()}));
 const cost=a.visual_status?.budget;
 async function commit(changes:Partial<Article>,stage='visual'){
  if(savingRef.current)return;savingRef.current=true;setSaving(true);
  try{await save(changes,stage)}catch{/* App keeps the previous article and reports the error. */}finally{savingRef.current=false;setSaving(false)}
 }
 const imageChange=(im:any,p:Record<string,unknown>)=>void commit({images:a.images.map(x=>x.id===im.id?{...x,...p}:x)});
 const planChange=(plan:any,p:Record<string,unknown>)=>void commit({image_plans:a.image_plans.map(x=>x.id===plan.id?{...x,...p}:x)},'preferences');
 function upload(role:string,plan_id=''){uploadTarget.current={role,plan_id};file.current?.click()}
 function location(item:any,change:(v:Record<string,unknown>)=>void){
  const found=headings.filter(h=>h.heading===item.after_heading);
  const value=!item.after_heading?'':found.length===1?String(found[0].index):found.some(h=>h.index===item.section_index)?String(item.section_index):'missing';
  return <Select label="放在章节之后" value={value} onChange={v=>{const h=headings[Number(v)];change(v===''?{after_heading:'',section_index:null}:{after_heading:h.heading,section_index:h.index})}}><option value="">文章末尾</option>{value==='missing'&&<option value="missing" disabled>原位置已失效，请重新选择</option>}{headings.map(h=><option key={h.index} value={h.index}>{h.heading}</option>)}</Select>
 }
 function picture(im:any){
  const source=im.origin||(im.prompt?'generated':'upload');const rights=im.rights?.status;
  const blocked=source==='web'&&!['licensed','confirmed'].includes(rights);
  const src=`/api/articles/${a.id}/assets/${im.filename}`;
  return <article key={im.id} className={'image-card '+(im.selected?'picture-selected':'')}>
   {im.check?.status==='rejected'?<div className="picture-note">此候选未通过适配检查，已隐藏预览。<p><a className="text-link" href={src} target="_blank" rel="noreferrer">自行查看原图</a></p></div>:<a href={src} target="_blank" rel="noreferrer" title="查看完整原图"><img className={im.role==='cover'?'cover-crop':''} style={im.role==='cover'?{objectPosition:`${(im.crop_x??.5)*100}% ${(im.crop_y??.5)*100}%`}:undefined} src={src} alt={im.caption||'配图候选'}/></a>}
   <div className="image-meta"><div className="row between wrap"><Tag>{source==='generated'?'AI 生成':source==='web'?'网络原图':'自行上传'}</Tag><button type="button" className="icon-button" title="移除图片" onClick={()=>void commit({images:a.images.filter(x=>x.id!==im.id)})}><Trash2 size={15}/></button></div>
   {im.check&&<p className={'small-text '+(im.check.status==='passed'?'muted':'picture-note')}><strong>{im.check.status==='passed'?'已检查图片':im.check.status==='rejected'?'建议换图':'需人工查看'}：</strong>{im.check.reason}</p>}
   {blocked&&<p className="picture-note">使用条件尚未确认，暂不用于排版和导出。</p>}
   {blocked?<span className="muted small-text">先在下方填写使用依据，再采用这张图片。</span>:<Toggle checked={im.selected} label="用于排版" onChange={v=>imageChange(im,{selected:v})}/>}
   <Field label="图注" value={im.caption||''} onCommit={v=>imageChange(im,{caption:v})}/>
   {im.role==='article'&&location(im,p=>imageChange(im,p))}
   {im.role==='cover'&&<details><summary>调整封面裁切 · 2.35:1</summary><p className="muted small-text">上方为封面预览，点击可看完整原图。原图始终保留。</p>{[['crop_x','横向位置'],['crop_y','纵向位置']].map(([key,label])=><label className="field" key={key}><span>{label}</span><input aria-label={label} type="range" min="0" max="100" value={Math.round((im[key]??.5)*100)} onChange={e=>imageChange(im,{[key]:Number(e.target.value)/100})}/></label>)}</details>}
   <details><summary>来源、使用依据与图片用途</summary><Select label="图片用途" value={im.role} onChange={v=>imageChange(im,{role:v})}><option value="cover">封面</option><option value="article">正文插图</option></Select>
    {source==='web'&&<><p className="small-text">{im.original_caption||'原始页面未提供图注'}</p><p className="small-text">{im.author||'作者信息未取得'} · {im.rights?.license||'使用条件未知'}</p>{im.source_url&&<a className="text-link" href={im.source_url} target="_blank" rel="noreferrer">查看来源页面</a>}{im.rights?.url&&<p><a className="text-link" href={im.rights.url} target="_blank" rel="noreferrer">查看使用条件</a></p>}<Field label="使用依据" value={im.rights_basis||''} placeholder="例如已获授权及其范围，或适用的许可及出处" multiline onCommit={v=>imageChange(im,{rights_basis:v})}/><p className="muted small-text">填写依据表示你已核对使用条件；仅注明来源并不等于获得授权。</p></>}
    {im.manual_approved&&<p className="muted small-text">已由你手动采用。</p>}
   </details></div>
  </article>
 }
 const loose=a.images.filter(im=>!a.image_plans.some(p=>p.id===im.plan_id));
 return <div className="visual-workspace"><fieldset className="visual-controls" disabled={locked}>
  <div className="visual-intro"><div><h3>先安排位置，再选择图片</h3><p className="muted">按正文需要找图或生成。专业图保留出处，图片和位置都可手动调整。</p></div><Toggle checked={a.visual.enabled} label="启用智能配图" onChange={v=>void commit({visual:{...a.visual,enabled:v}},'preferences')}/></div>
  {a.visual.enabled&&<div className="form-grid three"><Field label="目标图片数（含封面）" type="number" min={1} max={6} value={a.visual.count} onCommit={v=>void commit({visual:{...a.visual,count:Number(v)}},'preferences')}/><Select label="生成原图尺寸" value={a.visual.size} onChange={v=>void commit({visual:{...a.visual,size:v}},'preferences')}><option value="1536x1024">横图 · 1536 × 1024</option><option value="1024x1024">方图 · 1024 × 1024</option><option value="1024x1536">竖图 · 1024 × 1536</option></Select><Field label="本篇配图总预算 / 元" type="number" min={0} value={a.visual.budget} onCommit={v=>void commit({visual:{...a.visual,budget:Number(v)}},'preferences')}/></div>}
  {cost&&<details className="picture-budget"><summary>配图费用：已知约 ¥{cost.known.toFixed(4)} · 占用预算 ¥{cost.reserved.toFixed(4)}{cost.unknown>0?` · ${cost.unknown} 笔待核算`:''}</summary><p className="muted small-text">包含规划、找图、识图和生成。预估单价来自服务设置，不是服务商实际扣费；未知请求仍占用预留。展开对应记录可按账单核对。</p><div className="row wrap">{Object.entries(cost.categories).map(([k,v])=><Tag key={k}>{{visual:'规划',vision:'识图',image:'生成',image_search:'找图'}[k]} ¥{Number(v).toFixed(4)}</Tag>)}</div>{cost.records?.map(row=><BillRow key={row.id} row={row} a={a} act={act} update={update}/>)}</details>}
  <div className="row wrap"><button className="button primary" disabled={!a.visual.enabled||a.workflow?.visual.allowed===false} onClick={()=>run('visual',{action_id:crypto.randomUUID()})}><Sparkles size={16}/>{a.image_plans.length?'重新规划配图':'生成配图方案'}</button><button className="button secondary" onClick={()=>upload('cover')}><Upload size={15}/>上传封面</button><button className="button secondary" onClick={()=>upload('article')}><ImagePlus size={15}/>上传插图</button></div>
  {a.visual_status?.warnings.map(w=><p key={w.id} className="picture-note" role="status">{w.message}</p>)}
  {a.images.filter(i=>i.selected&&i.role==='cover').length>1&&<p className="picture-note">旧记录采用了多张封面，请只保留一张后导出。</p>}
  <input hidden ref={file} type="file" accept="image/png,image/jpeg,image/webp" onChange={e=>{const f=e.target.files?.[0];if(f){const body=new FormData();body.append('file',f);body.append('revision',String(a.revision));body.append('role',uploadTarget.current.role);body.append('plan_id',uploadTarget.current.plan_id);void act(async()=>update(await api(`/articles/${a.id}/images/upload`,'POST',body)))}e.target.value=''}}/>
  <div className="visual-slots">{a.image_plans.map((p,index)=>{const images=a.images.filter(im=>im.plan_id===p.id);return <section className="visual-slot" key={p.id}>
   <div className="row between wrap"><h3>{p.role==='cover'?'封面':`插图 ${index+(a.image_plans[0]?.role==='cover'?0:1)} · ${p.after_heading||'文章末尾'}`}</h3><Tag tone={images.some(i=>i.selected)?'green':''}>{images.some(i=>i.selected)?'已采用':images.length?'候选待选':'待获取'}</Tag></div>
   <p className="picture-purpose">{p.purpose||p.caption||'可在方案详情中补充这张图要解释的内容'}</p>
   <div className="row wrap"><Tag>{TYPES[p.image_type]||'配图'}</Tag><Tag>{METHODS[p.method||'generate']}</Tag></div>
   <details className="picture-plan"><summary>编辑配图方案与位置</summary><Field label="这张图解释什么" value={p.purpose||''} onCommit={v=>planChange(p,{purpose:v})}/>{p.role==='article'&&location(p,v=>planChange(p,v))}<Select label="获取方式" value={p.method||'generate'} onChange={v=>planChange(p,{method:v})}><option value="generate">生成图片</option><option value="search">寻找图片</option><option value="upload">自行上传</option></Select><Select label="图片类型" value={p.image_type||'concept'} onChange={v=>planChange(p,{image_type:v,method:['action','anatomy','equipment','research'].includes(v)?'search':p.method||'generate'})}>{Object.entries(TYPES).map(([k,v])=><option key={k} value={k}>{v}</option>)}</Select><Field label="专业性与内容要求" value={p.requirements||''} multiline onCommit={v=>planChange(p,{requirements:v})}/>{p.method==='search'?<Field label="找图关键词" value={p.query||''} onCommit={v=>planChange(p,{query:v})}/>:p.method!=='upload'&&<Field label="图片提示词" value={p.prompt||''} multiline onCommit={v=>planChange(p,{prompt:v})}/>}<Field label="建议图注" value={p.caption||''} onCommit={v=>planChange(p,{caption:v})}/><button className="text-button" onClick={()=>planChange(p,{})}>按当前正文更新此方案</button></details>
   <div className="row wrap">{p.method!=='upload'&&<button className="button secondary" disabled={!a.visual.enabled} onClick={()=>run('image',{image_id:p.id,chain:false,action_id:crypto.randomUUID()})}>{images.length?'获取或复用候选':METHODS[p.method||'generate']}</button>}<button className="text-button" onClick={()=>upload(p.role,p.id)}>为此位置上传图片</button></div>
   {images.length>0&&<div className="image-gallery">{images.map(picture)}</div>}
  </section>})}</div>
  {loose.length>0&&<section className="visual-slot"><h3>已上传与保留的图片</h3><p className="muted small-text">重新规划不会删除原有图片。仍然采用的图片会继续参与排版。</p><div className="image-gallery">{loose.map(picture)}</div></section>}
  {!a.image_plans.length&&!a.images.length&&<Empty icon={<ImagePlus size={30}/>} title="按内容安排图片" description="先完成正文，再规划封面与插图；也可以直接上传已有图片。"/>}
 </fieldset></div>
}
