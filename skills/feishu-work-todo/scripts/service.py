"""Manage only this installation's card receiver; preserve all business data."""
import argparse
import hashlib
import json
import os
import pathlib
import plistlib
import signal
import shutil
import subprocess
import sys
import time
from runtime_paths import ROOT,PROFILE,CLI,ENV,prepare_storage,assert_identity
from assistant_control import set_enabled,read_control
from online_config import CLIENT_VERSION

def read(path,default=None):
    try:return json.loads(path.read_text()) if path.exists() else default
    except (ValueError,OSError):return default

def live(pid):
    try:os.kill(int(pid),0);return True
    except (OSError,ValueError,TypeError):return False

def status():
    state=read(ROOT/'state.json',{});control=read_control();receiver=read(ROOT/'card-service-status.json',{})
    return {'initialized':bool(state.get('recipient_open_id') and state.get('application_id')),
            'enabled':control['enabled'],'switch_error':control.get('error'),
            'receiver_connected':bool(receiver.get('ready') and live(receiver.get('pid')) and live(receiver.get('consumer_pid'))),
            'receiver_version':receiver.get('service_version'),'client_version':CLIENT_VERSION,
            'schedule_registered':bool(state.get('host_schedule',{}).get('verified'))}

def identifiers(state):
    suffix=hashlib.sha256((state['application_id']+state['recipient_open_id']).encode()).hexdigest()[:10]
    return 'com.feishu.work-todo.'+suffix,'FeishuWorkTodo-'+suffix

def process_table():
    if os.name=='nt':
        p=subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',
            'Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,CommandLine | ConvertTo-Json -Compress'],capture_output=True,text=True,check=True)
        values=json.loads(p.stdout or '[]');values=values if isinstance(values,list) else [values]
        return {int(p['ProcessId']):{'ppid':int(p['ParentProcessId']),'command':p.get('CommandLine') or ''} for p in values}
    raw=subprocess.check_output(['ps','-axo','pid=,ppid=,command='],text=True)
    result={}
    for line in raw.splitlines():
        parts=line.strip().split(None,2)
        if len(parts)==3:result[int(parts[0])]={'ppid':int(parts[1]),'command':parts[2]}
    return result

def receiver_processes(table):
    paths=[str(ROOT/'package/scripts/card_callback_service.py')]
    seeds={pid for pid,p in table.items() if any(path in p['command'] for path in paths) and pid!=os.getpid()}
    while True:
        added={pid for pid,p in table.items() if p['ppid'] in seeds}-seeds
        if not added:return {pid:table[pid] for pid in seeds}
        seeds.update(added)

def terminate_owned(owned):
    for pid,before in owned.items():
        now=process_table().get(pid)
        if not now or now['command']!=before['command']:continue
        if os.name=='nt':subprocess.run(['taskkill','/PID',str(pid),'/T','/F'],capture_output=True,check=False)
        else:
            try:os.kill(pid,signal.SIGTERM)
            except ProcessLookupError:pass
    for _ in range(20):
        current=process_table()
        alive=[pid for pid,p in owned.items() if pid in current and current[pid]['command']==p['command']]
        if not alive:return
        time.sleep(0.1)
    raise RuntimeError('接收进程尚未完全停止，请检查本机进程权限。')

def unload(state):
    label,task=identifiers(state)
    owned=receiver_processes(process_table())
    if sys.platform=='darwin':
        subprocess.run(['launchctl','bootout','gui/'+str(os.getuid())+'/'+label],capture_output=True,check=False)
        (pathlib.Path.home()/'Library/LaunchAgents'/(label+'.plist')).unlink(missing_ok=True)
    elif os.name=='nt':
        subprocess.run(['schtasks','/End','/TN',task],capture_output=True,check=False)
        subprocess.run(['schtasks','/Delete','/TN',task,'/F'],capture_output=True,check=False)
    terminate_owned(owned)
    if receiver_processes(process_table()):raise RuntimeError('接收进程仍在运行。')

def stop(state):
    set_enabled(False)
    unload(state)
    (ROOT/'card-service-status.json').write_text(json.dumps({'ready':False,'stopped_by_user':True}))
    return {'receiver_stopped':True,'data_preserved':True}

def resume(state):
    if not state.get('recipient_open_id') or not state.get('application_id'):
        raise ValueError('请先完成本人的飞书授权与待办助手初始化。')
    before=status()
    if before['enabled'] and before['receiver_connected'] and before['receiver_version']==CLIENT_VERSION:
        return {'already_running':True,'data_preserved':True}
    set_enabled(True)
    try:return install(state)
    except Exception:
        set_enabled(False)
        raise

def deploy():
    prepare_storage();source=pathlib.Path(__file__).resolve().parent.parent;deployed=ROOT/'package'
    if source!=deployed:
        shutil.copytree(source,deployed,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','tests'))
    return deployed

def windows_quote(value):
    if any(c in value for c in '\r\n"'):raise ValueError('Unsupported launcher path')
    return '"'+value.replace('%','%%')+'"'

def install(state):
    assert_identity(state);prepare_storage();unload(state)
    deployed=deploy();label,task=identifiers(state)
    command=[sys.executable,str(deployed/'scripts/card_callback_service.py')]
    env={'PATH':str(pathlib.Path(CLI).parent)+os.pathsep+os.environ.get('PATH',''),'LANG':'en_US.UTF-8',
         'FEISHU_TODO_HOME':str(ROOT),'FEISHU_TODO_PROFILE':PROFILE}
    if sys.platform=='darwin':
        directory=pathlib.Path.home()/'Library/LaunchAgents';directory.mkdir(parents=True,exist_ok=True)
        path=directory/(label+'.plist')
        definition={'Label':label,'ProgramArguments':command,'WorkingDirectory':str(ROOT),'RunAtLoad':True,'KeepAlive':True,
                    'ThrottleInterval':10,'StandardOutPath':str(ROOT/'receiver-output.log'),
                    'StandardErrorPath':str(ROOT/'receiver-error.log'),'EnvironmentVariables':env}
        path.write_bytes(plistlib.dumps(definition))
        subprocess.run(['launchctl','enable','gui/'+str(os.getuid())+'/'+label],check=True,capture_output=True)
        subprocess.run(['launchctl','bootstrap','gui/'+str(os.getuid()),str(path)],check=True,capture_output=True)
    elif os.name=='nt':
        launcher=ROOT/'receiver-launcher.cmd';lines=['@echo off']
        for key,value in env.items():lines.append('set '+windows_quote(key+'='+value))
        lines.append(' '.join(windows_quote(s) for s in command));launcher.write_text('\r\n'.join(lines)+'\r\n')
        subprocess.run(['schtasks','/Create','/TN',task,'/SC','ONLOGON','/TR',windows_quote(str(launcher)),'/IT','/F'],check=True,capture_output=True)
        subprocess.run(['schtasks','/Run','/TN',task],check=True,capture_output=True)
    else:
        with (ROOT/'receiver-output.log').open('a') as output,(ROOT/'receiver-error.log').open('a') as error:
            subprocess.Popen(command,cwd=ROOT,env={**ENV,**env},stdin=subprocess.DEVNULL,stdout=output,stderr=error,start_new_session=True)
    return {'receiver_started':True,'ai_schedule_created':False,'login_start':sys.platform=='darwin' or os.name=='nt'}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['status','pause','resume','install','stop']);parser.add_argument('--confirm',action='store_true');args=parser.parse_args()
    if args.action=='status':
        print(json.dumps(status(),ensure_ascii=False));return
    if not args.confirm:raise RuntimeError('仅在本人明确要求暂停或恢复后使用--confirm；询问方法不执行启停。')
    state=read(ROOT/'state.json',{})
    if args.action in ['resume','install']:result=resume(state)
    elif state:result=stop(state)
    else:
        set_enabled(False);result={'receiver_stopped':True,'data_preserved':True}
    print(json.dumps({'ok':True,**result,'status':status(),'host_schedule_changed':False},ensure_ascii=False))

if __name__=='__main__':main()
