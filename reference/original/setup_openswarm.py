import json,sys,pathlib
import core
from swarm_api import call
caps=json.loads((core.DATA/'capabilities.json').read_text())
cfg={}
cfg['dashboard_id']=call('/api/dashboards/create',{'name':'TimeLens · Verified X-ray Review'})['id']
for role in ['blind','review']:
 name='timelens-'+role
 instructions=('You are TimeLens Blind Image Analyst. Independently inspect the two actual radiographs using only the TimeLens blind tools. You must not obtain the report, reference labels, other agent work, filesystem or shell. Preserve chronological roles. Assess only pleural effusion presence, absence, uncertainty or not_assessable. Describe observable evidence and limitations. Submit exactly once. Never claim calibrated confidence or clinical approval.' if role=='blind' else 'You are TimeLens Discrepancy Investigator. Use only TimeLens review tools. Explain the frozen image assessment against the simulated report at its exact time point. Do not override immutable findings or deterministic comparison. Explain uncertainty and competing explanations. No clinical signoff and no invented confidence percentages. Submit exactly once.')
 tool=call('/api/tools/create',{'name':name,'description':'TimeLens scoped '+role+' research demo tools','mcp_config':{'type':'stdio','command':sys.executable,'args':[str(core.ROOT/'mcp_server.py'),role],'env':{'TIMELENS_CAPABILITY':caps[role]}}})
 discovered=call('/api/tools/'+tool['id']+'/discover',{})['tool']
 permissions=discovered['tool_permissions']
 names=[x for x in permissions if not x.startswith('_')]
 for n in names: permissions[n]='always_allow'
 call('/api/tools/'+tool['id'],{'tool_permissions':permissions},'PUT')
 allowed=['mcp__'+name+'__'+n for n in names]
 mode=call('/api/modes/create',{'name':'TimeLens '+role,'instructions':instructions,'system_prompt':instructions,'memory_scope':'own','tools':allowed,'model':'ag/gemini-3.8-flash'})
 cfg[role]={'tool_id':tool['id'],'mode_id':mode['id'],'allowed_tools':allowed,'instructions':instructions}
 print(role,tool['id'],mode['id'],names,flush=True)
(core.DATA/'integration.json').write_text(json.dumps(cfg,indent=2))
print('dashboard',cfg['dashboard_id'])
