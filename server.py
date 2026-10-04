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
    c.execute('CREATE TABLE IF NOT EXISTS case_edits (id TEXT PRIMARY KEY, payload TEXT, deleted INTEGER NOT NULL DEFAULT 0)')
    c.execute('CREATE TABLE IF NOT EXISTS run_inputs (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
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


async def report_input(form, scope):
    """Return at most one report for a study, from text or one file."""
    text = form.get(scope+'_report', '')
    if not isinstance(text, str):
        raise ValueError('Report text must be text.')
    files = [file for file in form.getlist(scope+'_report_file') if getattr(file, 'filename', '')]
    if len(files) > 1:
        raise ValueError(f'Attach only one {scope} report.')
    if text.strip() and files:
        raise ValueError(f'For the {scope} report, paste text or attach a file—not both.')
    if text.strip():
        return {'scope':scope, 'text':validate_text(text), 'source':'pasted text', 'synthetic':False}
    if files:
        file = files[0]
        return {'scope':scope, 'text':extract_report(await file.read(MAX_REPORT+1), file.filename),
                'source':'uploaded report', 'synthetic':False}
    return None

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

def cases(include_deleted=False):
    with connect() as c:
        edits = {r[0]: r[1:] for r in c.execute('SELECT id,payload,deleted FROM case_edits')}
        uploaded = [normalize_case(json.loads(row[0])) for row in c.execute('SELECT payload FROM cases ORDER BY created ASC, rowid ASC')]
        rows = c.execute(f'SELECT {RUN_COLUMNS} FROM runs ORDER BY updated DESC').fetchall()
        signoffs = c.execute('SELECT id,case_id,run_id,source,action,reason,status,created FROM signoffs ORDER BY created DESC').fetchall()
    latest, latest_signoff = {}, {}
    for row in rows:
        latest.setdefault(row[1], row_to_run(row))
    for row in signoffs:
        latest_signoff.setdefault(row[1], {'id':row[0],'run_id':row[2],'source':row[3],'action':row[4],'reason':row[5],'status':row[6],'created':row[7]})
    result = [catalog.public(item) for item in catalog.catalog()] + uploaded
    result = [json.loads(edits[item['id']][0]) if item['id'] in edits and edits[item['id']][0] else item for item in result]
    if not include_deleted:
        result = [item for item in result if not edits.get(item['id'], (None, 0))[1]]
    unnamed_upload = 0
    for item in result:
        item.setdefault('revision', 1)
        is_upload = item.get('set') == 'upload' or item.get('source') == 'User upload'
        if is_upload and (not item.get('name') or item['name'] == 'Uploaded comparison'):
            unnamed_upload += 1
            item['name'] = f'Untitled comparison {unnamed_upload:02d}'
        item['gate'] = case_gate(item)
        item['last_run'] = latest.get(item['id'])
        item['history'] = []
        for row in rows:
            if row[1] == item['id']:
                record = row_to_run(row)
                with connect() as c:
                    snapshot = c.execute('SELECT payload FROM run_inputs WHERE id=?', (record['id'],)).fetchone()
                revision = json.loads(snapshot[0]).get('revision', 1) if snapshot else 1
                item['history'].append({'id': record['id'], 'status': record['status'], 'revision': revision})
        if item['last_run'] and item['history'][0]['revision'] != item['revision']:
            item['last_run'] = None
        item['replay'] = replay_record(item['id']) if item['revision']==1 else None
        item['signoff'] = latest_signoff.get(item['id'])
        shown = item['last_run'] if item['last_run'] and item['last_run']['status']=='complete' else item['replay']
        if item['signoff']:
            signed_result_is_current = bool(
                shown and (
                    (item['signoff']['source'] == 'replay' and shown.get('replay')) or
                    item['signoff']['run_id'] == shown['id']
                )
            )
            if not signed_result_is_current:
                item['signoff'] = None
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
        c.execute(f"UPDATE runs SET {assignments} WHERE id=? AND status != 'interrupted'", (*values.values(),run_id))

async def process_run(run_id, manifest_path, engine):
    update_run(run_id,status='running',stage='launching_agents',error=None)
    runner = execute_workflow or ENGINES[engine]
    try:
        result = await runner(manifest_path, progress=lambda stage:update_run(run_id,stage=stage))
    except asyncio.CancelledError:
        update_run(run_id,status='interrupted',stage='interrupted',error='Stopped by you.')
        raise
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
        for row in c.execute("SELECT id FROM runs WHERE status IN ('queued','running')"):
            folder = RUNTIME/'runs'/row[0]
            if folder.is_dir():
                (folder/'cancelled').touch()
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
        async with request.form(max_files=6, max_fields=15, max_part_size=MAX_REPORT) as form:
            if form.get('same_patient') != 'true' or form.get('chronological') != 'true':
                raise ValueError('Confirm that both images belong to the same patient and are in chronological order.')
            raw_name = form.get('comparison_name', '')
            if not isinstance(raw_name, str):
                raise ValueError('Comparison name must be text.')
            comparison_name = ' '.join(raw_name.split())
            if len(comparison_name) > 80:
                raise ValueError('Use 80 characters or fewer for the comparison name.')
            blobs, metadata, views = {}, {}, {}
            for scope in ['prior','current']:
                file = form.get(scope)
                if not hasattr(file,'read'):
                    raise ValueError('Provide both the prior and current images.')
                blobs[scope] = await file.read(MAX_IMAGE+1)
                metadata[scope] = validate_image(blobs[scope])
                view = form.get(scope+'_view','unknown')
                views[scope] = view if view in ('PA','AP') else 'unknown'
            reports = [report for scope in ('prior','current') if (report := await report_input(form, scope))]
            cid = 'upload-'+uuid.uuid4().hex[:12]
            if not comparison_name:
                comparison_name = f'Untitled comparison {cid[-4:].upper()}'
            folder = RUNTIME/'uploads'/cid
            folder.mkdir(parents=True, mode=0o700)
            record = dict(id=cid,set='upload',slot=None,name=comparison_name,source='User upload',
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
    ensure_idle(selected['id'])
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
        c.execute('INSERT INTO run_inputs VALUES (?,?)', (rid,json.dumps(selected)))
        c.execute('INSERT INTO runs (id,case_id,status,stage,result,trace,error,created,updated,engine) VALUES (?,?,?,?,?,?,?,?,?,?)',
                  (rid,selected['id'],'queued','queued',None,'[]',None,now,now,engine))
    retain_task(rid,asyncio.create_task(process_run(rid,manifest_path,engine)))
    return ui_adapter.run(run_record(rid),selected)

@app.get('/api/runs/{run_id}')
def get_run(run_id: str):
    record = run_record(run_id)
    with connect() as c:
        snapshot = c.execute('SELECT payload FROM run_inputs WHERE id=?', (run_id,)).fetchone()
    return ui_adapter.run(record,json.loads(snapshot[0]) if snapshot else case(record['case_id']))

def ensure_idle(case_id):
    with connect() as c:
        active = c.execute("SELECT id FROM runs WHERE case_id=? AND status IN ('queued','running')", (case_id,)).fetchone()
    if active:
        raise HTTPException(409, 'Stop the running comparison before changing it.')


def save_case_edit(item):
    previous = case(item['id'])
    value = {k:v for k,v in item.items() if k not in ('gate','history','last_run','replay','signoff','status')}
    value['revision'] = item.get('revision', 1) + 1
    with connect() as c:
        # Freeze legacy run inputs before applying the first editable revision.
        for row in c.execute('SELECT id FROM runs WHERE case_id=?',(item['id'],)).fetchall():
            c.execute('INSERT OR IGNORE INTO run_inputs VALUES (?,?)',(row[0],json.dumps(previous)))
        c.execute('INSERT INTO case_edits VALUES (?,?,0) ON CONFLICT(id) DO UPDATE SET payload=excluded.payload',
                  (item['id'], json.dumps(value)))


def check_revision(item, revision):
    if str(item['revision']) != str(revision):
        raise HTTPException(409, 'This comparison changed in another window. Refresh and try again.')


@app.post('/api/runs/{run_id}/interrupt')
async def interrupt(run_id: str):
    record = run_record(run_id)
    if record['status'] not in ('queued','running'):
        return {'status':record['status']}
    folder = RUNTIME/'runs'/run_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder/'cancelled').touch()
    update_run(run_id,status='interrupted',stage='interrupted',error='Stopped by you.')
    task = RUN_TASKS.get(run_id)
    if task:
        task.cancel()
    errors = await openswarm_workflow.stop_sessions(folder)
    return {'status':'interrupted', 'warning': 'Local work stopped; OpenSwarm could not confirm every session stopped.' if errors else None}


@app.delete('/api/cases/{case_id}')
async def delete_case(case_id: str):
    item = case(case_id)
    ensure_idle(case_id)
    with connect() as c:
        for row in c.execute('SELECT id FROM runs WHERE case_id=?',(case_id,)).fetchall():
            c.execute('INSERT OR IGNORE INTO run_inputs VALUES (?,?)',(row[0],json.dumps(item)))
        c.execute('INSERT INTO case_edits(id,deleted) VALUES (?,1) ON CONFLICT(id) DO UPDATE SET deleted=1', (case_id,))
    return {'deleted':True}


@app.post('/api/cases/{case_id}/restore')
def restore_case(case_id: str):
    if not any(item['id']==case_id for item in cases(include_deleted=True)):
        raise HTTPException(404, 'Comparison not found.')
    with connect() as c:
        c.execute('UPDATE case_edits SET deleted=0 WHERE id=?', (case_id,))
    return {'restored':True}


@app.get('/api/deleted-cases')
def deleted_cases():
    with connect() as c:
        ids = {row[0] for row in c.execute('SELECT id FROM case_edits WHERE deleted=1')}
    return [{'id':item['id'],'name':item['name']} for item in cases(include_deleted=True) if item['id'] in ids]


@app.post('/api/cases/{case_id}/swap')
async def swap_case(case_id: str, request: Request):
    body = await request.json()
    if not isinstance(body,dict) or not isinstance(body.get('move_reports',True),bool):
        raise HTTPException(422, 'Provide a valid switch request.')
    item = case(case_id)
    ensure_idle(case_id)
    check_revision(item, body.get('revision'))
    if body.get('confirmed') is not True:
        raise HTTPException(422, 'Confirm the corrected chronological order.')
    item['prior'], item['current'] = item['current'], item['prior']
    if body.get('move_reports', True):
        for report in item['reports']:
            report['scope'] = 'current' if report['scope']=='prior' else 'prior'
    item['purpose'] = 'Image order corrected and confirmed by uploader; chronology is not independently verified.'
    save_case_edit(item)
    return {'saved':True}


@app.post('/api/cases/{case_id}/reports')
async def add_reports(case_id: str, request: Request):
    item = case(case_id)
    ensure_idle(case_id)
    try:
        async with request.form(max_files=4, max_fields=4, max_part_size=MAX_REPORT) as form:
            check_revision(item, form.get('revision'))
            added = [report for scope in ('prior','current') if (report := await report_input(form, scope))]
            if not added:
                raise ValueError('Add at least one report.')
            occupied = {report['scope'] for report in item['reports']}
            duplicate = next((report['scope'] for report in added if report['scope'] in occupied), None)
            if duplicate:
                label = 'earlier' if duplicate == 'prior' else 'current'
                raise ValueError(f'The {label} study already has a report. Each study can have only one.')
            if len(item['reports'])+len(added)>2:
                raise ValueError('A comparison can have at most two reports: one earlier and one current.')
            ensure_idle(case_id)
            check_revision(case(case_id), form.get('revision'))
            item['reports'].extend(added)
            save_case_edit(item)
    except ValueError as exc:
        raise HTTPException(422,str(exc)) from exc
    return {'saved':True}


@app.put('/api/cases/{case_id}/reports/{scope}')
async def replace_report(case_id: str, scope: str, request: Request):
    if scope not in ('prior', 'current'):
        raise HTTPException(404, 'Study not found.')
    item = case(case_id)
    ensure_idle(case_id)
    try:
        async with request.form(max_files=1, max_fields=2, max_part_size=MAX_REPORT) as form:
            check_revision(item, form.get('revision'))
            report = await report_input(form, scope)
            if not report:
                raise ValueError('Paste report text or attach one report file.')
            item['reports'] = [saved for saved in item['reports'] if saved['scope'] != scope] + [report]
            check_revision(case(case_id), form.get('revision'))
            save_case_edit(item)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {'saved': True}


@app.post('/api/cases/{case_id}/images/{scope}')
async def replace_image(case_id: str, scope: str, request: Request):
    if scope not in ('prior', 'current'):
        raise HTTPException(404, 'Study not found.')
    item = case(case_id)
    ensure_idle(case_id)
    try:
        async with request.form(max_files=1, max_fields=4, max_part_size=MAX_IMAGE) as form:
            check_revision(item, form.get('revision'))
            if form.get('confirmed') != 'true':
                raise ValueError('Confirm that this replacement remains the same patient and correct study order.')
            file = form.get('image')
            if not hasattr(file, 'read') or not getattr(file, 'filename', ''):
                raise ValueError('Choose a PNG or JPEG image.')
            blob = await file.read(MAX_IMAGE + 1)
            metadata = validate_image(blob)
            view = form.get('view', 'unknown')
            if view not in ('PA', 'AP', 'unknown'):
                view = 'unknown'
            suffix = '.png' if metadata['format'] == 'PNG' else '.jpg'
            name = f'{scope}-v{item.get("revision", 1)+1}{suffix}'
            folder = image_folder(item['id'])
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
            (folder/name).write_bytes(blob)
            item[scope] = {'image':name, 'view':view, 'order':None, **metadata,
                           'sha256':hashlib.sha256(blob).hexdigest()}
            item['purpose'] = 'Replacement image and chronology confirmed by uploader; not independently verified.'
            check_revision(case(case_id), form.get('revision'))
            save_case_edit(item)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {'saved': True}


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
