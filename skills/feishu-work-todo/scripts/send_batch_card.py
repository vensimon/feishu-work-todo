"""Send one checklist, or activate the previously reviewed preview in place."""
import argparse
import datetime
import subprocess
import sys
import time
import json
import os
import pathlib
SOURCE_ROOT=pathlib.Path(__file__).resolve().parent
from runtime_paths import assert_identity
from batch_card_runtime import ROOT,CARDS,read,save,cli,patch
from render_batch_card import build
from online_config import sync,get_config
from assistant_control import require_enabled,guarded_wait,run_guarded

def main():
    generation=require_enabled()
    parser=argparse.ArgumentParser()
    parser.add_argument('--batch',required=True)
    parser.add_argument('--activate-preview',action='store_true')
    parser.add_argument('--not-before',help='Earliest send time in Beijing, HH:MM')
    args=parser.parse_args()
    runs=read(ROOT/'batch-card-runs.json',{})
    if args.batch in runs:
        print(json.dumps({'ok':True,'existing':True,**runs[args.batch]},ensure_ascii=False));return
    if args.not_before:
        zone=datetime.timezone(datetime.timedelta(hours=8))
        now=datetime.datetime.now(zone)
        target=datetime.datetime.combine(now.date(),datetime.time.fromisoformat(args.not_before),zone)
        remaining=(target-now).total_seconds()
        if remaining>3600:raise RuntimeError('Send preparation started over one hour early')
        if remaining>0:print(json.dumps({'waiting_until':target.isoformat()}),flush=True)
        while remaining>0:
            guarded_wait(min(remaining,30),generation)
            remaining=(target-datetime.datetime.now(zone)).total_seconds()
        # Re-read checkbox state at send time so an item finished during preparation is excluded.
        for script in ['sync_base_status.py','dashboard_support.py']:
            result=subprocess.run([sys.executable,str(SOURCE_ROOT/script)],cwd=SOURCE_ROOT.parents[1],capture_output=True,text=True)
            if result.returncode:raise RuntimeError(result.stderr or result.stdout)
    state=read(ROOT/'state.json')
    assert_identity(state)
    if not state.get('setup',{}).get('callback_roundtrip_verified'):
        raise RuntimeError('Run verify_callback.py send/check before sending interactive work checklists')
    save(ROOT/'state.json',state)
    service=read(ROOT/'card-service-status.json',{})
    if not service.get('ready'):raise RuntimeError('Card submission service is not connected')
    for key in ['pid','consumer_pid']:
        try:os.kill(int(service[key]),0)
        except (KeyError,ValueError,ProcessLookupError):raise RuntimeError('Card submission service is not running')
    runs=read(ROOT/'batch-card-runs.json',{})
    if args.batch in runs:
        print(json.dumps({'ok':True,'existing':True,**runs[args.batch]},ensure_ascii=False));return
    config_sync=sync();config=get_config()
    require_enabled(generation)
    card,mapping=build(state['items'],False,config)
    manifest={'preview':False,'batch':args.batch,'mapping':mapping,'card':card,'saved_keys':[],
              'style':config['style'],'config_version':config['version']}
    if args.activate_preview:
        mid=state['batch_card_preview_message_id']
        save(CARDS/(mid+'.json'),manifest)
        patch(mid,card)
    else:
        result=cli(['im','+messages-send','--as','bot','--user-id',state['recipient_open_id'],
                    '--msg-type','interactive','--content',json.dumps(card,ensure_ascii=False),
                    '--idempotency-key','todo-form-'+args.batch])
        mid=result['message_id']
        save(CARDS/(mid+'.json'),manifest)
    runs[args.batch]={'message_id':mid,'items':len(mapping)}
    save(ROOT/'batch-card-runs.json',runs)
    print(json.dumps({'ok':True,**runs[args.batch],'config_version':config['version'],'config_sync_mode':config_sync['mode']},ensure_ascii=False))

if __name__=='__main__':run_guarded(main)
