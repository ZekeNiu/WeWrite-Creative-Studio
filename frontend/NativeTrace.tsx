import {useState} from 'react';
import type {Job} from './types';
import {api} from './api';

export default function NativeTrace({job}:{job:Job}){
 const [files,setFiles]=useState<string[]>([]);const [text,setText]=useState('');
 const n=job.native;if(!n)return null;
 async function list(){try{setFiles(await api<string[]>('/jobs/'+job.id+'/native-artifacts'))}catch(e){setText(String(e))}}
 async function read(name:string){try{const r=await api<{content:string}>('/jobs/'+job.id+'/native-artifacts/'+encodeURIComponent(name));setText(r.content)}catch(e){setText(String(e))}}
 return <details className="notice"><summary>执行详情{job.execution_usage?` · 已请求 ${job.execution_usage.requests} 次`:''}</summary><p className="muted">任务 {n.run_id} · WeWrite {n.upstream_revision.slice(0,7)}{job.execution_usage?.unknown?` · ${job.execution_usage.unknown} 次费用未知`:''}</p><ul>{n.reads.map((r,i)=><li key={i}>{r.path}{r.complete?'（创作规则）':r.operation==='find'?'（全文查找）':`（字符 ${r.start}—${r.end} / ${r.total}）`}</li>)}</ul><button className="button secondary" onClick={()=>void list()}>查看保留的任务产物</button><div className="row">{files.map(f=><button key={f} className="text-button" onClick={()=>void read(f)}>{f}</button>)}</div>{text&&<pre className="editorial-text">{text}</pre>}</details>
}
