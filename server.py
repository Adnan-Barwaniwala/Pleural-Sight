"""Local intake/viewer with required two-agent OpenSwarm orchestration."""
import hashlib
import asyncio
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from inputs import validate_image, extract_report, validate_text, MAX_IMAGE, MAX_REPORT
from openswarm_workflow import execute as execute_workflow, OpenSwarmError
from gemini_direct import ModelError, api_key
from swarm_api import call as swarm_call

ROOT = Path(__file__).parent
RUNTIME = ROOT/'runtime'
RUNTIME.mkdir(mode=0o700, exist_ok=True)
DB = RUNTIME/'intake.sqlite'
PAIRS = [('00000001_000.png','00000001_001.png'),('00000001_001.png','00000001_002.png'),('00000011_000.png','00000011_001.png'),('00000061_002.png','00000061_003.png')]
BLOCKER = 'TimeLens requires both GEMINI_API_KEY and the local OpenSwarm app before analysis can run.'
RUN_TASKS = {}

@asynccontextmanager
async def lifespan(_app):
    recover_interrupted_runs()
    yield

app = FastAPI(title='TimeLens', docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['127.0.0.1','localhost','testserver'])
app.mount('/static', StaticFiles(directory=ROOT/'static'), name='static')

def connect():
    c = sqlite3.connect(DB)
    c.execute('CREATE TABLE IF NOT EXISTS cases (id TEXT PRIMARY KEY, payload TEXT NOT NULL, created REAL NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, case_id TEXT NOT NULL, status TEXT NOT NULL, stage TEXT, result TEXT, trace TEXT, error TEXT, created REAL NOT NULL, updated REAL NOT NULL)')
    columns = {row[1] for row in c.execute('PRAGMA table_info(runs)')}
    if 'stage' not in columns:
        c.execute('ALTER TABLE runs ADD COLUMN stage TEXT')
    if 'trace' not in columns:
        c.execute('ALTER TABLE runs ADD COLUMN trace TEXT')
    return c

def openswarm_ready():
    try:
        swarm_call('/api/agents/activity', timeout=2)
        return True
    except Exception:
        return False

def configured():
    return bool(api_key()) and openswarm_ready()

def demos():
    return [dict(id=f'demo-{i+1}', name=f'Demonstration {i+1:02}', source='NIH ChestX-ray14', prior=a, current=b, reports=[], assertions='Paired by supplied follow-up index; not independently clinically verified.', status='ready', result=None) for i,(a,b) in enumerate(PAIRS)]

def cases():
    with connect() as c:
        uploaded = [json.loads(row[0]) for row in c.execute('SELECT payload FROM cases ORDER BY created DESC')]
        rows = c.execute('SELECT id,case_id,status,stage,result,trace,error,created,updated FROM runs ORDER BY updated DESC').fetchall()
    latest = {}
    for row in rows:
        if row[1] not in latest:
            latest[row[1]] = {'id':row[0],'case_id':row[1],'status':row[2],'stage':row[3],
                'result':json.loads(row[4]) if row[4] else None,
                'trace':json.loads(row[5]) if row[5] else [],'error':row[6],
                'created':row[7],'updated':row[8]}
    result = demos() + uploaded
    for item in result:
        item['last_run'] = latest.get(item['id'])
    return result

def case(case_id):
    value = next((c for c in cases() if c['id'] == case_id), None)
    if value is None:
        raise HTTPException(404,'Case not found')
    return value

def run_record(run_id):
    with connect() as c:
        row = c.execute('SELECT id,case_id,status,stage,result,trace,error,created,updated FROM runs WHERE id=?',(run_id,)).fetchone()
    if row is None:
        raise HTTPException(404,'Run not found')
    progress = {'assess_images':'waiting','read_reports':'waiting'}
    stage_db = RUNTIME/'runs'/run_id/'stages.sqlite'
    if stage_db.exists():
        try:
            with sqlite3.connect(stage_db, timeout=1) as stages:
                for name, status in stages.execute('SELECT name,status FROM stages'):
                    if name in progress and status in {'running','complete','failed'}:
                        progress[name] = status
        except sqlite3.Error:
            pass
    return {'id':row[0],'case_id':row[1],'status':row[2],'stage':row[3],
            'result':json.loads(row[4]) if row[4] else None,
            'trace':json.loads(row[5]) if row[5] else [],'error':row[6],
            'created':row[7],'updated':row[8],'progress':progress}

def update_run(run_id, **changes):
    allowed = {'status','stage','result','trace','error'}
    values = {key:value for key,value in changes.items() if key in allowed}
    if 'result' in values and values['result'] is not None:
        values['result'] = json.dumps(values['result'])
    if 'trace' in values and values['trace'] is not None:
        values['trace'] = json.dumps(values['trace'])
    values['updated'] = time.time()
    assignments = ','.join(key+'=?' for key in values)
    with connect() as c:
        c.execute(f'UPDATE runs SET {assignments} WHERE id=?', (*values.values(),run_id))

async def process_run(run_id, manifest_path):
    update_run(run_id,status='running',stage='launching_agents',error=None)
    try:
        result = await execute_workflow(manifest_path, progress=lambda stage:update_run(run_id,stage=stage))
    except (OpenSwarmError,ModelError,asyncio.TimeoutError) as exc:
        message = str(exc) if not isinstance(exc,asyncio.TimeoutError) else 'OpenSwarm agent timed out.'
        update_run(run_id,status='failed',stage='failed',error=message)
        return
    except Exception:
        update_run(run_id,status='failed',stage='failed',error='OpenSwarm orchestration failed locally.')
        return
    update_run(run_id,status='complete',stage='human_review',result=result,trace=result.get('agents',[]),error=None)

def retain_task(run_id, task):
    RUN_TASKS[run_id] = task
    task.add_done_callback(lambda _: RUN_TASKS.pop(run_id,None))

def recover_interrupted_runs():
    with connect() as c:
        c.execute("UPDATE runs SET status='interrupted',stage='interrupted',error='Server restarted before the run completed.',updated=? WHERE status IN ('queued','running')",(time.time(),))

@app.middleware('http')
async def local_only(request, next_handler):
    if request.method not in ['GET','HEAD']:
        origin = request.headers.get('origin')
        if origin and origin not in ['http://127.0.0.1:8765','http://localhost:8765']:
            return JSONResponse({'detail':'Cross-origin requests are not permitted.'},status_code=403)
        if request.headers.get('x-timelens-request') != 'local-ui':
            return JSONResponse({'detail':'Missing local request header.'},status_code=403)
    try:
        size = int(request.headers.get('content-length','0'))
    except ValueError:
        return JSONResponse({'detail':'Invalid request length.'},status_code=400)
    if size > 30 * 1024 * 1024:
        return JSONResponse({'detail':'Request too large.'},status_code=413)
    response = await next_handler(request)
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' blob:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'"
    return response

@app.get('/')
def index():
    return FileResponse(ROOT/'static/index.html')

@app.get('/api/state')
def state():
    key_ready, swarm_ready = bool(api_key()), openswarm_ready()
    ready = key_ready and swarm_ready
    if ready:
        message = 'Ready: OpenSwarm will launch independent Image Analyst and Report Reader agents.'
    elif not key_ready:
        message = 'Gemini API key is missing. Add it to the local .env file.'
    else:
        message = 'OpenSwarm is not reachable. Start the local OpenSwarm app.'
    return {'cases':cases(), 'integration':{'ready':ready,'message':message}, 'provenance':json.loads((ROOT/'data/provenance.json').read_text())}

@app.get('/api/cases/{case_id}/images/{scope}')
def image(case_id: str, scope: str):
    if scope not in ['prior','current']:
        raise HTTPException(404)
    selected = case(case_id)
    folder = ROOT/'data/images' if case_id.startswith('demo-') else RUNTIME/'uploads'/case_id
    return FileResponse(folder/selected[scope], media_type='image/png' if selected[scope].endswith('.png') else 'image/jpeg')

@app.post('/api/cases')
async def upload(request: Request):
    try:
        async with request.form(max_files=6, max_fields=12, max_part_size=MAX_REPORT) as form:
            if form.get('same_patient') != 'true' or form.get('chronological') != 'true':
                raise ValueError('Confirm that both images belong to the same patient and are in chronological order.')
            blobs, metadata = {}, {}
            for scope in ['prior','current']:
                file = form.get(scope)
                if not hasattr(file,'read'):
                    raise ValueError('Provide both the prior and current images.')
                blobs[scope] = await file.read(MAX_IMAGE+1)
                metadata[scope] = validate_image(blobs[scope])
            reports = []
            for scope in ['prior','current']:
                text = form.get(scope+'_report','')
                if not isinstance(text,str):
                    raise ValueError('Report text must be text.')
                if text.strip():
                    reports.append({'scope':scope,'text':validate_text(text),'source':'pasted text'})
                for file in form.getlist(scope+'_report_file'):
                    if getattr(file,'filename',''):
                        reports.append({'scope':scope,'text':extract_report(await file.read(MAX_REPORT+1),file.filename),'source':'uploaded report'})
            if len(reports)>4:
                raise ValueError('Use at most four reports per case.')
            cid = uuid.uuid4().hex
            folder = RUNTIME/'uploads'/cid
            folder.mkdir(parents=True, mode=0o700)
            record = dict(id=cid,name='Uploaded comparison',source='User upload',reports=reports,metadata=metadata,assertions='Same patient and chronology confirmed by uploader; not independently verified.',status='ready',result=None)
            for scope,data in blobs.items():
                filename = scope+('.png' if metadata[scope]['format']=='PNG' else '.jpg')
                (folder/filename).write_bytes(data)
                record[scope] = filename
                metadata[scope]['sha256'] = hashlib.sha256(data).hexdigest()
            with connect() as c:
                c.execute('INSERT INTO cases VALUES (?,?,?)',(cid,json.dumps(record),time.time()))
            return record
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc

@app.post('/api/runs',status_code=202)
async def run(request: Request):
    if not configured():
        raise HTTPException(503,BLOCKER)
    body = await request.json()
    selected = case(str(body.get('case_id','')))
    rid = uuid.uuid4().hex
    folder = RUNTIME/'runs'/rid
    folder.mkdir(parents=True, mode=0o700)
    source = ROOT/'data/images' if selected['id'].startswith('demo-') else RUNTIME/'uploads'/selected['id']
    manifest = {'run_id':rid,'prior':str((source/selected['prior']).resolve()),
                'current':str((source/selected['current']).resolve()),'reports':selected['reports']}
    manifest_path = folder/'manifest.json'
    manifest_path.write_text(json.dumps(manifest))
    now = time.time()
    with connect() as c:
        c.execute('INSERT INTO runs (id,case_id,status,stage,result,trace,error,created,updated) VALUES (?,?,?,?,?,?,?,?,?)',
                  (rid,selected['id'],'queued','queued',None,'[]',None,now,now))
    retain_task(rid,asyncio.create_task(process_run(rid,manifest_path)))
    return run_record(rid)

@app.get('/api/runs/{run_id}')
def get_run(run_id: str):
    return run_record(run_id)

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8765,access_log=False)
