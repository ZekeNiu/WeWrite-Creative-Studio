"""Extract exactly one schema-valid JSON object without a paid repair call."""
import json
import re


def restore_array_openings(raw,schema):
    """Restore only an unambiguous missing '[' before a schema-defined string list.

    No strings, numbers, IDs or ordering are changed. Object fields and truncated
    output cannot be repaired this way, and still need a fresh generation.
    """
    fields=set()
    def visit(node):
        if isinstance(node,dict):
            for name,item in node.get('properties',{}).items():
                if item.get('type')=='array' and item.get('items',{}).get('type')=='string':fields.add(name)
            for value in node.values():visit(value)
        elif isinstance(node,list):
            for value in node:visit(value)
    visit(schema.model_json_schema())
    decoder=json.JSONDecoder();insertions=[]
    def whitespace(pos):
        while pos<len(raw) and raw[pos].isspace():pos+=1
        return pos
    for match in re.finditer(r'"(?:[^"\\]|\\.)*"',raw):
        try:name=json.loads(match[0])
        except ValueError:continue
        pos=whitespace(match.end())
        if name not in fields or raw[pos:pos+1]!=':':continue
        pos=whitespace(pos+1);start=pos
        while raw[pos:pos+1]=='"':
            try:value,length=decoder.raw_decode(raw[pos:])
            except ValueError:break
            if not isinstance(value,str):break
            pos=whitespace(pos+length)
            if raw[pos:pos+1]==']':insertions.append(start);break
            if raw[pos:pos+1]!=',':break
            pos=whitespace(pos+1)
    if not insertions or len(insertions)>16:return raw
    for pos in sorted(set(insertions),reverse=True):raw=raw[:pos]+'['+raw[pos:]
    return raw


def parse(raw,schema,_restored=False):
    decoder=json.JSONDecoder();position=0;candidates=[]
    while position<len(raw):
        start=raw.find('{',position)
        if start<0: break
        try:
            value,length=decoder.raw_decode(raw[start:])
        except json.JSONDecodeError:
            position=start+1;continue
        position=start+length
        try: candidates.append(schema.model_validate(value).model_dump())
        except ValueError: continue
    if not candidates and not _restored:
        restored=restore_array_openings(raw,schema)
        if restored!=raw:return parse(restored,schema,True)
    if len(candidates)!=1: raise ValueError('需要唯一、完整且符合约定的 JSON 结果')
    return candidates[0]
