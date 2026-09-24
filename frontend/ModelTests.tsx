import {type Settings,type ModelCard,LABELS} from './types';
import {Select,Tag} from './ui';
import {TEXT_PROTOCOLS,SEARCH_PROTOCOLS,ResponseDetails,FailureDetails} from './ServiceDetails';

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

const STATES:Record<string,string>={tested:'已通过',failed:'未通过',unused:'尚未发送搜索请求',unconfigured:'未配置',untested:'尚未测试'};
export default function ModelTests({cfg,busy,onProtocol,onTest}:{cfg:Settings;busy:boolean;onProtocol:(card:ModelCard,protocol:string)=>void;onTest:(card:ModelCard,kind:string)=>void}){
 const cards=modelCards(cfg);
 return <><div className="section-intro"><h3>按模型验证能力</h3><p>每次只测试点击的模型与能力，不改变创作分工。测试会真实调用接口，可能产生费用；图片测试生成 1 张图片，工具测试使用实际服务参数进行 2 次请求。基础测试通过不代表完整选题流程已通过。</p></div>
 {!cards.length&&<p className="muted">请先在“模型服务”中添加服务和模型。</p>}
 {cards.map(c=><section className="service-card model-test-card" key={JSON.stringify([c.service_id,c.model])}><h3>{c.name}</h3><p className="model-id">{c.model||'未填写模型'}</p><p className="muted small-text">{c.roles.map(r=>r==='default'?'服务默认模型':r==='search'?'联网搜索':LABELS[r]||r).join(' · ')}</p>
 <Select label={c.name+" · "+c.model+" 模型原生联网接口"} value={c.search_protocol} onChange={p=>onProtocol(c,p)}>{SEARCH_PROTOCOLS.map(([id,label])=><option key={id} value={id}>{label}</option>)}</Select><p className="muted small-text">联网接入独立于文本与工具接口；请按当前服务商开放的能力选择。DeepSeek 可通过兼容 Messages 的搜索接入验证，需服务商支持，不能仅凭模型品牌确认。未接入原生搜索的模型仍可配合工作台已配置的搜索服务使用。</p><p className="muted small-text">配置这里不会改变选题模型或全局联网模型；测试仅验证本次接入。</p><div className="model-capabilities">{[['text','测试文本连接（小样本）'],['tools','测试工具调用'],['image','测试图片生成'],['search','测试联网搜索']].map(([kind,label])=>{const r=c.capabilities[kind];return <div className="model-capability" key={kind}><button className="button secondary" disabled={busy||!c.model} onClick={()=>onTest(c,kind)}>{label}</button><Tag tone={r?.status==='tested'?'green':r?.status==='failed'?'amber':''}>{STATES[r?.status||'untested']||'尚未测试'}</Tag>{r?.at&&<small className="muted">{new Date(r.at).toLocaleString()}</small>}{r?.message&&<p className="small-text">{r.message}</p>}</div>})}</div>
 <details><summary>测试参数与详细结果</summary>{Object.entries(c.capabilities).map(([kind,r])=><div key={kind}><strong>{({text:"文本连接",tools:"工具调用",image:"图片生成",search:"联网搜索"} as Record<string,string>)[kind]}</strong>{r.protocol&&<p className="small-text">实际接口：{[...TEXT_PROTOCOLS,...SEARCH_PROTOCOLS].find(([id])=>id===r.protocol)?.[1]||r.protocol} · 测试版本：{r.test_version||"历史测试，参数未记录"}</p>}{r.failure?<><FailureDetails value={r.failure}/>{!r.failure.parameters&&<ResponseDetails value={r}/>}</>:<ResponseDetails value={r.diagnostic||r}/>}</div>)}{c.capabilities.text?.reply&&<p>文本回复：{c.capabilities.text.reply}</p>}{c.capabilities.search?.sources?.map((r,i)=><p key={i}><a className="text-link research-url" href={r.url} target="_blank" rel="noreferrer">{r.title||r.url}</a></p>)}</details>
 {c.capabilities.image?.status==='tested'&&c.capabilities.image.image_url&&<img className="connection-preview" src={c.capabilities.image.image_url} alt={c.name+' 实际生成的测试图片'}/>}
 </section>)}</>;
}
