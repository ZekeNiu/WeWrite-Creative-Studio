import {useEffect,useMemo,useRef,useState,type ReactNode} from 'react';
import {X} from 'lucide-react';
import {readView,remember} from './MaterialList';
import type {Stage} from './types';

export const CONTEXT_LABELS:Record<Stage,string>={topic:'选题方向',sources:'素材参考',outline:'大纲参考',write:'AI 修改',review:'审核意见',visual:'配图概况',layout:''};
type View={tab:'context'|'brief';open:boolean;drawerOpen:boolean};
export function useSidebarState(articleId:string|undefined,step:Stage){
 const [narrow,setNarrow]=useState(()=>matchMedia('(max-width: 1199px)').matches);
 const [version,setVersion]=useState(0);
 const views=useRef<Record<string,View>>({});
 useEffect(()=>{const mq=matchMedia('(max-width: 1199px)');const changed=()=>setNarrow(mq.matches);mq.addEventListener('change',changed);return()=>mq.removeEventListener('change',changed)},[]);
 const key='context-sidebar:'+articleId+':'+step;
 const view=useMemo(()=>{const saved=views.current[key]||readView<View>(key,{tab:'context',open:true,drawerOpen:false});return {...saved,tab:saved.tab==='brief'?'brief' as const:'context' as const}},[key,version]);
 function change(patch:{tab?:View['tab'];open?:boolean},target:Stage=step){
  const targetKey='context-sidebar:'+articleId+':'+target;
  const next={...(target===step?view:views.current[targetKey]||readView<View>(targetKey,{tab:'context',open:true,drawerOpen:false}))};if(patch.tab)next.tab=patch.tab;
  if(patch.open!==undefined)next[narrow?'drawerOpen':'open']=patch.open;
  views.current[targetKey]=next;remember(targetKey,next);setVersion(v=>v+1);
 }
 return {side:step!=='layout'&&(narrow?view.drawerOpen:view.open),tab:view.tab,narrow,change};
}

export default function ContextSidebar({step,tab,narrow,onTab,onClose,children}:{step:Stage;tab:'context'|'brief';narrow:boolean;onTab:(tab:'context'|'brief')=>void;onClose:()=>void;children:ReactNode}){
 const root=useRef<HTMLElement>(null);const close=useRef(onClose);close.current=onClose;
 useEffect(()=>{
  if(!narrow)return;
  const previous=document.activeElement as HTMLElement|null;
  root.current?.querySelector<HTMLButtonElement>('.context-close')?.focus();
  const key=(e:KeyboardEvent)=>{
   if(document.querySelector('dialog[open]'))return;
   if(e.key==='Escape'){e.preventDefault();close.current()}
   if(e.key==='Tab'){
    const elements=Array.from(root.current?.querySelectorAll<HTMLElement>('button:not([disabled]),input:not([disabled]),textarea:not([disabled]),select:not([disabled]),a[href],summary,[tabindex="0"]')||[]).filter(el=>el.getClientRects().length);
    const first=elements[0],last=elements[elements.length-1];
    if(e.shiftKey&&(document.activeElement===first||!root.current?.contains(document.activeElement))){e.preventDefault();last?.focus()}
    else if(!e.shiftKey&&(document.activeElement===last||!root.current?.contains(document.activeElement))){e.preventDefault();first?.focus()}
   }
  };
  document.addEventListener('keydown',key);
  const overflow=document.body.style.overflow;document.body.style.overflow='hidden';
  return()=>{document.removeEventListener('keydown',key);document.body.style.overflow=overflow;if(previous?.isConnected)previous.focus()};
 },[narrow]);
 return <>{narrow&&<div className="context-backdrop" onClick={onClose} aria-hidden="true"/>}<aside ref={root} id="context-sidebar" className={'context-sidebar '+(narrow?'context-drawer':'')} role={narrow?'dialog':undefined} aria-modal={narrow||undefined} aria-label={CONTEXT_LABELS[step]}>
  <div className="context-tabs" role="tablist" aria-label="当前环节辅助内容">{(['context','brief'] as const).map(id=><button role="tab" id={'context-tab-'+id} aria-controls="context-panel" aria-selected={tab===id} key={id} className={tab===id?'active':''} onClick={()=>onTab(id)}>{id==='brief'?'写作设置':CONTEXT_LABELS[step]}</button>)}<button className="icon-button context-close" aria-label="关闭侧栏" onClick={onClose}><X size={16}/></button></div>
  <div className="context-body" id="context-panel" role="tabpanel" aria-labelledby={'context-tab-'+tab}>{children}</div>
 </aside></>;
}
