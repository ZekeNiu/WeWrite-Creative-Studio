"""Tool conversations over the user's existing three text protocols.

No hidden retries and no fallback to a text-only workflow. Wire messages are
retained between turns, including provider reasoning/signature blocks.
"""
import json
import time
import httpx
from . import providers


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
    return path, body


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
                raise ValueError(providers.http_error(response.status_code, response.text))
            data = response.json()
    except httpx.HTTPError:
        raise ValueError('模型工具连接中断或超时；本次可能计费，已保留任务，不自动重试') from None
    usage = data.get('usage', {})
    inp, out = usage.get('input_tokens', usage.get('prompt_tokens')), usage.get('output_tokens', usage.get('completion_tokens'))
    cost = None
    if inp is not None and out is not None and all(service.get(k) is not None for k in ('input_price', 'output_price')):
        cost = (inp * service['input_price'] + out * service['output_price']) / 1_000_000
    wire, calls, text = decode(service['protocol'], data)
    ids = [c['id'] for c in calls]
    if len(set(ids)) != len(ids): raise ValueError('模型返回了重复工具调用编号')
    return dict(wire=wire, calls=calls, text=text, usage=dict(model=service['model'], service=service.get('name',''),
        input_tokens=inp, output_tokens=out, estimated_cost=cost, currency=service.get('currency','CNY'),
        seconds=round(time.monotonic()-started, 2), status='completed'))
