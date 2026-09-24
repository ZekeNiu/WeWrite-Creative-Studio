import {type Settings,type SearchConfig} from './types';
import SearchModel from './SearchModel';
import {Field,Toggle} from './ui';

export default function SearchPreferences({cfg,onChange}:{cfg:Settings;onChange:(patch:Partial<SearchConfig>)=>void}){
 const s=cfg.search;
 return <section className="service-card"><h3>自动查找与核对资料</h3><p className="muted">先使用已有材料，再由联网模型查找缺失的依据；资料足够就继续创作。</p>
 <Toggle checked={s.enabled} onChange={v=>onChange({enabled:v})} label="创作时自动检索与核对来源"/>
 <SearchModel cfg={cfg} onChange={onChange}/>
 <Toggle checked={s.allow_fallback!==false} onChange={v=>onChange({allow_fallback:v})} label="模型暂时不可用或证据不足时，允许后备搜索"/>
 <p className="small-text muted">没有结果时依次尝试已启用渠道。搜索超时、断连、明确限流或服务暂时故障时，仅尝试免费渠道，不重发失败的付费搜索；后续分析仍计入原预算。认证、权限、余额、预算及取消会停止任务。</p>
 <details><summary>高级设置：后备渠道、论文补查与限额</summary>
 <Toggle checked={s.browser_enabled} onChange={v=>onChange({browser_enabled:v})} label="启用备用网页搜索"/>
 <Toggle checked={s.page_render_enabled!==false} onChange={v=>onChange({page_render_enabled:v})} label="允许后台浏览器读取动态网页"/>
 <p className="muted small-text">网页搜索与原文读取分别控制；受限网站会寻找替代来源，也可上传文件或粘贴正文。</p>
 <Toggle checked={s.academic_enabled} onChange={v=>onChange({academic_enabled:v})} label="研究依据不足时补查学术资料"/>
 <Toggle checked={s.pubmed_enabled} onChange={v=>onChange({pubmed_enabled:v})} label="运动健康问题补查 PubMed / PMC"/>
 <Toggle checked={s.arxiv_enabled} onChange={v=>onChange({arxiv_enabled:v})} label="相关领域补查 arXiv 预印本"/>
 <Field label="OpenAlex 可选 Key" type="password" value={s.openalex_key??''} placeholder={s.openalex_key_set?'已加密保存，留空保持不变':'可不填写'} onCommit={v=>onChange({openalex_key:v||undefined})}/>
 <details><summary>Tavily 后备搜索</summary><Toggle checked={s.tavily_enabled} onChange={v=>onChange({tavily_enabled:v})} label="启用 Tavily"/><Field label="Tavily 调用地址" value={s.base_url} onCommit={v=>onChange({base_url:v})}/><Field label="Tavily API Key" type="password" value={s.key??''} placeholder={s.key_set?'已加密保存，留空保持不变':'可不填写'} onCommit={v=>onChange({key:v||undefined})}/><Field label="每次 Tavily 搜索价格 / 元" type="number" value={s.tavily_price??''} onCommit={v=>onChange({tavily_price:v===''?null:Number(v)})}/></details>
 <div className="form-grid"><Field label="每次任务最多搜索调用" type="number" value={s.max_calls} onCommit={v=>onChange({max_calls:Number(v)})}/><Field label="每次任务最多读取页面" type="number" value={s.max_pages} onCommit={v=>onChange({max_pages:Number(v)})}/><Field label="最多补查轮数" type="number" value={s.max_rounds} onCommit={v=>onChange({max_rounds:Number(v)})}/></div>
 <p className="small-text muted">搜索次数、页数和补查轮数限制工作量；付费请求同时受下方总请求和金额上限约束。未知费用仍保留为未知。</p>
 </details></section>;
}
