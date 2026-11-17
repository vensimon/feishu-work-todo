"""A cancellable, installation-scoped card consumer with process-tree cleanup."""
import datetime
import json
import os
import queue
import signal
import subprocess
import threading
import time
from batch_card_runtime import ROOT,WORKSPACE,CLI_ARGS,ENV,process,save
from assistant_control import read_control,require_enabled,AssistantDisabled
from online_config import CLIENT_VERSION

STATUS=ROOT/'card-service-status.json'
def status(**extra):
    save(STATUS,{'pid':os.getpid(),'service_version':CLIENT_VERSION,
                 'updated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),**extra})

def terminate_consumer(child):
    if os.name=='nt':
        if child.poll() is not None:return
        subprocess.run(['taskkill','/PID',str(child.pid),'/T','/F'],capture_output=True,check=False)
    else:
        try:os.killpg(child.pid,signal.SIGTERM)
        except ProcessLookupError:pass
    try:child.wait(timeout=3)
    except subprocess.TimeoutExpired:
        if os.name!='nt':
            try:os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        child.wait(timeout=3)

def main():
    stopping=threading.Event()
    for sig in [signal.SIGTERM,signal.SIGINT]:signal.signal(sig,lambda *_:stopping.set())
    while not stopping.is_set() and read_control()['enabled']:
        generation=require_enabled();status(ready=False)
        child=subprocess.Popen([*CLI_ARGS,'event','consume','card.action.trigger','--as','bot','--timeout','12h'],
            cwd=WORKSPACE,env=ENV,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
            bufsize=1,start_new_session=os.name!='nt')
        events=queue.Queue()
        def watch_error():
            for line in child.stderr:
                if '[event] ready event_key=card.action.trigger' in line and not stopping.is_set() and read_control()['enabled']:
                    status(ready=True,consumer_pid=child.pid)
        def watch_output():
            for line in child.stdout:events.put(line)
        readers=[threading.Thread(target=watch_error,daemon=True),threading.Thread(target=watch_output,daemon=True)]
        for reader in readers:reader.start()
        try:
            while child.poll() is None and not stopping.is_set():
                require_enabled(generation)
                try:line=events.get(timeout=0.25)
                except queue.Empty:continue
                try:print(json.dumps(process(json.loads(line)),ensure_ascii=False),flush=True)
                except AssistantDisabled:break
                except Exception as error:print(json.dumps({'error':str(error)},ensure_ascii=False),flush=True)
        except AssistantDisabled:break
        finally:
            terminate_consumer(child)
            for reader in readers:reader.join(timeout=1)
            status(ready=False,consumer_exit_code=child.returncode)
        for _ in range(20):
            if stopping.is_set() or not read_control()['enabled']:break
            time.sleep(0.25)
    status(ready=False,assistant_enabled=read_control()['enabled'])

if __name__=='__main__':main()
