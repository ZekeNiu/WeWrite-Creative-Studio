"""User-owned upstream personas and themes; account revision controls all changes."""
import copy
import re
import yaml
from . import account_memory, native_skills, prompts, store


def identifier(value):
    if not isinstance(value,str) or not re.fullmatch(r'user-[a-zA-Z0-9_-]{1,60}',value):raise ValueError('名称编号须以 user- 开头，仅含英文、数字、横线和下划线')
    return value


def personas():
    return [dict(id=k,name=v[0],description=v[1],example=v[2]) for k,v in prompts.PERSONAS.items()]+[
        dict(id=x['id'],name=x['label'],description=x['definition'].get('description',''),example='自定义人格') for x in account_memory.get().get('personas',[])]


def persona(id):
    value=next((x['definition'] for x in account_memory.get().get('personas',[]) if x['id']==id),None)
    if value:return copy.deepcopy(value)
    if id not in prompts.PERSONAS:raise ValueError('写作人格不存在，请重新选择')
    return yaml.safe_load((native_skills.SKILLS/'wewrite-write/personas'/f'{id}.yaml').read_text('utf-8'))


def save_persona(value):
    id=identifier(value['id']);label=str(value.get('label','')).strip()
    if not label or len(label)>100:raise ValueError('请填写人格名称，最多100字')
    definition=persona(value.get('base','industry-observer'))
    patch=value.get('definition',{})
    if not isinstance(patch,dict) or set(patch)-set(definition):raise ValueError('人格字段须使用上游定义')
    for key,item in patch.items():
        expected=definition[key]
        if isinstance(expected,(float,int)):
            if isinstance(item,bool) or not isinstance(item,(float,int)) or not 0<=item<=1000:raise ValueError('人格参数无效')
        elif isinstance(expected,list):
            if not isinstance(item,list) or any(not isinstance(x,str) for x in item):raise ValueError('表达示例应为文本列表')
        elif not isinstance(item,str):raise ValueError('人格描述应为文字')
    definition.update(patch);definition['name']=id
    if len(store.encode(definition))>30000:raise ValueError('人格定义过长')
    def mutate(v):
        rows=v.setdefault('personas',[]);old=next((x for x in rows if x['id']==id),None)
        row=dict(id=id,label=label,definition=definition,updated=store.now())
        if old:rows[rows.index(old)]=row
        else:rows.append(row)
    return account_memory.change(value['revision'],mutate,'保存自定义上游人格')


def theme(id):return next((x for x in account_memory.get().get('themes',[]) if x['id']==id),None)


def save_theme(revision,id,label,definition,url):
    identifier(id)
    if not isinstance(definition,dict) or not all(k in definition for k in ('name','description','base_css','colors')):raise ValueError('上游主题产物不完整')
    def mutate(v):
        rows=v.setdefault('themes',[])
        if any(x['id']==id for x in rows):raise ValueError('主题编号已存在，请换一个编号；不会覆盖已有主题')
        rows.append(dict(id=id,label=label or id,definition=definition,source=url,created=store.now()))
    return account_memory.change(revision,mutate,'学习上游排版主题')
