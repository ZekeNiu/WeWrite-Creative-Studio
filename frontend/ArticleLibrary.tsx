import {Pager} from './MaterialList';
import {useEffect,useState} from 'react';
import {ArrowUpRight,Trash2,RotateCcw,FolderOpen} from 'lucide-react';
import {api,date,errorText} from './api';
import {Modal,Tag} from './ui';
import {LABELS,type Article,type PageResult} from './types';

export default function ArticleLibrary({articles,onOpen,onChanged}:{articles:Article[];onOpen:(id:string)=>void;onChanged:()=>Promise<void>}){
 const [trash,setTrash]=useState(false),[rows,setRows]=useState<Article[]>([]),[confirm,setConfirm]=useState<Article|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),[notice,setNotice]=useState('');
 async function action(fn:()=>Promise<void>){setBusy(true);setError('');try{await fn()}catch(e){setError(errorText(e))}finally{setBusy(false)}}
 const [query,setQuery]=useState(''),[page,setPage]=useState(1),[total,setTotal]=useState(0);
 useEffect(()=>{let active=true;const timer=setTimeout(()=>{void api<PageResult<Article>>(`/articles?state=${trash?'trash':'active'}&page=${page}&page_size=20&query=${encodeURIComponent(query)}`).then(result=>{if(active){setRows(result.items);setTotal(result.total);setError('');if(page>1&&!result.items.length)setPage(Math.max(1,Math.ceil(result.total/20)))}}).catch(e=>{if(active)setError(errorText(e))})},150);return()=>{active=false;clearTimeout(timer)}},[articles,trash,page,query]);
 async function reload(){await onChanged()}
 return <section className="library"><div className="row between wrap"><div className="row"><h2>{trash?'回收站':'我的文章'}</h2><span className="count">{total}</span></div><button className="text-button" disabled={busy} onClick={()=>void action(async()=>{setTrash(!trash);setPage(1);setNotice('')})}>{trash?'返回文章库':'回收站'}</button></div>
 <label className="field"><span>搜索文章标题或主题</span><input aria-label="搜索文章标题或主题" value={query} onChange={e=>{setQuery(e.target.value);setPage(1)}}/></label>
 {error&&<p className="notice amber" role="alert">{error}</p>}{notice&&<p className="muted" role="status">{notice}</p>}
 {rows.length?<div className="article-grid">{rows.map(a=><article className="article-card library-card" key={a.id}><button className="article-open" disabled={trash||busy} aria-label={'打开文章：'+a.title} onClick={()=>onOpen(a.id)}><div className="row between"><Tag>{a.brief.column}</Tag>{!trash&&<ArrowUpRight size={16}/>}</div><h3>{a.title}</h3><p>{a.brief.audience} · {a.brief.words} 字</p></button><div className="article-card-bottom"><span>{trash?'已移入回收站':LABELS[a.current_stage]||'创作中'}</span><time>{date(a.updated)}</time></div><div className="library-actions">{trash?<><button className="text-button" disabled={busy} onClick={()=>void action(async()=>{await api('/articles/'+a.id+'/untrash','POST',{revision:a.revision});await reload();setNotice('文章已恢复到文章库')})}><RotateCcw size={14}/>恢复</button><button className="text-button" disabled={busy} onClick={()=>setConfirm(a)}><Trash2 size={14}/>彻底删除</button></>:<button className="text-button" disabled={busy} aria-label={'删除文章：'+a.title} onClick={()=>void action(async()=>{await api('/articles/'+a.id+'/trash','POST',{revision:a.revision});await reload();setNotice('已移入回收站，可随时恢复')})}><Trash2 size={14}/>删除</button>}</div></article>)}</div>:<div className="library-empty"><FolderOpen size={28}/><div><h3>{trash?'回收站为空':'这里，留给你的下一篇作品'}</h3><p>{trash?'删除的文章会先保留在这里。':'新建文章或导入旧稿，随时回来继续。'}</p></div></div>}
 <Pager page={page} total={total} pageSize={20} onChange={setPage}/>
 {confirm&&<Modal title="彻底删除文章" onClose={()=>{if(!busy)setConfirm(null)}}><p>将永久删除“{confirm.title}”及其在本项目中的附件、历史版本与任务记录。此操作无法恢复。</p>{error&&<p className="notice amber" role="alert">{error}</p>}<div className="modal-footer"><button className="button secondary" disabled={busy} onClick={()=>setConfirm(null)}>取消</button><button className="button primary" disabled={busy} onClick={()=>void action(async()=>{await api('/articles/'+confirm.id,'DELETE',{revision:confirm.revision});setConfirm(null);await reload();setNotice('文章已彻底删除')})}>确认彻底删除</button></div></Modal>}
 </section>;
}
