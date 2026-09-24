import {type ResponseDiagnostic,type ServiceFailure,type SearchDiagnostic} from './types';

export const TEXT_PROTOCOLS=[['chat','OpenAI 兼容对话（Chat Completions）'],['responses','OpenAI 响应（Responses）'],['anthropic','Anthropic 消息（Messages）']];
export const SEARCH_PROTOCOLS=[['inherit','沿用文本与工具接口'],['responses','OpenAI 搜索（Responses · web_search）'],['anthropic','Anthropic 兼容搜索（Messages · web_search）'],['gemini','Gemini 搜索（Google Search）']];
export const ERROR_LABELS:Record<string,string>={timeout:'等待响应超时',connection:'连接中断',quota:'余额或额度不足',rate_limit:'请求限流',rate_limit_or_quota:'限制原因未明确',authentication:'凭证错误',permission:'权限不足',invalid_request:'请求不被接受',not_found:'模型或接口不存在',service_error:'模型服务错误',validation:'输入或结果需要调整',budget_exceeded:'旧版任务预算上限',unknown:'未分类错误',empty_response:'接口返回空结果',missing_tool_call:'未返回要求的工具调用',output_truncated:'输出达到上限而截断',malformed_response:'响应格式异常',refusal:'模型明确拒答',search_evidence_missing:'未取得真实搜索证据',search_limit_exceeded:'旧版搜索内部次数上限',search_unavailable:'搜索工具暂时不可用',search_tool_error:'搜索工具返回错误',search_incomplete:'搜索尚未完成'};

export function ResponseDetails({value}:{value?:ResponseDiagnostic}){
 if(!value||(!value.finish_reason&&value.tool_count===undefined&&value.text_chars===undefined&&!value.parameters))return null;
 return <dl className="failure-details">{value.finish_reason&&<><dt>结束原因</dt><dd>{value.finish_reason}</dd></>}{value.tool_count!==undefined&&<><dt>返回工具数</dt><dd>{value.tool_count}</dd></>}{value.text_chars!==undefined&&<><dt>返回文字数</dt><dd>{value.text_chars}</dd></>}{value.parameters&&<><dt>本次输出上限</dt><dd>{value.parameters.max_tokens??'不适用'} Token</dd><dt>温度</dt><dd>{value.parameters.temperature??'服务默认'}</dd></>}</dl>;
}

export function FailureDetails({value}:{value:ServiceFailure}){
 const status=value.http_status??(value.response_received===true?'已收到响应，状态未记录':value.response_received===false?'未收到 HTTP 响应':'未记录');
 return <><dl className="failure-details"><dt>错误类别</dt><dd>{ERROR_LABELS[value.category]||'其他错误'}</dd><dt>HTTP 状态</dt><dd>{status}</dd><dt>供应商错误码</dt><dd>{value.provider_code||value.provider_type||'未提供'}</dd><dt>请求编号</dt><dd>{value.request_id||'未提供'}</dd></dl><ResponseDetails value={value}/></>;
}

export function SearchDetails({value}:{value?:SearchDiagnostic}){
 if(!value)return null;
 return <div className="search-diagnostic">{value.warnings?.map((warning,i)=><p key={i} className="notice amber small-text">{warning}</p>)}<details><summary>本次搜索记录</summary>{value.service&&<p className="small-text">实际服务：{value.service.name} · {value.service.model}</p>}<dl className="failure-details">{value.finish_reason&&<><dt>搜索结束原因</dt><dd>{value.finish_reason}</dd></>}{value.partial&&<><dt>结果状态</dt><dd>回复不完整，来源待读取原文</dd></>}{!!value.tool_errors?.length&&<><dt>搜索工具错误</dt><dd>{value.tool_errors.join('、')}</dd></>}{value.max_tokens&&<><dt>搜索输出参数</dt><dd>{value.max_tokens} Token</dd></>}<dt>工作台请求</dt><dd>{value.request_count} 次</dd><dt>搜索工具调用</dt><dd>{value.tool_calls??'未提供'}</dd>{value.provider_queries!=null&&<><dt>服务端检索词</dt><dd>{value.provider_queries}</dd></>}<dt>搜索结果块</dt><dd>{value.result_blocks??'未记录'}</dd><dt>去重来源</dt><dd>{value.source_count??'未记录'}</dd>{value.usage&&<><dt>输入 / 输出 Token</dt><dd>{value.usage.input_tokens??'未知'} / {value.usage.output_tokens??'未知'}</dd></>}</dl></details></div>;
}
