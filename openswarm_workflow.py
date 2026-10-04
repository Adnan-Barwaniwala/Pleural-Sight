"""OpenSwarm engine: one fresh, role-restricted agent per TimeLens tool."""
import asyncio
import json
import os
from pathlib import Path
import sys
import time

from analysis_mcp import Worker
import pipeline
from swarm_api import call as swarm_call

ROOT = Path(__file__).parent
TERMINAL_FAILURES = {'failed', 'stopped', 'interrupted', 'cancelled', 'error'}
AGENT_TIMEOUT = 240


class OpenSwarmError(RuntimeError):
    pass


async def api(path, data=None, method=None, timeout=30):
    try:
        return await asyncio.to_thread(swarm_call, path, data, method, timeout)
    except Exception as exc:
        raise OpenSwarmError('OpenSwarm API is unavailable or rejected the TimeLens request.') from exc


def _unwrap(value, key):
    return value.get(key, value) if isinstance(value, dict) else value


def agent_model():
    return os.environ.get('TIMELENS_OPENSWARM_MODEL', 'gemini-3.8-flash')


async def create_registration(kind, payload):
    """A cancelled HTTP thread can still create a resource: await and remove it."""
    pending = asyncio.create_task(api(f'/api/{kind}/create', payload))
    try:
        return await asyncio.shield(pending)
    except asyncio.CancelledError:
        response = await pending
        item = _unwrap(response, 'tool' if kind=='tools' else 'mode')
        if isinstance(item,dict) and item.get('id'):
            await api(f"/api/{kind}/{item['id']}", method='DELETE')
        raise


async def register_role(run_id, role, manifest_path):
    tool_name = pipeline.TOOLS[role]
    label = pipeline.LABELS[role]
    name = f'timelens-{run_id[:10]}-{role}'
    # The MCP process is launched by OpenSwarm from its own working directory.
    manifest_path = Path(manifest_path).resolve()
    created = await create_registration('tools', {
        'name': name,
        'description': f'TimeLens {label} connector for run {run_id[:10]}',
        'auth_type': 'none', 'auth_status': 'configured',
        'mcp_config': {'type': 'stdio', 'command': sys.executable,
                       'args': [str(ROOT/'analysis_mcp.py')],
                       'env': {'TIMELENS_RUN_MANIFEST': str(manifest_path), 'TIMELENS_ROLE': role}},
    })
    tool = _unwrap(created, 'tool')
    if not isinstance(tool, dict) or not tool.get('id'):
        raise OpenSwarmError(f'OpenSwarm did not create the {label} connector.')
    registration = {'tool_id': tool['id'], 'mode_id': None, 'name': name, 'role': role}
    try:
        discovered = None
        for attempt in range(3):
            try:
                discovered = _unwrap(await api(f"/api/tools/{tool['id']}/discover", {}, timeout=120), 'tool')
                break
            except OpenSwarmError:
                if attempt == 2:
                    raise
                await asyncio.sleep(2)
        permissions = discovered.get('tool_permissions', {}) if isinstance(discovered, dict) else {}
        names = [item for item in permissions if not item.startswith('_')]
        if names != [tool_name]:
            raise OpenSwarmError(f'{label} connector exposed an unexpected tool surface: {names}.')
        await api(f"/api/tools/{tool['id']}", {'tool_permissions': {tool_name: 'always_allow'}}, 'PUT')
        marker = 'mcp:'+name
        qualified = 'mcp__'+name+'__'+tool_name
        instructions = (
            f'You are the TimeLens {label}. '
            f'Activate only the connector named {name}, call {tool_name} exactly once with the input exactly {{}}. '
            'Do not add a reason or any other argument. '
            'Then report the structured result it returned in one short sentence and stop. Do not use filesystem, shell, '
            'browser, memory, session, web, or any other connector. The assigned MCP tool owns all private inputs; '
            'do not seek them.'
        )
        mode_created = await create_registration('modes', {
            'name': name, 'memory_scope': 'own', 'tools': [marker, qualified],
            'instructions': instructions, 'system_prompt': instructions, 'model': agent_model(),
        })
        mode = _unwrap(mode_created, 'mode')
        if not isinstance(mode, dict) or not mode.get('id'):
            raise OpenSwarmError(f'OpenSwarm did not create the {label} mode.')
        registration.update(mode_id=mode['id'], allowed=[marker, qualified], instructions=instructions)
        return registration
    except BaseException:
        await cleanup_registration(registration)
        raise


async def cleanup_registration(registration):
    for kind, identity in [('modes', registration.get('mode_id')), ('tools', registration.get('tool_id'))]:
        if identity:
            try:
                await api(f'/api/{kind}/{identity}', method='DELETE')
            except Exception:
                pass


async def launch_role(run_id, manifest_path, registration, case_name=''):
    role = registration['role']
    label = pipeline.LABELS[role]
    tool_name = pipeline.TOOLS[role]
    workspace = Path(manifest_path).resolve().parent/'agent-workspaces'/role
    workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
    launch_request = asyncio.create_task(api('/api/agents/launch', {
        'name': f'TimeLens · {label} · {case_name or run_id[:8]}',
        'model': agent_model(), 'provider': 'ag', 'mode': registration['mode_id'],
        'allowed_tools': registration['allowed'], 'system_prompt': registration['instructions'],
        'max_turns': 8, 'target_directory': str(workspace),
        'prompt': registration['instructions'],
    }))
    try:
        launched = await asyncio.shield(launch_request)
    except asyncio.CancelledError:
        launched = await launch_request
        if launched.get('session_id'):
            (Path(manifest_path).parent/f'session-{role}.json').write_text(json.dumps({'session_id':launched['session_id']}))
            await api(f"/api/agents/sessions/{launched['session_id']}/stop", {})
        raise
    session_id = launched.get('session_id') if isinstance(launched, dict) else None
    if not session_id:
        raise OpenSwarmError(f'OpenSwarm did not launch the {label}.')
    (Path(manifest_path).parent/f'session-{role}.json').write_text(json.dumps({'session_id':session_id}))
    if (Path(manifest_path).parent/'cancelled').exists():
        await api(f'/api/agents/sessions/{session_id}/stop', {})
        raise asyncio.CancelledError()
    started = time.monotonic()
    worker = Worker(manifest_path)
    while time.monotonic()-started < AGENT_TIMEOUT:
        last = await api(f'/api/agents/sessions/{session_id}', timeout=10)
        status = str(last.get('status', '')).lower()
        stage = worker.get(tool_name)
        if status == 'completed':
            if stage is None:
                failed = worker.failure(tool_name)
                if failed:
                    raise OpenSwarmError(f'{label} called {tool_name}, but the tool failed: {failed}')
                raise OpenSwarmError(f'{label} completed without submitting its MCP result.')
            messages = last.get('messages', [])
            attempts = [m for m in messages if m.get('role') == 'tool_call' and tool_name in str(m.get('content', ''))]
            successes = [m for m in messages if m.get('role') == 'tool_result'
                         and tool_name in str(m.get('content', ''))
                         and not (isinstance(m.get('content'), dict) and m['content'].get('is_error'))]
            return stage, {'role': role, 'label': label, 'tool': tool_name, 'session_id': session_id,
                           'status': status, 'requested_model': agent_model(),
                           'returned_model': last.get('model'), 'provider': last.get('provider'),
                           'seconds': round(time.monotonic()-started, 3), 'tool_calls': len(successes),
                           'tool_attempts': len(attempts), 'rejected_tool_calls': len(attempts)-len(successes),
                           'tool_trace': stage.get('trace')}
        if status in TERMINAL_FAILURES:
            raise OpenSwarmError(f'{label} ended with OpenSwarm status {status}.')
        await asyncio.sleep(1)
    raise OpenSwarmError(f'{label} timed out after {AGENT_TIMEOUT} seconds.')


class OpenSwarmEngine:
    name = 'openswarm'

    def __init__(self, manifest_path):
        self.manifest_path = Path(manifest_path).resolve()
        self.manifest = Worker(self.manifest_path).manifest

    async def invoke(self, role):
        run_id = self.manifest['run_id']
        registration = await register_role(run_id, role, self.manifest_path)
        try:
            try:
                return await launch_role(run_id, self.manifest_path, registration, self.manifest.get('case_name', ''))
            except (asyncio.CancelledError, Exception):
                await stop_sessions(self.manifest_path.parent)
                raise
        finally:
            await cleanup_registration(registration)


async def execute(manifest_path, progress=None):
    return await pipeline.execute(manifest_path, OpenSwarmEngine(manifest_path), progress)


async def stop_sessions(folder):
    errors = []
    for path in Path(folder).glob('session-*.json'):
        session_id = json.loads(path.read_text())['session_id']
        try:
            await api(f'/api/agents/sessions/{session_id}/stop', {}, timeout=10)
        except OpenSwarmError:
            errors.append(session_id)
    return errors
