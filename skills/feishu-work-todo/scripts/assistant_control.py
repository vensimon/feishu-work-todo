"""Installation-local switch; shared online configuration can never override it."""
import datetime as dt
import json
import os
import time
from runtime_paths import ROOT,prepare_storage

class AssistantDisabled(RuntimeError):pass

def read_control():
    path=ROOT/'assistant-control.json'
    if not path.exists():return {'enabled':True,'generation':0,'source':'legacy_default'}
    try:
        data=json.loads(path.read_text())
        if type(data.get('enabled')) is not bool or type(data.get('generation')) is not int:raise ValueError('Invalid local switch')
        return data
    except (ValueError,OSError):return {'enabled':False,'generation':-1,'error':'本机开关文件异常，已停止工作，请从控制台重新设置。'}

def set_enabled(enabled):
    if type(enabled) is not bool:raise ValueError('The local switch must be boolean')
    prepare_storage();old=read_control()
    if old['enabled']==enabled and not old.get('error') and (ROOT/'assistant-control.json').exists():return old
    result={'enabled':enabled,'generation':max(0,old['generation'])+1,
            'updated_at':dt.datetime.now(dt.timezone.utc).isoformat(),'source':'local_user'}
    path=ROOT/'assistant-control.json';temp=path.with_name(path.name+'.'+str(os.getpid())+'.tmp')
    temp.write_text(json.dumps(result,ensure_ascii=False,indent=2))
    try:temp.chmod(0o600)
    except OSError:pass
    temp.replace(path)
    return result

def require_enabled(generation=None):
    current=read_control()
    if not current['enabled'] or (generation is not None and generation!=current['generation']):
        raise AssistantDisabled('助手已关闭或本轮已取消；保留记录，不读取聊天、不发送消息。')
    return current['generation']

def guarded_wait(seconds,generation):
    end=time.monotonic()+seconds
    while True:
        require_enabled(generation)
        left=end-time.monotonic()
        if left<=0:return
        time.sleep(min(left,0.5))

def run_guarded(function):
    try:return function()
    except AssistantDisabled as error:
        print(json.dumps({'ok':True,'skipped':'assistant_disabled','message':str(error)},ensure_ascii=False))
