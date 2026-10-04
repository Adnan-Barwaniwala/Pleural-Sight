"""Minimal stdio MCP, role-specific capability surface; no file/shell tools."""
import base64,json,sys,urllib.request
ROLE=sys.argv[1]
def schema(name,description,props,required): return {'name':name,'description':description,'inputSchema':{'type':'object','properties':props,'required':required,'additionalProperties':False}}
S={'type':'string'}
TOOLS=[schema('get_image_pair','Get prior and current PA radiographs, in that order. No reports or reference labels.',{'run_id':S},['run_id']),schema('submit_blind_reading','Freeze independent effusion assessment. No confidence percentages.',{'run_id':S,'prior':{'type':'string','enum':['present','absent','uncertain','not_assessable']},'current':{'type':'string','enum':['present','absent','uncertain','not_assessable']},'evidence':S,'limitations':S},['run_id','prior','current','evidence','limitations'])] if ROLE=='blind' else [schema('get_review_packet','Get frozen independent assessment and simulated report with exact temporal scope.',{'run_id':S},['run_id']),schema('submit_review','Record explanation of deterministic verdict and limitations; cannot override frozen findings or approve clinical use.',{'run_id':S,'explanation':S},['run_id','explanation'])]
def invoke(name,args):
 if name not in [x['name'] for x in TOOLS]: raise ValueError('Tool forbidden for this role')
 req=urllib.request.Request('http://127.0.0.1:8765/internal/'+ROLE,data=json.dumps({'name':name,'arguments':args}).encode(),headers={'Content-Type':'application/json','X-TimeLens-Capability':__import__('os').environ['TIMELENS_CAPABILITY']})
 with urllib.request.urlopen(req,timeout=30) as r: return json.load(r)
for line in sys.stdin:
 try:
  msg=json.loads(line); method=msg.get('method'); result={}
  if 'id' not in msg: continue
  if method=='initialize': result={'protocolVersion':'2024-11-05','capabilities':{'tools':{}},'serverInfo':{'name':'timelens-'+ROLE,'version':'0.1.0'}}
  elif method=='tools/list': result={'tools':TOOLS}
  elif method=='tools/call':
   try: result=invoke(msg['params']['name'],msg['params'].get('arguments',{}))
   except Exception as e: result={'isError':True,'content':[{'type':'text','text':str(e)}]}
  elif method!='ping': raise ValueError('Unsupported method')
  print(json.dumps({'jsonrpc':'2.0','id':msg['id'],'result':result}),flush=True)
 except Exception as e:
  print(json.dumps({'jsonrpc':'2.0','id':msg.get('id'),'error':{'code':-32603,'message':str(e)}}),flush=True)
