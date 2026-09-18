export async function api<T=any>(url:string,method='GET',body?:unknown):Promise<T>{
  const isForm=body instanceof FormData;
  let response:Response;
  try{response=await fetch('/api'+url,{method,headers:{'X-Studio-Request':'1',...(body&&!isForm?{'Content-Type':'application/json'}:{})},body:body?(isForm?body:JSON.stringify(body)):undefined})}
  catch{throw new Error('无法连接本地工作台，请重新双击启动文件；已有文章保存在本机。')}
  if(!response.ok){let data;try{data=await response.json()}catch{data={detail:'无法连接工作台，请检查是否已启动'}};
    throw new Error(typeof data.detail==='string'?data.detail:'输入内容格式不正确，请检查后重试');}
  return response.json();
}
export const date=(s:string)=>new Date(s).toLocaleString('zh-CN',{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'});
export const errorText=(e:unknown)=>e instanceof Error?e.message:String(e);
