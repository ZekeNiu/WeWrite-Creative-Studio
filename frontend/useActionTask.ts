import {useEffect,useRef,useState} from 'react';
import {api,errorText} from './api';
import type {Article,Job,PageResult} from './types';

export type ToolAction='theme'|'rewrite'|'publish'|'image_post'|'stats'|'stats_review'|'draft_read';
export type ToolKind='persona'|'theme'|'rewrite'|'publish';
export type ToolContext={articleId?:string;prepare?:()=>Promise<Article>;refresh:()=>Promise<void>};
export type ToolOverview={configured:boolean;credential_id:string;account_revision:number;personas:any[];custom_personas:any[];themes:any[];platforms:any[];online_metrics:any[];bindings:any[]};
type TaskPage=PageResult<Job>&{active:Job[]};
const running=(j:Job)=>['queued','running'].includes(j.status);

// Each mounted feature owns one fixed article/action scope. Callers key article views by id.
export function useActionTask(actions:ToolAction[],context:ToolContext){
 const [data,setData]=useState<ToolOverview|null>(null),[records,setRecords]=useState<TaskPage>({items:[],active:[],total:0,page:1,page_size:20});
 const [error,setError]=useState(''),[pending,setPending]=useState(false),[job,setJob]=useState<Job|null>(null);
 const alive=useRef(false),lock=useRef(false),sequence=useRef(0),page=useRef(1),callbacks=useRef(context);callbacks.current=context;
 const scope=actions.join(',')+':'+(context.articleId??'*');
 const query=(n:number)=>{const q=new URLSearchParams({page:String(n),page_size:'20'});actions.forEach(a=>q.append('action',a));if(context.articleId!==undefined)q.set('article_id',context.articleId);return q};
 async function reload(n=page.current){
  const seq=++sequence.current;
  const [d,rows]=await Promise.all([api<ToolOverview>('/extensions'),actions.length?api<TaskPage>('/extensions/jobs?'+query(n)):Promise.resolve({items:[],active:[],total:0,page:n,page_size:20})]);
  if(alive.current&&seq===sequence.current){setData(d);setRecords(rows);page.current=n;setJob(current=>rows.active[0]||rows.items.find(j=>j.id===current?.id)||rows.items[0]||null)}
  return d;
 }
 async function act(fn:()=>Promise<unknown>){
  if(lock.current)return;lock.current=true;setPending(true);setError('');
  try{await fn()}catch(e){if(alive.current)setError(errorText(e))}finally{lock.current=false;if(alive.current)setPending(false)}
 }
 useEffect(()=>{alive.current=true;void act(()=>reload(1));return()=>{alive.current=false;sequence.current++}},[scope]);
 const activeKey=records.active.map(j=>j.id).join(',');
 useEffect(()=>{
  if(!activeKey)return;
  let live=true,inFlight=false;
  const timer=setInterval(()=>{
   if(inFlight||lock.current)return;inFlight=true;
   void (async()=>{
    const updates=await Promise.all(activeKey.split(',').map(id=>api<Job>('/jobs/'+id)));
    if(!live||!alive.current)return;
    const completed=updates.some(j=>!running(j));
    if(completed){await callbacks.current.refresh();if(!live||!alive.current)return;await reload()}
    else {setRecords(current=>({...current,active:updates,items:current.items.map(j=>updates.find(x=>x.id===j.id)||j)}));setJob(updates[0])}
   })().catch(e=>{if(live&&alive.current)setError(errorText(e))}).finally(()=>{inFlight=false});
  },800);
  return()=>{live=false;clearInterval(timer)};
 },[activeKey,scope]);
 async function start(action:ToolAction,extra:Record<string,unknown>={}){
  const a=callbacks.current.prepare?await callbacks.current.prepare():null;
  if(context.articleId!==undefined&&a?.id!==context.articleId)throw new Error('关联文章已改变，请重新打开此功能');
  const current=await reload(1);if(!alive.current)return;
  const j=await api<Job>('/extensions/actions','POST',{action,article_id:a?.id||'',revision:a?.revision||0,account_revision:current.account_revision,client_id:crypto.randomUUID(),...extra});
  if(!alive.current)return;
  setJob(j);await reload(1);await callbacks.current.refresh();
 }
 async function cancel(id:string){await api('/jobs/'+id+'/cancel','POST');await reload()}
 return {data,records,error,pending,job,busy:pending||records.active.length>0,act,reload,start,cancel};
}
export type ActionTask=ReturnType<typeof useActionTask>;
