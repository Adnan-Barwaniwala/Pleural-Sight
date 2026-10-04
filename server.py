"""Local TimeLens worklist and review API with OpenSwarm-orchestrated investigations."""
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
import cases as catalog
import openswarm_workflow
import direct_workflow
from openswarm_workflow import OpenSwarmError
from gemini_direct import ModelError, api_key
from swarm_api import call as swarm_call
import verdict
import ui_adapter

ROOT = Path(__file__).parent
RUNTIME = ROOT/'runtime'
RUNTIME.mkdir(mode=0o700, exist_ok=True)
DB = RUNTIME/'intake.sqlite'
REPLAY = ROOT/'data'/'replay'
EVALUATION = ROOT/'data'/'eval'/'results.json'
RUN_TASKS = {}
PORT = int(os.environ.get('TIMELENS_PORT', '8765'))
ORIGINS = [f'http://127.0.0.1:{PORT}', f'http://localhost:{PORT}']
ENGINES = {'openswarm': openswarm_workflow.execute, 'headless': direct_workflow.execute}
execute_workflow = None  # test hook: overrides both engines when set
SIGNOFF_ACTIONS = {'approve', 'override', 'escalate'}
_gate_cache = {}

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
    c.execute('CREATE TABLE IF NOT EXISTS signoffs (id TEXT PRIMARY KEY, case_id TEXT NOT NULL, run_id TEXT, source TEXT NOT NULL, action TEXT NOT NULL, reason TEXT, status TEXT, created REAL NOT NULL)')
    columns = {row[1] for row in c.execute('PRAGMA table_info(runs)')}
    for column in ('stage','trace','engine'):
        if column not in columns:
            c.execute(f'ALTER TABLE runs ADD COLUMN {column} TEXT')
    return c

def openswarm_ready():
    try:
        swarm_call('/api/agents/activity', timeout=2)
        return True
    except Exception:
        return False

RUN_COLUMNS = 'id,case_id,status,stage,result,trace,error,created,updated,engine'

def row_to_run(row):
    return {'id':row[0],'case_id':row[1],'status':row[2],'stage':row[3],
            'result':json.loads(row[4]) if row[4] else None,
            'trace':json.loads(row[5]) if row[5] else [],'error':row[6],
            'created':row[7],'updated':row[8],'engine':row[9] or 'openswarm','replay':False}

def image_folder(case_id):
    upload = RUNTIME/'uploads'/case_id
    return upload if case_id.startswith('upload-') or upload.is_dir() else catalog.IMAGES

def normalize_case(item):
    """Read cases saved by the original prototype without rewriting its database."""
    for scope in ('prior', 'current'):
        if isinstance(item.get(scope), str):
            metadata = (item.get('metadata') or {}).get(scope, {})
            item[scope] = {'image': item[scope], **metadata}
    return item

def image_path(item, scope):
    return image_folder(item['id'])/item[scope]['image']

def case_gate(item):
    key = (item['id'], item['prior']['image'], item['current']['image'])
    if key not in _gate_cache:
        _gate_cache[key] = catalog.gate(image_path(item,'prior'), image_path(item,'current'),
                                        item['prior'].get('view'), item['current'].get('view'))
    return _gate_cache[key]

def replay_record(case_id):
    path = REPLAY/f'{case_id}.json'
    if not path.is_file():
        return None
    return {**json.loads(path.read_text()), 'replay': True}

def cases():
    with connect() as c:
        uploaded = [normalize_case(json.loads(row[0])) for row in c.execute('SELECT payload FROM cases ORDER BY created DESC')]
        rows = c.execute(f'SELECT {RUN_COLUMNS} FROM runs ORDER BY updated DESC').fetchall()
        signoffs = c.execute('SELECT id,case_id,run_id,source,action,reason,status,created FROM signoffs ORDER BY created DESC').fetchall()
    latest, latest_signoff = {}, {}
    for row in rows:
        latest.setdefault(row[1], row_to_run(row))
    for row in signoffs:
        latest_signoff.setdefault(row[1], {'id':row[0],'run_id':row[2],'source':row[3],'action':row[4],'reason':row[5],'status':row[6],'created':row[7]})
    result = [catalog.public(item) for item in catalog.catalog()] + uploaded
    for item in result:
        item['gate'] = case_gate(item)
        item['last_run'] = latest.get(item['id'])
        item['replay'] = replay_record(item['id'])
        item['signoff'] = latest_signoff.get(item['id'])
        shown = item['last_run'] if item['last_run'] and item['last_run']['status']=='complete' else item['replay']
        stored_result = shown.get('result') if shown else None
        item['status'] = stored_result['verdict']['status'] if stored_result and stored_result.get('verdict') else None
    return result

def case(case_id):
    value = next((c for c in cases() if c['id'] == case_id), None)
    if value is None:
        raise HTTPException(404,'Case not found')
    return value

def run_record(run_id):
    with connect() as c:
        row = c.execute(f'SELECT {RUN_COLUMNS} FROM runs WHERE id=?',(run_id,)).fetchone()
    if row is None:
        raise HTTPException(404,'Run not found')
    # Per-tool progress read from the run's MCP stage table (persisted state, never simulated).
    progress = {'read_pair':'waiting','read_reports':'waiting','reassess':'waiting'}
    stage_db = RUNTIME/'runs'/run_id/'stages.sqlite'
    if stage_db.exists():
        try:
            with sqlite3.connect(stage_db, timeout=1) as stages:
                for name, status in stages.execute('SELECT name,status FROM stages'):
                    if name in progress and status in {'running','complete','failed'}:
                        progress[name] = status
        except sqlite3.Error:
            pass
    return {**row_to_run(row),'progress':progress}

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

async def process_run(run_id, manifest_path, engine):
    update_run(run_id,status='running',stage='launching_agents',error=None)
    runner = execute_workflow or ENGINES[engine]
    try:
        result = await runner(manifest_path, progress=lambda stage:update_run(run_id,stage=stage))
    except (OpenSwarmError,ModelError,asyncio.TimeoutError) as exc:
        message = str(exc) if not isinstance(exc,asyncio.TimeoutError) else 'OpenSwarm agent timed out.'
        update_run(run_id,status='failed',stage='failed',error=message)
        return
    except Exception:
        update_run(run_id,status='failed',stage='failed',error='TimeLens orchestration failed locally.')
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
        if origin and origin not in ORIGINS:
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
    response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' blob: data:; style-src 'self'; script-src 'self'; frame-ancestors 'none'; base-uri 'none'"
    return response

@app.get('/')
def index():
    return FileResponse(ROOT/'static/intro.html')

@app.get('/workspace')
def workspace_page():
    return FileResponse(ROOT/'static/index.html')

@app.get('/api/state')
def state():
    key_ready, swarm_ready = bool(api_key()), openswarm_ready()
    if key_ready and swarm_ready:
        message = 'Live: OpenSwarm launches a Blind Reader, a Report Reader and, if disputed, an Investigator.'
    elif key_ready:
        message = 'OpenSwarm is not reachable. Start the OpenSwarm app, or run cases with the headless runner.'
    else:
        message = 'Gemini API key is missing. Add GEMINI_API_KEY to the local .env file. Cached replays remain available.'
    return {'cases':[ui_adapter.case(item) for item in cases()], 'integration':{'ready':key_ready and swarm_ready,'openswarm':swarm_ready,
            'gemini':key_ready,'message':message},
            'status_order':verdict.STATUS_ORDER, 'status_text':verdict.STATUS_TEXT,
            'provenance':json.loads((ROOT/'data/provenance.json').read_text())}

@app.get('/api/cases/{case_id}/images/{scope}')
def image(case_id: str, scope: str):
    if scope not in ['prior','current']:
        raise HTTPException(404)
    selected = case(case_id)
    path = image_path(selected, scope)
    return FileResponse(path, media_type='image/png' if path.suffix=='.png' else 'image/jpeg')

@app.post('/api/cases')
async def upload(request: Request):
    try:
        async with request.form(max_files=6, max_fields=14, max_part_size=MAX_REPORT) as form:
            if form.get('same_patient') != 'true' or form.get('chronological') != 'true':
                raise ValueError('Confirm that both images belong to the same patient and are in chronological order.')
            blobs, metadata, views = {}, {}, {}
            for scope in ['prior','current']:
                file = form.get(scope)
                if not hasattr(file,'read'):
                    raise ValueError('Provide both the prior and current images.')
                blobs[scope] = await file.read(MAX_IMAGE+1)
                metadata[scope] = validate_image(blobs[scope])
                view = form.get(scope+'_view','unknown')
                views[scope] = view if view in ('PA','AP') else 'unknown'
            reports = []
            for scope in ['prior','current']:
                text = form.get(scope+'_report','')
                if not isinstance(text,str):
                    raise ValueError('Report text must be text.')
                if text.strip():
                    reports.append({'scope':scope,'text':validate_text(text),'source':'pasted text','synthetic':False})
                for file in form.getlist(scope+'_report_file'):
                    if getattr(file,'filename',''):
                        reports.append({'scope':scope,'text':extract_report(await file.read(MAX_REPORT+1),file.filename),'source':'uploaded report','synthetic':False})
            if len(reports)>4:
                raise ValueError('Use at most four reports per case.')
            cid = 'upload-'+uuid.uuid4().hex[:12]
            folder = RUNTIME/'uploads'/cid
            folder.mkdir(parents=True, mode=0o700)
            record = dict(id=cid,set='upload',slot=None,name='Uploaded comparison',source='User upload',
                          purpose='Same patient and chronology confirmed by uploader; not independently verified.',
                          reports=reports)
            for scope,data in blobs.items():
                filename = scope+('.png' if metadata[scope]['format']=='PNG' else '.jpg')
                (folder/filename).write_bytes(data)
                record[scope] = {'image':filename,'view':views[scope],'order':None,
                                 'width':metadata[scope]['width'],'height':metadata[scope]['height'],
                                 'sha256':hashlib.sha256(data).hexdigest()}
            with connect() as c:
                c.execute('INSERT INTO cases VALUES (?,?,?)',(cid,json.dumps(record),time.time()))
            return record
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc

@app.post('/api/runs',status_code=202)
async def run(request: Request):
    try:
        body = await request.json()
    except ValueError:
        body = {}
    engine = body.get('engine','openswarm') if isinstance(body,dict) else 'openswarm'
    if engine not in ENGINES:
        raise HTTPException(422,'Unknown engine.')
    if not api_key():
        raise HTTPException(503,'TimeLens needs GEMINI_API_KEY in the local .env file before a live run.')
    if engine == 'openswarm' and not openswarm_ready():
        raise HTTPException(503,'OpenSwarm is not reachable. Start the OpenSwarm app or use the headless runner.')
    selected = case(str(body.get('case_id','')))
    rid = uuid.uuid4().hex
    folder = (RUNTIME/'runs'/rid).resolve()
    folder.mkdir(parents=True, mode=0o700)
    manifest = {'run_id':rid,'case_id':selected['id'],'case_name':selected['name'],
                'prior':str(image_path(selected,'prior').resolve()),
                'current':str(image_path(selected,'current').resolve()),
                'reports':selected['reports'],'gate':selected['gate']}
    manifest_path = folder/'manifest.json'
    manifest_path.write_text(json.dumps(manifest))
    now = time.time()
    with connect() as c:
        c.execute('INSERT INTO runs (id,case_id,status,stage,result,trace,error,created,updated,engine) VALUES (?,?,?,?,?,?,?,?,?,?)',
                  (rid,selected['id'],'queued','queued',None,'[]',None,now,now,engine))
    retain_task(rid,asyncio.create_task(process_run(rid,manifest_path,engine)))
    return ui_adapter.run(run_record(rid),selected)

@app.get('/api/runs/{run_id}')
def get_run(run_id: str):
    record = run_record(run_id)
    return ui_adapter.run(record,case(record['case_id']))

@app.post('/api/signoffs')
async def signoff(request: Request):
    body = await request.json()
    selected = case(str(body.get('case_id','')))
    action = body.get('action')
    reason = (body.get('reason') or '').strip()
    if action not in SIGNOFF_ACTIONS:
        raise HTTPException(422,'Choose approve, override or escalate.')
    if action == 'override' and len(reason) < 5:
        raise HTTPException(422,'An override needs a reason of at least five characters.')
    if len(reason) > 2000:
        raise HTTPException(422,'Keep the reason under 2,000 characters.')
    if not selected['status']:
        raise HTTPException(409,'There is no completed result to sign off.')
    live = selected['last_run'] if selected['last_run'] and selected['last_run']['status']=='complete' else None
    record = {'id':uuid.uuid4().hex,'case_id':selected['id'],'run_id':live['id'] if live else None,
              'source':'live' if live else 'replay','action':action,'reason':reason or None,
              'status':selected['status'],'created':time.time()}
    with connect() as c:
        c.execute('INSERT INTO signoffs VALUES (?,?,?,?,?,?,?,?)',tuple(record.values()))
    return record

@app.get('/api/signoffs')
def signoff_log():
    with connect() as c:
        rows = c.execute('SELECT id,case_id,run_id,source,action,reason,status,created FROM signoffs ORDER BY created DESC LIMIT 200').fetchall()
    return [dict(zip(['id','case_id','run_id','source','action','reason','status','created'],row)) for row in rows]

@app.get('/api/evaluation')
def evaluation():
    if not EVALUATION.is_file():
        return {'available':False}
    return {'available':True,**json.loads(EVALUATION.read_text())}

if __name__ == '__main__':
    import uvicorn
    print(f'TimeLens running at http://127.0.0.1:{PORT}', flush=True)
    uvicorn.run(app,host='127.0.0.1',port=PORT,access_log=False)
