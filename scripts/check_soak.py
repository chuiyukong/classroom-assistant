"""Reproduce connection saturation and sustain 64 isolated Chromium clients."""
import asyncio,json,socket,sys,tempfile,threading,time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from classroom.web.app import create_app
from waitress import create_server
from playwright.async_api import async_playwright
from classroom.core.diagnostics import WaitressDiagnosticHandler
import logging

def close_app(app):
 app.extensions['diagnostics'].close()
 for h in list(app.logger.handlers):
  if hasattr(h,'baseFilename'):h.close();app.logger.removeHandler(h)

def reproduce():
 with tempfile.TemporaryDirectory(prefix='classroom-limit-') as folder:
  app=create_app(folder);server=create_server(app,host='127.0.0.1',port=0,threads=12,connection_limit=150,channel_timeout=30)
  threading.Thread(target=server.run,daemon=True).start();sockets=[];port=server.effective_port
  try:
   for i in range(148):
    sock=socket.create_connection(('127.0.0.1',port),timeout=1);sock.sendall(b'GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n');sock.recv(4096);sockets.append(sock)
   extra=socket.create_connection(('127.0.0.1',port),timeout=1);sockets.append(extra);extra.sendall(b'GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n')
   try:response=extra.recv(4096);blocked=not response
   except TimeoutError:blocked=True
   result={'old_limit':150,'held_connections':len(sockets),'channels':len(server._map),'new_health_blocked':blocked}
   assert blocked,result
   return result
  finally:
   for sock in sockets:sock.close()
   server.close();server.task_dispatcher.shutdown();close_app(app)

async def run(seconds):
 result={'connection_reproduction':reproduce()}
 with tempfile.TemporaryDirectory(prefix='classroom-soak-') as folder:
  app=create_app(folder,bootstrap_key='soak');real=app.wsgi_app
  def transport(env,start):
   if env.get('HTTP_X_TEST_DEVICE_IP'):env['REMOTE_ADDR']=env['HTTP_X_TEST_DEVICE_IP']
   return real(env,start)
  app.wsgi_app=transport;s=app.extensions['seating'];a=app.extensions['attendance'];cls=app.extensions['classes'].create('并发测试班');rid=s.open_round(cls['id'])['round']['id']
  server=create_server(app,host='127.0.0.1',port=0,threads=12,connection_limit=400,channel_timeout=10,cleanup_interval=5)
  thread=threading.Thread(target=server.run,name='classroom-server',daemon=True);thread.start();url='http://127.0.0.1:'+str(server.effective_port)
  diag=app.extensions['diagnostics'];monitor=threading.Thread(target=diag.monitor,args=(server,thread,server.effective_port,lambda:['127.0.0.1']),daemon=True);monitor.start()
  errors=[];durations=[];http_errors=[];peak=0
  try:
   async with async_playwright() as pw:
    browser=await pw.chromium.launch();contexts=[];pages=[]
    for i in range(64):
     ctx=await browser.new_context(extra_http_headers={'X-Test-Device-IP':'10.99.0.'+str(i+1)})
     page=await ctx.new_page();page.on('pageerror',lambda e:errors.append(type(e).__name__))
     page.on('response',lambda r:http_errors.append(r.status) if r.status>=500 else None)
     contexts.append(ctx);pages.append(page)
    gate=asyncio.Semaphore(16)
    async def register(i,page):
     async with gate:
      await page.goto(url+'/',timeout=45000)
      await page.locator('[data-seat="%d"]'%(i+1)).click(timeout=45000)
      await page.locator('#student-name').fill('测试学生%02d'%i);await page.locator('#submit-seat').click()
      await page.locator('#dialog').wait_for(state='hidden',timeout=45000)
    await asyncio.gather(*(register(i,p) for i,p in enumerate(pages)))
    assert s.get_current_arrangement()['count']==64
    s.close_round(rid);lid=a.start(rid)['lesson']['id'];a.action(lid,'open')
    async def sign(i,page):
     await page.wait_for_url(url+'/attendance',timeout=45000)
     await page.locator('[data-seat="%d"]'%(i+1)).click(timeout=45000)
     await page.locator('#checkin-name').fill('测试学生%02d'%i);await page.locator('#checkin-button').click()
     await page.locator('#checkin-dialog').wait_for(state='hidden',timeout=45000)
    await asyncio.gather(*(sign(i,p) for i,p in enumerate(pages)))
    assert a.detail(lid)['counts']['actual']==64
    teacher=await browser.new_page();await teacher.goto(url+'/teacher?key=soak')
    started=time.monotonic()
    while time.monotonic()-started<seconds:
     t=time.monotonic();await teacher.goto(url+'/teacher/attendance',timeout=15000);await teacher.locator('.seat').first.wait_for(timeout=15000);durations.append(time.monotonic()-t)
     peak=max(peak,len(server._map));await asyncio.sleep(10)
    result.update(duration_seconds=round(time.monotonic()-started),browser_contexts=64,registered=64,signed=64,peak_channels=peak,teacher_load_max_seconds=round(max(durations),3),http_5xx=len(http_errors),js_errors=errors)
    await browser.close()
   assert not errors and not http_errors,result
  finally:
   diag.stop_event.set();monitor.join(3);server.close();server.task_dispatcher.shutdown();close_app(app)
  Path('test-results/soak190.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
  print(json.dumps(result,ensure_ascii=True))
if __name__=='__main__':asyncio.run(run(int(sys.argv[1]) if len(sys.argv)>1 else 600))
