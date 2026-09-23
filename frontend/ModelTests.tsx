import {type Settings,type ModelCard,LABELS} from './types';
import {Select,Tag} from './ui';

export function modelCards(cfg:Settings):ModelCard[]{
 const rows=new Map<string,ModelCard>();
 function add(sid:string,model:string,role:string){const service=cfg.services.find(s=>s.id===sid);if(!service)return;model=model||service.model;const key=JSON.stringify([sid,model]);
  const saved=cfg.model_capabilities?.find(c=>c.service_id===sid&&c.model===model);
  const profile=cfg.model_connections?.find(c=>c.service_id===sid&&c.model===model);
  const selected=sid===(cfg.search.native_service_id||cfg.default_service)&&model===(cfg.search.native_model||service.model);
  const card=rows.get(key)||{service_id:sid,model,name:service.name,roles:[],search_protocol:profile?.search_protocol||(selected?cfg.search.native_protocol:'inherit'),capabilities:saved?.capabilities||{}};
  if(!card.roles.includes(role))card.roles.push(role);rows.set(key,card);
 }
 cfg.services.forEach(s=>add(s.id,s.model,'default'));
 ['topic','sources','research','outline','write','review','revise','visual','image','layout_advice'].forEach(role=>{const r=cfg.routes[role]||{};const inherited=role==='research'&&!r.service_id?cfg.routes.sources:undefined;add(r.service_id||inherited?.service_id||cfg.default_service,r.model||inherited?.model||'',role)});
 add(cfg.search.native_service_id||cfg.default_service,cfg.search.native_model,'search');
 return [...rows.values()];
}

const STATES:Record<string,string>={tested:'已通过',failed:'未通过',unused:'待配置接入方式',unconfigured:'未配置',untested:'尚未测试'};
export default function ModelTests({cfg,busy,onProtocol,onTest}:{cfg:Settings;busy:boolean;onProtocol:(card:ModelCard,protocol:string)=>void;onTest:(card:ModelCard,kind:string)=>void}){
 const cards=modelCards(cfg);
 return <><div className="section-intro"><h3>按模型验证能力</h3><p>每次只测试点击的模型与能力，不改变创作分工。测试会真实调用接口，可能产生费用；图片测试生成 1 张图片，工具测试使用 2 次文本请求。</p></div>
 {!cards.length&&<p className="muted">请先在“模型服务”中添加服务和模型。</p>}
 {cards.map(c=><section className="service-card model-test-card" key={JSON.stringify([c.service_id,c.model])}><h3>{c.name}</h3><p className="model-id">{c.model||'未填写模型'}</p><p className="muted small-text">{c.roles.map(r=>r==='default'?'服务默认模型':r==='search'?'联网搜索':LABELS[r]||r).join(' · ')}</p>
 <div className="model-capabilities">{[['text','测试文本连接'],['tools','测试工具调用'],['image','测试图片生成'],['search','测试联网搜索']].map(([kind,label])=>{const r=c.capabilities[kind];return <div className="model-capability" key={kind}><button className="button secondary" disabled={busy||!c.model} onClick={()=>onTest(c,kind)}>{label}</button><Tag tone={r?.status==='tested'?'green':r?.status==='failed'?'amber':''}>{STATES[r?.status||'untested']||'尚未测试'}</Tag>{r?.at&&<small className="muted">{new Date(r.at).toLocaleString()}</small>}{r?.message&&<p className="small-text">{r.message}</p>}</div>})}</div>
 <details><summary>联网接入方式与测试详情</summary><Select label={c.name+' · '+c.model+' 联网接入方式'} value={c.search_protocol} onChange={p=>onProtocol(c,p)}><option value="inherit">沿用文本协议</option><option value="responses">OpenAI Responses · web_search</option><option value="anthropic">Anthropic Messages · web_search</option><option value="gemini">Gemini · Google Search</option></Select><p className="muted small-text">联网接入独立于文本协议。未通过只说明当前接入未验证，不能据此判断模型本身不支持。</p>{c.capabilities.text?.reply&&<p>文本回复：{c.capabilities.text.reply}</p>}{c.capabilities.search?.sources?.map((r,i)=><p key={i}><a className="text-link research-url" href={r.url} target="_blank" rel="noreferrer">{r.title||r.url}</a></p>)}</details>
 {c.capabilities.image?.status==='tested'&&c.capabilities.image.image_url&&<img className="connection-preview" src={c.capabilities.image.image_url} alt={c.name+' 实际生成的测试图片'}/>}
 </section>)}</>;
}
