import {type Settings,type SearchConfig} from './types';
import {modelCards} from './ModelTests';
import {Select} from './ui';

export default function SearchModel({cfg,onChange}:{cfg:Settings;onChange:(patch:Partial<SearchConfig>)=>void}){
 const s=cfg.search,cards=modelCards(cfg),selected=cfg.services.find(x=>x.id===(s.native_service_id||cfg.default_service));
 return <><Select label="联网模型" value={JSON.stringify([s.native_service_id||cfg.default_service,s.native_model||selected?.model||''])} onChange={v=>{const [service_id,model]=JSON.parse(v);const card=cards.find(c=>c.service_id===service_id&&c.model===model);onChange({native_service_id:service_id,native_model:model,native_protocol:card?.search_protocol||'inherit'})}}><option value="">请选择已配置模型</option>{cards.map(c=><option key={JSON.stringify([c.service_id,c.model])} value={JSON.stringify([c.service_id,c.model])}>{c.name} · {c.model||'未填写模型'}</option>)}</Select>
 <p className="small-text muted">用于各环节查找来源；搜索接口在“能力测试”中配置。</p></>;
}
