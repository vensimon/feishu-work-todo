"""Verify a real card roundtrip without creating or completing a work item."""
import argparse
import datetime
import json
import os
import uuid
from runtime_paths import ROOT,assert_identity,write_state
from batch_card_runtime import CARDS,read,save,cli
from render_batch_card import build
from assistant_control import require_enabled,run_guarded

def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['send','check'])
    args=parser.parse_args()
    if args.action=='send':require_enabled()
    state=read(ROOT/'state.json');assert_identity(state)
    probe=ROOT/'callback-probe.json'
    if args.action=='check':
        mid=read(probe,{}).get('message_id')
        result=next((e for e in reversed(read(ROOT/'card-submissions.json',[]))
                     if e.get('message_id')==mid and e.get('saved') and e.get('card_updated')),None)
        if not result:raise RuntimeError('No successful submission/card update yet. Ask the user to click the verification button.')
        state.setdefault('setup',{})['callback_roundtrip_verified']=True
        state['setup']['callback_verified_at']=result['saved_at'];write_state(state)
        print(json.dumps({'ok':True,'callback_roundtrip_verified':True}));return
    service=read(ROOT/'card-service-status.json',{})
    if not service.get('ready'):raise RuntimeError('Start and check the card receiver first')
    for key in ['pid','consumer_pid']:os.kill(int(service[key]),0)
    card,mapping=build([])
    card['header']['title']['content']='待办助手 · 提交验证'
    card['header']['subtitle']['content']='仅验证，不涉及工作待办'
    card['body']['elements'][0]['content']='请点击下方按钮，验证清单提交能否保存。不会创建或完成任何工作待办。'
    button=card['body']['elements'][1]['elements'][-1]
    button['disabled']=False;button['text']['content']='验证提交'
    data=cli(['im','+messages-send','--as','bot','--user-id',state['recipient_open_id'],
              '--msg-type','interactive','--content',json.dumps(card,ensure_ascii=False),
              '--idempotency-key','todo-probe-'+str(uuid.uuid4())])
    mid=data['message_id']
    save(CARDS/(mid+'.json'),{'callback_probe':True,'preview':False,'mapping':mapping,'card':card,'saved_keys':[]})
    save(probe,{'message_id':mid,'sent_at':datetime.datetime.now(datetime.timezone.utc).isoformat()})
    print(json.dumps({'ok':True,'message_id':mid,'next':'User clicks verification button, then run check'}))

if __name__=='__main__':run_guarded(main)
