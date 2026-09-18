import {useEffect,useRef,useState,type ReactNode} from 'react';
import {X,LoaderCircle,ChevronDown} from 'lucide-react';

export function Field({label,value,onCommit,placeholder='',multiline=false,type='text',min,max,hint}:{label:string;value:string|number;onCommit:(s:string)=>void;placeholder?:string;multiline?:boolean;type?:string;min?:number;max?:number;hint?:string}){
 const [local,setLocal]=useState(String(value??''));const focused=useRef(false);
 useEffect(()=>{if(!focused.current)setLocal(String(value??''))},[value]);
 const props={'aria-label':label,value:local,placeholder,onFocus:()=>{focused.current=true},onBlur:()=>{focused.current=false;if(local!==String(value??''))onCommit(local)},onChange:(e:React.ChangeEvent<HTMLInputElement|HTMLTextAreaElement>)=>setLocal(e.target.value)};
 return <label className="field"><span>{label}</span>{multiline?<textarea {...props} rows={3}/>:<input {...props} type={type} min={min} max={max}/>} {hint&&<small>{hint}</small>}</label>
}
export function Toggle({checked,onChange,label,small=false}:{checked:boolean;onChange:(v:boolean)=>void;label:string;small?:boolean}){return <label className={'toggle-label '+(small?'small':'')}><button type="button" className={'toggle '+(checked?'on':'')} role="switch" aria-checked={checked} aria-label={label} onClick={()=>onChange(!checked)}><span/></button><span>{label}</span></label>}
export function Select({label,value,onChange,children}:{label:string;value:string;onChange:(s:string)=>void;children:ReactNode}){return <label className="field"><span>{label}</span><div className="select-wrap"><select aria-label={label} value={value} onChange={e=>onChange(e.target.value)}>{children}</select><ChevronDown size={14}/></div></label>}
export function Modal({title,children,onClose,wide=false}:{title:string;children:ReactNode;onClose:()=>void;wide?:boolean}){
 const ref=useRef<HTMLDialogElement>(null);useEffect(()=>{ref.current?.showModal()},[]);
 return <dialog ref={ref} className={'modal '+(wide?'wide':'')} onCancel={onClose}><div className="modal-head"><h2>{title}</h2><button className="icon-button" onClick={onClose} aria-label="关闭"><X size={20}/></button></div>{children}</dialog>
}
export function Empty({icon,title,description,children}:{icon:ReactNode;title:string;description:string;children?:ReactNode}){return <div className="empty"><div className="empty-icon">{icon}</div><h3>{title}</h3><p>{description}</p>{children}</div>}
export function Busy({text='正在处理…'}:{text?:string}){return <span className="busy"><LoaderCircle size={16} className="spin"/>{text}</span>}
export function Tag({children,tone=''}:{children:ReactNode;tone?:string}){return <span className={'tag '+tone}>{children}</span>}
