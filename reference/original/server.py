import base64,json,pathlib,secrets,threading,urllib.parse,time
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
import core
from swarm_api import call
CONFIG=core.DATA/'integration.json'
CAPFILE=core.DATA/'capabilities.json'
if not CAPFILE.exists(): CAPFILE.write_text(json.dumps({r:secrets.token_urlsafe(32) for r in ['blind','review']}))
CAPS=json.loads(CAPFILE.read_text())
def launch_role(rid,role):
 cfg=json.loads(CONFIG.read_text()); item=cfg[role]
 directory=core.ROOT/'agent-workspaces'/role; directory.mkdir(parents=True,exist_ok=True)
 prompt=(f'Assess run {rid}. First call get_image_pair. Examine both actual images for pleural effusion; return prior/current states and image-specific evidence via submit_blind_reading. Do not infer from filenames. Do not read reports, labels, files or other agents. If images are inaccessible, mark not_assessable and explain; never fabricate.' if role=='blind' else f'Review run {rid}. Call get_review_packet, then submit_review with a concise explanation of the temporal comparison, whether the report truly conflicts at its stated time point, alternative image explanations and limitations. Respect the deterministic verdict. Simulated report; research demonstration only. Do not claim diagnosis, probabilities or clinical approval.')
 result=call('/api/agents/launch',{'name':('Blind Image Analyst' if role=='blind' else 'Discrepancy Investigator')+' · '+rid,'model':'ag/gemini-3.8-flash','provider':'ag','mode':item['mode_id'],'system_prompt':item['instructions'],'allowed_tools':item['allowed_tools'],'max_turns':8,'target_directory':str(directory),'dashboard_id':cfg['dashboard_id'],'prompt':prompt})
 with core.connect() as c: core.event(c,rid,'openswarm_session',{'role':role,'session_id':result['session_id'],'model':'ag/gemini-3.8-flash'})
 return result['session_id']
def orchestrate(rid):
 try: launch_role(rid,'blind')
 except Exception as e:
  with core.connect() as c: core.event(c,rid,'execution_error',{'error':str(e)})
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args): pass
 def send(self,obj,status=200,mime='application/json'):
  data=json.dumps(obj).encode() if mime=='application/json' else obj
  self.send_response(status); self.send_header('Content-Type',mime); self.send_header('Content-Length',str(len(data))); self.send_header('Cache-Control','no-store'); self.end_headers(); self.wfile.write(data)
 def do_GET(self):
  p=urllib.parse.urlparse(self.path).path
  try:
   if p=='/': return self.send((core.ROOT/'index.html').read_bytes(),mime='text/html; charset=utf-8')
   if p=='/api/state':
    with core.connect() as c: events=[dict(x) for x in c.execute('SELECT * FROM events ORDER BY created')]
    for e in events: e['payload']=json.loads(e['payload'])
    return self.send({'cases':[{'id':x[0],'prior':x[1],'current':x[2]} for x in core.CASES],'runs':core.all_runs(),'events':events,'provenance':json.loads((core.DATA/'provenance.json').read_text())})
   if p.startswith('/images/'):
    name=p.split('/')[-1]
    if name not in {n for x in core.CASES for n in x[1:]}: raise ValueError('Unknown image')
    return self.send((core.DATA/'images'/name).read_bytes(),mime='image/png')
   self.send({'error':'not found'},404)
  except Exception as e:self.send({'error':str(e)},400)
 def do_POST(self):
  try:
   if int(self.headers.get('Content-Length','0'))>100000: raise ValueError('Request too large')
   body=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))))
   if self.path=='/api/run':
    if self.headers.get('Origin') not in [None,'http://127.0.0.1:8765','http://localhost:8765']: return self.send({'error':'origin denied'},403)
    rid=core.create(body['case_id'],body['report'],body['scope']); threading.Thread(target=orchestrate,args=(rid,),daemon=True).start(); return self.send({'run_id':rid})
   role=self.path.removeprefix('/internal/')
   if role not in CAPS or not secrets.compare_digest(self.headers.get('X-TimeLens-Capability',''),CAPS[role]): return self.send({'error':'forbidden'},403)
   name=body['name']; a=body['arguments']; rid=a['run_id']; content=[]
   if role=='blind' and name=='get_image_pair':
    p=core.pair(rid); content=[{'type':'text','text':json.dumps(p)}]
    for key in ['prior','current']:
     content.extend([{'type':'text','text':key.upper()+' radiograph'},{'type':'image','mimeType':'image/png','data':base64.b64encode((core.DATA/'images'/p[key]).read_bytes()).decode()}])
    with core.connect() as c: core.event(c,rid,'images_delivered',{'count':2,'report_visible':False,'reference_labels_visible':False})
   elif role=='blind' and name=='submit_blind_reading':
    result=core.submit(rid,{k:a[k] for k in ['prior','current','evidence','limitations']}); content=[{'type':'text','text':json.dumps(result)}]
    threading.Thread(target=self.launch_review,args=(rid,),daemon=True).start()
   elif role=='review' and name=='get_review_packet': content=[{'type':'text','text':json.dumps(core.packet(rid))}]
   elif role=='review' and name=='submit_review': content=[{'type':'text','text':json.dumps(core.review(rid,a['explanation']))}]
   else: raise ValueError('Tool forbidden for role')
   self.send({'content':content})
  except Exception as e: self.send({'error':str(e)},400)
 def launch_review(self,rid):
  try: launch_role(rid,'review')
  except Exception as e:
   with core.connect() as c: core.event(c,rid,'execution_error',{'error':str(e)})
if __name__=='__main__':
 print('TimeLens http://127.0.0.1:8765',flush=True)
 ThreadingHTTPServer(('127.0.0.1',8765),Handler).serve_forever()
