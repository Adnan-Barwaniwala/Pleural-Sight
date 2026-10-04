import json, pathlib, sqlite3, time, uuid, csv
ROOT=pathlib.Path(__file__).parent
DATA=ROOT/'data'; DATA.mkdir(exist_ok=True)
DB=DATA/'timelens.sqlite'
CASES=[('case-01','00000001_000.png','00000001_001.png'),('case-02','00000001_001.png','00000001_002.png'),('case-03','00000011_000.png','00000011_001.png'),('case-04','00000061_002.png','00000061_003.png')]
STATES=['present','absent','uncertain','not_assessable']
def connect():
 c=sqlite3.connect(DB); c.row_factory=sqlite3.Row
 c.execute('CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY, case_id TEXT, report TEXT, scope TEXT, reading TEXT, review TEXT, created REAL)')
 c.execute('CREATE TABLE IF NOT EXISTS events(run_id TEXT, event TEXT, payload TEXT, created REAL)')
 return c
def event(c,rid,kind,payload): c.execute('INSERT INTO events VALUES(?,?,?,?)',(rid,kind,json.dumps(payload),time.time()))
def create(case_id,report,scope):
 if case_id not in [x[0] for x in CASES] or scope not in ['prior','current']: raise ValueError('Invalid case or report scope')
 rid=uuid.uuid4().hex[:12]
 with connect() as c:
  c.execute('INSERT INTO runs VALUES(?,?,?,?,?,?,?)',(rid,case_id,report,scope,None,None,time.time()))
  event(c,rid,'created',{'scope':scope,'report_is_simulated':True})
 return rid
def get(rid):
 with connect() as c: row=c.execute('SELECT * FROM runs WHERE id=?',(rid,)).fetchone()
 if not row: raise ValueError('Unknown run')
 d=dict(row)
 for k in ['reading','review']: d[k]=json.loads(d[k]) if d[k] else None
 return d
def pair(rid):
 row=get(rid); case=next(x for x in CASES if x[0]==row['case_id'])
 return {'run_id':rid,'prior':case[1],'current':case[2],'view':'PA','temporal_order':'NIH follow-up index; elapsed days unavailable'}
def submit(rid,reading):
 for k in ['prior','current']:
  if reading.get(k) not in STATES: raise ValueError('Invalid '+k+' state')
 if not isinstance(reading.get('evidence'),str) or len(reading['evidence'])<20: raise ValueError('Image-specific evidence required')
 with connect() as c:
  changed=c.execute('UPDATE runs SET reading=? WHERE id=? AND reading IS NULL',(json.dumps(reading),rid)).rowcount
  if not changed: raise ValueError('Reading already frozen or unknown run')
  event(c,rid,'blind_reading_frozen',reading)
 return {'accepted':True,'immutable':True,'comparison':transition(reading)}
def transition(r):
 a,b=r['prior'],r['current']
 if a not in ['present','absent'] or b not in ['present','absent']: return 'indeterminate'
 return {('absent','absent'):'absent_both',('absent','present'):'new',('present','absent'):'resolved',('present','present'):'present_both'}[(a,b)]
def report_state(text):
 # Controlled demonstration templates only: never claim general clinical NLP.
 return {'No pleural effusion.':'absent','Pleural effusion is present.':'present','Cannot exclude a small pleural effusion.':'uncertain'}.get(text,'not_stated')
def packet(rid):
 r=get(rid)
 if not r['reading']: raise ValueError('Blind reading must be frozen first')
 stated=report_state(r['report']); visual=r['reading'][r['scope']]
 verdict='unresolved' if stated not in ['present','absent'] or visual not in ['present','absent'] else ('concordant' if stated==visual else 'discrepancy')
 return {'run_id':rid,'blind_reading':r['reading'],'transition':transition(r['reading']),'simulated_report':r['report'],'report_scope':r['scope'],'parsed_report_state':stated,'deterministic_verdict':verdict,'clinical_status':'needs clinician review','confidence':'not calibrated; no probability reported'}
def review(rid,explanation):
 p=packet(rid)
 if not isinstance(explanation,str) or len(explanation)<30: raise ValueError('Substantive review required')
 result={**p,'investigator_explanation':explanation}
 with connect() as c:
  if not c.execute('UPDATE runs SET review=? WHERE id=? AND review IS NULL',(json.dumps(result),rid)).rowcount: raise ValueError('Review already frozen')
  event(c,rid,'investigator_review_frozen',result)
 return result
def all_runs():
 with connect() as c: ids=[r[0] for r in c.execute('SELECT id FROM runs ORDER BY created DESC')]
 return [get(rid) for rid in ids]
