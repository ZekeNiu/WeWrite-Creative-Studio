"""Tool conversations over the user's existing three text protocols.

No hidden retries and no fallback to a text-only workflow. Wire messages are
retained between turns, including provider reasoning/signature blocks.
"""
import json
import time
import httpx
from . import providers,store
from .service_errors import http_failure,connection_failure,bind,ServiceFailure


def request_body(service, system, messages, tools):
    protocol = service['protocol']
    body = dict(model=service['model'], stream=False)
    maximum = service.get('max_tokens', 8000)
    if protocol == 'chat':
        path = 'chat/completions'
        body.update(messages=[dict(role='system', content=system), *messages], max_tokens=maximum,
                    tools=[dict(type='function', function=t) for t in tools])
    elif protocol == 'responses':
        path = 'responses'
        body.update(instructions=system, input=messages, max_output_tokens=maximum, store=False,include=['reasoning.encrypted_content'],
                    tools=[dict(type='function', strict=False, **t) for t in tools])
    else:
        path = 'messages'
        body.update(system=system, messages=messages, max_tokens=maximum,
                    tools=[dict(name=t['name'], description=t['description'], input_schema=t['parameters']) for t in tools])
    if service.get('temperature') is not None: body['temperature'] = service['temperature']
    choice=providers.tool_choice(service)
    body['tool_choice']={'type':'any' if choice=='required' else choice} if protocol=='anthropic' else choice
    return path, body


def diagnostic(service,data,status=200):
    """Counts and allowlisted metadata only, never response text or tool arguments."""
    data=data if isinstance(data,dict) else {}
    reason=data.get('stop_reason') or data.get('status');texts=[];calls=[];refused=False
    choices=data.get('choices')
    if isinstance(choices,list) and choices and isinstance(choices[0],dict):
        reason=choices[0].get('finish_reason');message=choices[0].get('message') or {}
        if isinstance(message,dict):
            texts=[message.get('content')];calls=message.get('tool_calls') or [];refused=bool(message.get('refusal'))
    else:
        output=data.get('output') or data.get('content') or []
        if isinstance(output,list):
            for item in output:
                if not isinstance(item,dict):continue
                if item.get('type') in ('function_call','tool_use'):calls.append(item)
                if item.get('type')=='text':texts.append(item.get('text'))
                if item.get('type')=='refusal':refused=True
                for part in item.get('content',[]) if isinstance(item.get('content'),list) else []:
                    if isinstance(part,dict):
                        texts.append(part.get('text'));refused=refused or part.get('type')=='refusal'
    incomplete=data.get('incomplete_details') or {}
    if isinstance(incomplete,dict) and incomplete.get('reason')=='max_output_tokens':reason='max_output_tokens'
    allowed={'stop','tool_calls','length','content_filter','completed','incomplete','failed','end_turn','tool_use','max_tokens','max_output_tokens','refusal','pause_turn'}
    value=dict(request_sent=True,response_received=True,http_status=status,
        finish_reason=reason if isinstance(reason,str) and reason in allowed else 'unknown',
        text_chars=sum(len(t) for t in texts if isinstance(t,str)),tool_count=len(calls) if isinstance(calls,list) else 0,
        refusal=bool(refused or reason in ('refusal','content_filter')),
        parameters=dict(max_tokens=service.get('max_tokens',8000),temperature=service.get('temperature'),tool_choice=providers.tool_choice(service)))
    return value


def save_diagnostic(service,value):
    if service.get('_job_id'):
        store.update_job(service['_job_id'],response_diagnostic=value)
        store.event(service['_job_id'],'model_response',**value)


def response_error(service,category,message,info,usage=None):
    error=bind(ServiceFailure(message,category=category,**info),service)
    error.usage=usage or dict(status='unknown',estimated_cost=None)
    return error


def decode(protocol, data):
    if data.get('error'): raise ValueError('模型工具请求返回错误，请检查服务权限和额度')
    if protocol == 'chat':
        choices = data.get('choices', [])
        if len(choices) != 1: raise ValueError('工具请求未返回唯一结果')
        choice = choices[0]
        if choice.get('finish_reason') not in ('stop', 'tool_calls'):
            raise ValueError('工具响应未完整结束；不自动重试')
        message = dict(choice['message'])
        calls = [dict(id=x['id'], name=x['function']['name'], arguments=x['function']['arguments']) for x in message.get('tool_calls', [])]
        return [message], calls, message.get('content') or ''
    if protocol == 'responses':
        if data.get('status') != 'completed': raise ValueError('工具响应未完整结束；不自动重试')
        output = data.get('output', [])
        calls = [dict(id=x['call_id'], name=x['name'], arguments=x['arguments']) for x in output if x.get('type') == 'function_call']
        text = ''.join(c.get('text', '') for x in output for c in x.get('content', []) if c.get('type') == 'output_text')
        return output, calls, text
    if data.get('stop_reason') not in ('end_turn', 'tool_use'): raise ValueError('工具响应未完整结束；不自动重试')
    content = data.get('content', [])
    calls = [dict(id=x['id'], name=x['name'], arguments=x['input']) for x in content if x.get('type') == 'tool_use']
    return [dict(role='assistant', content=content)], calls, ''.join(x.get('text', '') for x in content if x.get('type') == 'text')


def append_results(protocol, messages, results):
    if protocol == 'anthropic':
        messages.append(dict(role='user', content=[dict(type='tool_result', tool_use_id=cid, content=value) for cid, value in results]))
    elif protocol == 'responses':
        messages.extend(dict(type='function_call_output', call_id=cid, output=value) for cid, value in results)
    else:
        messages.extend(dict(role='tool', tool_call_id=cid, content=value) for cid, value in results)


async def turn(service, system, messages, tools):
    path, body = request_body(service, system, messages, tools)
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(240, connect=20)) as client:
            response = await client.post(providers.endpoint(service['base_url'], path), headers=providers.headers(service), json=body)
            if response.status_code >= 400:
                error=bind(http_failure(response.status_code,response.text,response.headers),service)
                save_diagnostic(service,dict(diagnostic(service,{},response.status_code),category=error.details['category']))
                raise error
            try:data = response.json()
            except ValueError:
                info=diagnostic(service,{},response.status_code);save_diagnostic(service,info)
                raise response_error(service,'malformed_response','模型响应不是有效 JSON；已停止，请检查当前接口',info) from None
    except httpx.HTTPError as exc:
        save_diagnostic(service,dict(request_sent=True,response_received=False,parameters=providers.test_parameters(service,'tools')))
        raise bind(connection_failure(exc),service) from None
    info=diagnostic(service,data,response.status_code)
    if not isinstance(data,dict):
        save_diagnostic(service,info)
        raise response_error(service,'malformed_response','模型响应结构异常；已停止',info)
    if data.get('error'):
        save_diagnostic(service,info)
        raise bind(http_failure(response.status_code,json.dumps(data),response.headers),service)
    usage = data.get('usage') or {}
    if not isinstance(usage,dict):usage={}
    inp, out = usage.get('input_tokens', usage.get('prompt_tokens')), usage.get('output_tokens', usage.get('completion_tokens'))
    inp=inp if type(inp) is int and inp>=0 else None
    out=out if type(out) is int and out>=0 else None
    cost = None
    if inp is not None and out is not None and all(service.get(k) is not None for k in ('input_price', 'output_price')):
        cost = (inp * service['input_price'] + out * service['output_price']) / 1_000_000
    usage=dict(model=service['model'], service=service.get('name',''),
        input_tokens=inp, output_tokens=out, estimated_cost=cost, currency=service.get('currency','CNY'),
        seconds=round(time.monotonic()-started, 2), status='completed')
    info['usage']={k:usage[k] for k in ('input_tokens','output_tokens','estimated_cost','currency')}
    save_diagnostic(service,info)
    if info['refusal']:raise response_error(service,'refusal','模型明确拒绝了本次请求；已保留任务，不自动纠正',info,usage)
    if info['finish_reason'] in ('length','max_tokens','max_output_tokens'):
        raise response_error(service,'output_truncated','模型输出达到单次回复上限而截断；请核对输出上限后重新运行',info,usage)
    try:
        wire,calls,text=decode(service['protocol'],data)
        if not isinstance(text,str):raise ValueError('Invalid text')
        ids=[c['id'] for c in calls]
        if len(set(ids))!=len(ids):raise ValueError('Duplicate tool ids')
        for call in calls:
            if not isinstance(call['id'],str) or not call['id'] or not isinstance(call['name'],str):raise ValueError('Invalid tool identity')
            args=json.loads(call['arguments']) if isinstance(call['arguments'],str) else call['arguments']
            if not isinstance(args,dict):raise ValueError('Invalid tool arguments')
    except (ValueError,KeyError,TypeError,AttributeError):
        raise response_error(service,'malformed_response','模型返回的结果或工具调用格式不完整；已停止并保留诊断',info,usage) from None
    return dict(wire=wire,calls=calls,text=text,usage=usage,diagnostic=info)
