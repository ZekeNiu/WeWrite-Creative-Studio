"""Extract exactly one schema-valid JSON object without a paid repair call."""
import json


def parse(raw,schema):
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
    if len(candidates)!=1: raise ValueError('需要唯一、完整且符合约定的 JSON 结果')
    return candidates[0]
