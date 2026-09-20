import {useEffect,useRef,useState,useId,type ReactNode} from 'react';
import {X,LoaderCircle,ChevronDown} from 'lucide-react';
import {registerField} from './fieldChanges';

export function Field({label,value,onCommit,placeholder='',multiline=false,type='text',min,max,hint}:{label:string;value:string|number;onCommit:(s:string)=>void|Promise<unknown>;placeholder?:string;multiline?:boolean;type?:string;min?:number;max?:number;hint?:string}){
 const [local,setLocal]=useState(String(value??'')),[error,setError]=useState('');
 const draft=useRef(local),dirty=useRef(false),focused=useRef(false),pending=useRef<Promise<void>|null>(null);
 const commitRef=useRef(onCommit);commitRef.current=onCommit;
 useEffect(()=>{if(!focused.current&&!dirty.current){draft.current=String(value??'');setLocal(draft.current)}},[value]);
 async function commit(){
  if(pending.current)await pending.current;
  if(!dirty.current)return;
  const text=draft.current;
  const task=(async()=>{try{await commitRef.current(text);if(draft.current===text)dirty.current=false;setError('')}catch(e){setError('未保存，请重试；输入已保留');throw e}})();
  pending.current=task;try{await task}finally{if(pending.current===task)pending.current=null}
 }
 const flushRef=useRef(commit);flushRef.current=commit;
 useEffect(()=>registerField(()=>flushRef.current()),[]);
 const props={'aria-label':label,'aria-invalid':!!error,value:local,placeholder,onFocus:()=>{focused.current=true},onBlur:()=>{focused.current=false;void commit().catch(()=>{})},onChange:(e:React.ChangeEvent<HTMLInputElement|HTMLTextAreaElement>)=>{draft.current=e.target.value;dirty.current=true;setLocal(e.target.value)}};
 return <label className="field"><span>{label}</span>{multiline?<textarea {...props} rows={3}/>:<input {...props} type={type} min={min} max={max}/>} {hint&&<small>{hint}</small>}{error&&<small role="alert">{error}<button type="button" className="text-button" onClick={()=>void commit().catch(()=>{})}>重试保存</button></small>}</label>
}
export function Toggle({checked,onChange,label,small=false}:{checked:boolean;onChange:(v:boolean)=>void;label:string;small?:boolean}){return <label className={'toggle-label '+(small?'small':'')}><button type="button" className={'toggle '+(checked?'on':'')} role="switch" aria-checked={checked} aria-label={label} onClick={()=>onChange(!checked)}><span/></button><span>{label}</span></label>}
export function Select({label,value,onChange,children}:{label:string;value:string;onChange:(s:string)=>void|Promise<unknown>;children:ReactNode}){
 const [local,setLocal]=useState(value),[error,setError]=useState('');const draft=useRef(value),dirty=useRef(false),pending=useRef<Promise<void>|null>(null);
 const handler=useRef(onChange);handler.current=onChange;
 useEffect(()=>{if(!dirty.current){draft.current=value;setLocal(value)}},[value]);
 async function commit(){
  if(pending.current)await pending.current;if(!dirty.current)return;
  const next=draft.current;
  const task=(async()=>{try{await handler.current(next);if(draft.current===next)dirty.current=false;setError('')}catch(e){setError('未保存，选择已保留');throw e}})();
  pending.current=task;try{await task}finally{if(pending.current===task)pending.current=null}
 }
 const flush=useRef(commit);flush.current=commit;
 useEffect(()=>registerField(()=>flush.current()),[]);
 return <label className="field"><span>{label}</span><div className="select-wrap"><select aria-label={label} aria-invalid={!!error} value={local} onChange={e=>{draft.current=e.target.value;dirty.current=true;setLocal(e.target.value);void commit().catch(()=>{})}}>{children}</select><ChevronDown size={14}/></div>{error&&<small role="alert">{error}<button type="button" className="text-button" onClick={()=>void commit().catch(()=>{})}>重试保存</button></small>}</label>
}
export function Modal({title,children,onClose,wide=false}:{title:string;children:ReactNode;onClose:()=>void;wide?:boolean}){
 const heading=useId();const ref=useRef<HTMLDialogElement>(null);useEffect(()=>{ref.current?.showModal()},[]);
 return <dialog ref={ref} aria-labelledby={heading} className={'modal '+(wide?'wide':'')} onCancel={e=>{e.preventDefault();onClose()}}><div className="modal-head"><h2 id={heading}>{title}</h2><button className="icon-button" onClick={onClose} aria-label="关闭"><X size={20}/></button></div>{children}</dialog>
}
export function Empty({icon,title,description,children}:{icon:ReactNode;title:string;description:string;children?:ReactNode}){return <div className="empty"><div className="empty-icon">{icon}</div><h3>{title}</h3><p>{description}</p>{children}</div>}
export function Busy({text='正在处理…'}:{text?:string}){return <span className="busy"><LoaderCircle size={16} className="spin"/>{text}</span>}
export function Tag({children,tone=''}:{children:ReactNode;tone?:string}){return <span className={'tag '+tone}>{children}</span>}
