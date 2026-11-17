"""Opt-in login startup for this installation's card receiver; never schedules the AI host."""
import argparse
import hashlib
import json
import os
import pathlib
import plistlib
import shutil
import subprocess
import sys
from runtime_paths import ROOT,PROFILE,CLI,prepare_storage,assert_identity

def main():
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['install','stop'])
    parser.add_argument('--confirm',action='store_true');args=parser.parse_args()
    if not args.confirm:raise RuntimeError('Review the login-start receiver and rerun with --confirm to authorize this persistent process')
    state=json.loads((ROOT/'state.json').read_text());assert_identity(state)
    suffix=hashlib.sha256((state['application_id']+state['recipient_open_id']).encode()).hexdigest()[:10]
    label='com.feishu.work-todo.'+suffix
    if args.action=='stop':
        if sys.platform=='darwin':
            subprocess.run(['launchctl','bootout','gui/'+str(os.getuid())+'/'+label],check=False,capture_output=True)
            (pathlib.Path.home()/'Library/LaunchAgents'/(label+'.plist')).unlink(missing_ok=True)
        elif os.name=='nt':
            subprocess.run(['schtasks','/End','/TN','FeishuWorkTodo-'+suffix],check=False,capture_output=True)
            subprocess.run(['schtasks','/Delete','/TN','FeishuWorkTodo-'+suffix,'/F'],check=True,capture_output=True)
        else:raise RuntimeError('Stop the foreground receiver in its terminal')
        print(json.dumps({'stopped':label}));return
    prepare_storage()
    source=pathlib.Path(__file__).resolve().parent.parent
    deployed=ROOT/'package'
    if source!=deployed:
        shutil.copytree(source,deployed,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','tests'))
    script=deployed/'scripts/card_callback_service.py'
    command=[sys.executable,str(script)]
    if sys.platform=='darwin':
        directory=pathlib.Path.home()/'Library/LaunchAgents';directory.mkdir(parents=True,exist_ok=True)
        path=directory/(label+'.plist')
        env={'PATH':str(pathlib.Path(CLI).parent)+os.pathsep+os.environ.get('PATH',''),'LANG':'en_US.UTF-8',
             'FEISHU_TODO_HOME':str(ROOT),'FEISHU_TODO_PROFILE':PROFILE}
        definition={'Label':label,'ProgramArguments':command,'WorkingDirectory':str(ROOT),'RunAtLoad':True,'KeepAlive':True,
                    'ThrottleInterval':10,'StandardOutPath':str(ROOT/'receiver-output.log'),
                    'StandardErrorPath':str(ROOT/'receiver-error.log'),'EnvironmentVariables':env}
        subprocess.run(['launchctl','bootout','gui/'+str(os.getuid())+'/'+label],capture_output=True,check=False)
        path.write_bytes(plistlib.dumps(definition))
        subprocess.run(['launchctl','bootstrap','gui/'+str(os.getuid()),str(path)],check=True,capture_output=True)
    elif os.name=='nt':
        # Runtime home is the normal per-user default on Windows. An override requires an explicit launcher.
        if os.environ.get('FEISHU_TODO_HOME') or PROFILE!='feishu-work-todo':
            raise RuntimeError('Custom Windows home/profile: configure a user task with the explicit environment first')
        subprocess.run(['schtasks','/Create','/TN','FeishuWorkTodo-'+suffix,'/SC','ONLOGON','/TR',subprocess.list2cmdline(command),'/IT'],check=True,capture_output=True)
        subprocess.run(['schtasks','/Run','/TN','FeishuWorkTodo-'+suffix],check=True,capture_output=True)
    else:raise RuntimeError('This system needs a user service; run card_callback_service.py in the foreground and configure startup explicitly')
    print(json.dumps({'installed':label,'requires_doctor_connection_check':True,'ai_schedule_created':False},ensure_ascii=False))

if __name__=='__main__':main()
