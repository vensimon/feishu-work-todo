"""Keep the existing CLI's card websocket connected; store no credentials."""
import datetime
import json
import os
import subprocess
import threading
import time
from batch_card_runtime import ROOT,WORKSPACE,CLI_ARGS,ENV,process,save

STATUS=ROOT/'card-service-status.json'
def status(**extra):
    save(STATUS,{'pid':os.getpid(),'updated_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),**extra})

def main():
    while True:
        status(ready=False)
        child=subprocess.Popen([*CLI_ARGS,'event','consume','card.action.trigger','--as','bot','--timeout','12h'],
                               cwd=WORKSPACE,env=ENV,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE,text=True,bufsize=1)
        def watch():
            with (ROOT/'card-service-connection.log').open('a') as log:
                for line in child.stderr:
                    log.write(line);log.flush()
                    if '[event] ready event_key=card.action.trigger' in line:
                        status(ready=True,consumer_pid=child.pid)
        threading.Thread(target=watch,daemon=True).start()
        for line in child.stdout:
            try:
                result=process(json.loads(line))
                # Never log the temporary callback token or full event content.
                print(json.dumps(result,ensure_ascii=False),flush=True)
            except Exception as error:
                print(json.dumps({'error':str(error)},ensure_ascii=False),flush=True)
        child.wait()
        status(ready=False,consumer_exit_code=child.returncode)
        time.sleep(5)

if __name__=='__main__':main()
