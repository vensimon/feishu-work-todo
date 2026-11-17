"""Collect evidence only after topic groups/nonhuman DMs have been excluded."""
import concurrent.futures
import datetime as dt
import json
import pathlib
from runtime_paths import ROOT,cli_json,assert_identity,prepare_storage
from online_config import sync,get_config

def main():
    state=json.loads((ROOT/'state.json').read_text());assert_identity(state);prepare_storage()
    config_sync=sync();settings=get_config()['collection']
    zone=dt.timezone(dt.timedelta(hours=8));end=dt.datetime.now(zone).replace(microsecond=0)
    watermark=state.get('last_successful_scan_at')
    start=dt.datetime.fromisoformat(watermark)-dt.timedelta(hours=settings['overlap_hours']) if watermark else end-dt.timedelta(days=settings['first_scan_days'])
    if start.tzinfo is None:raise ValueError('Scan watermark must include timezone')
    folder=ROOT/'evidence'/end.strftime('%Y%m%dT%H%M%S');folder.mkdir(parents=True)
    listing=cli_json(['im','+chat-list','--as','user','--types','p2p,group','--sort','active_time',
                      '--page-size','100','--page-all','--page-limit','100'],cwd=ROOT)
    if listing.get('meta',{}).get('pagination',{}).get('complete') is not True:
        raise RuntimeError('Conversation metadata is incomplete; do not read an unverified scope')
    social=settings['exclude_groups_containing']
    excluded_ids=set(state.get('excluded_chat_ids',[]))
    allowed=[];excluded=[]
    for chat in listing['data']['chats']:
        mode=chat.get('chat_mode');reason=None
        if mode not in ['group','p2p']:reason='topic_or_unknown'
        elif mode=='p2p' and chat.get('p2p_target_type')!='user':reason='nonhuman_dm'
        elif chat['chat_id'] in excluded_ids:reason='user_excluded'
        elif mode=='group' and any(word in chat.get('name','') for word in social):reason='obvious_social'
        if reason:excluded.append({'chat_id':chat['chat_id'],'reason':reason})
        else:allowed.append(chat)
    (folder/'allowed.json').write_text(json.dumps(allowed,ensure_ascii=False))
    (folder/'excluded.json').write_text(json.dumps(excluded,ensure_ascii=False))
    def batch(pair):
        index,chats=pair;ids=[c['chat_id'] for c in chats];messages=[];cursor=None
        args=['im','+messages-search','--as','user','--query','','--chat-id',','.join(ids),
              '--start',start.isoformat(),'--end',end.isoformat(),'--page-size','50','--page-all','--page-limit','40','--no-reactions']
        while True:
            result=cli_json(args+(['--page-token',cursor] if cursor else []),cwd=ROOT)
            data=result['data'];messages.extend(data.get('messages',[]))
            if data.get('has_more') is False:break
            next_cursor=data.get('page_token')
            if not next_cursor or next_cursor==cursor:raise RuntimeError('Message pagination stalled')
            cursor=next_cursor
        if any(m.get('chat_id') not in ids for m in messages):raise RuntimeError('Out-of-scope message returned')
        (folder/('batch-'+str(index)+'.json')).write_text(json.dumps({'complete':True,'messages':messages},ensure_ascii=False))
        return messages
    batches=[allowed[i:i+50] for i in range(0,len(allowed),50)]
    merged={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for messages in pool.map(batch,enumerate(batches)):
            for message in messages:merged[message['message_id']]=message
    (folder/'messages.json').write_text(json.dumps(list(merged.values()),ensure_ascii=False))
    result={'complete':True,'start':start.isoformat(),'through':end.isoformat(),'messages':len(merged),
            'evidence_directory':str(folder),'topics_and_other_exclusions':len(excluded),'eligible_chats':len(allowed),
            'config_version':get_config()['version'],'rules_file':config_sync['rules_file'],'config_sync_mode':config_sync['mode']}
    (folder/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
