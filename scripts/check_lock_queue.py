"""Controlled external write lock; never uses classroom runtime data."""
import sys, tempfile, threading, time, urllib.request, json
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from classroom.web.app import create_app
from waitress import create_server

def run():
 with tempfile.TemporaryDirectory(prefix='classroom-lock-') as folder:
  app=create_app(folder);db=app.extensions['database'];diag=app.extensions['diagnostics']
  @app.get('/test-write')
  def write():
   with db.connect(write=True):pass
   return 'ok'
  server=create_server(app,host='127.0.0.1',port=0,threads=12,connection_limit=400)
  thread=threading.Thread(target=server.run,daemon=True);thread.start()
  url='http://127.0.0.1:'+str(server.effective_port)
  opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
  def get(path):
   with opener.open(url+path,timeout=10) as response:return response.status
  try:
   with ThreadPoolExecutor(13) as pool:
    with db.connect(write=True):
     writers=[pool.submit(get,'/test-write') for _ in range(12)]
     deadline=time.monotonic()+5
     while time.monotonic()<deadline:
      with diag.lock:active=len(diag.active)
      if active==12:break
      time.sleep(.02)
     assert active==12
     health=pool.submit(get,'/health');time.sleep(.3)
     assert not health.done()
     with server.task_dispatcher.lock:queue=len(server.task_dispatcher.queue)
    assert all(f.result()==200 for f in writers) and health.result()==200
   result=dict(waiting_writers=12,queued_health=True,queue=queue,recovered_after_lock_release=True)
   Path('test-results/lock190.json').write_text(json.dumps(result,indent=2))
   print(result)
  finally:
   server.close();server.task_dispatcher.shutdown();diag.close()
   for handler in list(app.logger.handlers):
    if hasattr(handler,'baseFilename'):handler.close();app.logger.removeHandler(handler)
if __name__=='__main__':run()
