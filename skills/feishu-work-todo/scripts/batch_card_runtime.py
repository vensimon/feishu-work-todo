"""Shared card storage and strictly scoped submission handling."""
import copy
import datetime
import json
import os
import pathlib
import shutil
import subprocess
import time

from runtime_paths import ROOT, CLI_ARGS, ENV, assert_identity
from assistant_control import read_control,require_enabled
WORKSPACE=ROOT
CARDS=ROOT/'cards'
CARDS.mkdir(parents=True,exist_ok=True)

def read(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default

def save(path, data):
    temp=path.with_name(path.name+'.'+str(os.getpid())+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2))
    temp.replace(path)

def cli(args):
    result=subprocess.run([*CLI_ARGS,*args],cwd=WORKSPACE,env=ENV,capture_output=True,text=True,timeout=90)
    raw=result.stdout or result.stderr
    try:data=json.loads(raw)
    except ValueError:raise RuntimeError('CLI returned an invalid response')
    if result.returncode or not data.get('ok'):
        raise RuntimeError(json.dumps(data.get('error',data),ensure_ascii=False))
    return data.get('data',{})

def patch(message_id,card):
    return cli(['im','messages','patch','--as','bot','--params',json.dumps({'message_id':message_id}),
                '--data',json.dumps({'content':json.dumps(card,ensure_ascii=False)},ensure_ascii=False)])

def refresh_card(manifest, saved_keys, count):
    card=copy.deepcopy(manifest['card'])
    if manifest.get('callback_probe'):
        card['body']['elements'][0]['content']='验证成功：已收到本人的卡片提交，没有修改任何工作待办。'
        card['header']['template']='green'
        card['header']['subtitle']['content']='卡片提交已验证'
        card['body']['elements'][1]['elements'][-1]['disabled']=True
        return card
    form=next(element for element in card['body']['elements'] if element['tag']=='form')
    for element in form['elements']:
        key=manifest['mapping'].get(element.get('name'),{}).get('key')
        if key in saved_keys:
            element['checked']=True
            element['disabled']=True
    left=sum(element.get('tag')=='checker' and not element.get('checked') for element in form['elements'])
    for element in form['elements']:
        if element.get('form_action_type')=='submit':
            element['disabled']=left==0
            style=manifest.get('style',{})
            element['text']['content']=style.get('complete_text','全部已完成') if left==0 else style.get('submit_text','确定完成')
    card['body']['elements'][0]['content']=f'**已保存本次选择：{count} 项**\n剩余 {left} 项可继续勾选；未勾选的保持待办。'
    card['header']['subtitle']['content']=f'剩余 {left} 项 · 勾选后统一保存'
    if left==0:card['header']['template']='green'
    return card

def process(event):
    if not read_control()['enabled']:return {'ignored':'assistant_disabled'}
    generation=require_enabled()
    state=read(ROOT/'state.json')
    if event.get('operator_id')!=state['recipient_open_id']:
        return {'ignored':'different_operator'}
    mid=event.get('message_id','')
    if not mid.startswith('om_') or '/' in mid:
        return {'ignored':'invalid_message'}
    file=CARDS/(mid+'.json')
    manifest=read(file)
    if not manifest or manifest.get('preview'):
        return {'ignored':'unregistered_or_preview_card'}
    assert_identity(state)
    if event.get('action_tag')!='button' or event.get('action_name')!='submit_done':
        return {'ignored':'not_batch_submit'}
    values=event.get('form_value') or '{}'
    values=json.loads(values) if isinstance(values,str) else values
    if not isinstance(values,dict):raise ValueError('Invalid submitted form')
    selected=[]
    for name,record in manifest['mapping'].items():
        value=values.get(name,False)
        if type(value) is not bool:raise ValueError('Checkbox values must be booleans')
        if value:selected.append(record)
    event_id=event.get('event_id')
    ledger=read(ROOT/'card-submissions.json',[])
    if event_id and any(row.get('event_id')==event_id for row in ledger):
        return {'ignored':'duplicate_event'}
    # Accept only the fixed keys/record IDs issued with this exact message.
    current={item['key']:item.get('base_record_id') for item in state['items']}
    for item in selected:
        if current.get(item['key'])!=item['record_id']:
            raise ValueError('Stale or unknown task mapping')
    if selected:
        require_enabled(generation)
        updates={item['record_id']:{'处理完毕':True} for item in selected}
        result=cli(['base','+record-batch-update','--as','user','--base-token',state['base']['base_token'],
                    '--table-id',state['base']['table_id'],'--json',json.dumps({'update_records':updates},ensure_ascii=False)])
        if set(result.get('record_id_list',[]))!=set(updates):
            raise RuntimeError('Server did not confirm every selected record')
    saved_keys=set(manifest.get('saved_keys',[]))|{item['key'] for item in selected}
    updated=refresh_card(manifest,saved_keys,len(selected))
    manifest.update(card=updated,saved_keys=sorted(saved_keys))
    save(file,manifest)
    entry={'event_id':event_id,'message_id':mid,'selected_keys':[item['key'] for item in selected],
           'selected_count':len(selected),'saved':True,'saved_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    ledger.append(entry)
    save(ROOT/'card-submissions.json',ledger)
    try:
        patch(mid,updated)
        entry['card_updated']=True
    except Exception as error:
        entry['card_updated']=False
        entry['card_update_error']=str(error)
    save(ROOT/'card-submissions.json',ledger)
    return entry
