import {useEffect,useState} from 'react';

function olderVersion(left:string,right:string){
 const a=left.split('.').map(Number),b=right.split('.').map(Number);
 for(let i=0;i<3;i++){if(a[i]!==b[i])return a[i]<b[i]}
 return false;
}

export default function VersionNotice({busy,onRefresh}:{busy:boolean;onRefresh:()=>Promise<void>}){
 const [runtime,setRuntime]=useState<{version:string;available_version?:string}|null>(null);
 useEffect(()=>{
  let active=true;let checking=false;
  async function check(){
   if(checking)return;checking=true;
   try{const response=await fetch('/api/health',{cache:'no-store'});if(response.ok){const value=await response.json();if(active)setRuntime(value)}}catch{/* A restart may briefly close the connection. */}finally{checking=false}
  }
  void check();const interval=setInterval(check,15000);window.addEventListener('focus',check);
  return()=>{active=false;clearInterval(interval);window.removeEventListener('focus',check)};
 },[]);
 if(!runtime)return null;
 const available=runtime.available_version||runtime.version;
 const restart=runtime.version!==available||olderVersion(runtime.version,__APP_VERSION__);
 if(runtime.version===__APP_VERSION__&&available===__APP_VERSION__)return null;
 return <div className="notice amber version-notice" role="status"><div><strong>工作台版本尚未同步</strong><p>页面 v{__APP_VERSION__} · 后台 v{runtime.version}</p>
  <p>{restart?'请重新双击“启动工作台”切换到新版后台；若有生成任务，请待任务结束后再次启动。完成后刷新页面。':'后台已更新，保存当前内容后刷新即可使用新版界面。'}</p></div>
  {!restart&&<button className="button secondary" disabled={busy} onClick={()=>void onRefresh()}>保存并刷新页面</button>}
 </div>;
}
