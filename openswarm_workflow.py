"""Two-agent OpenSwarm orchestrator for run-bound TimeLens MCP tools."""
import asyncio
import os
from pathlib import Path
import time

import gemini_direct as gemini
from analysis_mcp import Worker
from swarm_api import call as swarm_call

ROOT = Path(__file__).parent
ROLE_TOOL = {'image': 'assess_images', 'report': 'read_reports'}
TERMINAL_FAILURES = {'failed', 'stopped', 'interrupted', 'cancelled', 'error'}


class OpenSwarmError(RuntimeError):
    pass


async def api(path, data=None, method=None, timeout=30):
    try:
        return await asyncio.to_thread(swarm_call, path, data, method, timeout)
    except Exception as exc:
        raise OpenSwarmError('OpenSwarm API is unavailable or rejected the TimeLens request.') from exc


def _unwrap(value, key):
    return value.get(key, value) if isinstance(value, dict) else value


async def register_role(run_id, role, manifest_path):
    tool_name = ROLE_TOOL[role]
    name = f'timelens-{run_id[:10]}-{role}'
    created = await api('/api/tools/create', {
        'name': name,
        'description': f'TimeLens {role} agent connector for run {run_id[:10]}',
        'auth_type': 'none', 'auth_status': 'configured',
        'mcp_config': {'type': 'stdio', 'command': os.sys.executable,
                       'args': [str(ROOT/'analysis_mcp.py')],
                       'env': {'TIMELENS_RUN_MANIFEST': str(manifest_path), 'TIMELENS_ROLE': role}},
    })
    tool = _unwrap(created, 'tool')
    if not isinstance(tool, dict) or not tool.get('id'):
        raise OpenSwarmError(f'OpenSwarm did not create the {role} connector.')
    registration = {'tool_id': tool['id'], 'mode_id': None, 'name': name, 'role': role}
    try:
        discovered = _unwrap(await api(f"/api/tools/{tool['id']}/discover", {}, timeout=120), 'tool')
        permissions = discovered.get('tool_permissions', {}) if isinstance(discovered, dict) else {}
        names = [item for item in permissions if not item.startswith('_')]
        if names != [tool_name]:
            raise OpenSwarmError(f'{role.title()} connector exposed an unexpected tool surface: {names}.')
        await api(f"/api/tools/{tool['id']}", {'tool_permissions': {tool_name: 'always_allow'}}, 'PUT')
        marker = 'mcp:'+name
        qualified = 'mcp__'+name+'__'+tool_name
        instructions = (
            f'You are the TimeLens {"Image Analyst" if role == "image" else "Report Reader"}. '
            f'Activate only the connector named {name}, call {tool_name} exactly once with the input exactly {{}}. '
            'Do not add a reason or any other argument. '
            'briefly acknowledge whether it completed, and stop. Do not use filesystem, shell, browser, memory, '
            'session, web, or any other connector. The assigned MCP tool owns all private inputs; do not seek them.'
        )
        mode_created = await api('/api/modes/create', {
            'name': name, 'memory_scope': 'own', 'tools': [marker, qualified],
            'instructions': instructions, 'system_prompt': instructions,
            'model': os.environ.get('TIMELENS_OPENSWARM_MODEL', 'gemini-3.8-flash'),
        })
        mode = _unwrap(mode_created, 'mode')
        if not isinstance(mode, dict) or not mode.get('id'):
            raise OpenSwarmError(f'OpenSwarm did not create the {role} mode.')
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


async def launch_role(run_id, manifest_path, registration):
    role = registration['role']
    label = 'Image Analyst' if role == 'image' else 'Report Reader'
    workspace = Path(manifest_path).parent/'agent-workspaces'/role
    workspace.mkdir(parents=True, exist_ok=True, mode=0o700)
    requested_model = os.environ.get('TIMELENS_OPENSWARM_MODEL', 'gemini-3.8-flash')
    launched = await api('/api/agents/launch', {
        'name': f'TimeLens {label} · {run_id[:8]}',
        'model': requested_model, 'provider': 'ag', 'mode': registration['mode_id'],
        'allowed_tools': registration['allowed'], 'system_prompt': registration['instructions'],
        'max_turns': 8, 'target_directory': str(workspace),
        'prompt': registration['instructions'],
    })
    session_id = launched.get('session_id') if isinstance(launched, dict) else None
    if not session_id:
        raise OpenSwarmError(f'OpenSwarm did not launch the {label}.')
    started = time.monotonic()
    worker = Worker(manifest_path)
    tool_name = ROLE_TOOL[role]
    last = {}
    while time.monotonic()-started < 180:
        last = await api(f'/api/agents/sessions/{session_id}', timeout=10)
        status = str(last.get('status','')).lower()
        stage = worker.get(tool_name)
        if status == 'completed':
            if stage is None:
                raise OpenSwarmError(f'{label} completed without submitting its MCP result.')
            messages = last.get('messages', [])
            attempts = [m for m in messages if m.get('role') == 'tool_call' and tool_name in str(m.get('content',''))]
            successes = [m for m in messages if m.get('role') == 'tool_result'
                         and tool_name in str(m.get('content',''))
                         and not (isinstance(m.get('content'),dict) and m['content'].get('is_error'))]
            return stage, {'role': role, 'label': label, 'session_id': session_id,
                'status': status, 'requested_model': requested_model,
                'returned_model': last.get('model'), 'provider': last.get('provider'),
                'seconds': round(time.monotonic()-started,3), 'tool_calls': len(successes),
                'tool_attempts': len(attempts), 'rejected_tool_calls': len(attempts)-len(successes)}
        if status in TERMINAL_FAILURES:
            raise OpenSwarmError(f'{label} ended with OpenSwarm status {status}.')
        await asyncio.sleep(1)
    raise OpenSwarmError(f'{label} timed out after 180 seconds.')


async def execute(manifest_path, progress=None):
    manifest_path = Path(manifest_path)
    worker = Worker(manifest_path)
    has_reports = bool(worker.manifest.get('reports'))
    roles = ['image'] + (['report'] if has_reports else [])
    registrations = []
    try:
        for role in roles:
            registrations.append(await register_role(worker.manifest['run_id'], role, manifest_path))
        if progress:
            progress('agents_running')
        completed = await asyncio.gather(*(launch_role(worker.manifest['run_id'], manifest_path, r) for r in registrations))
        outputs = {registration['role']: result[0] for registration, result in zip(registrations, completed)}
        traces = [result[1] for result in completed]
        if not has_reports:
            outputs['report'] = {'data': {'claims': []}, 'trace': {'model_requests': 0}}
            traces.append({'role': 'report', 'label': 'Report Reader', 'session_id': None,
                           'status': 'skipped_no_report', 'seconds': 0, 'tool_calls': 0,
                           'tool_attempts': 0, 'rejected_tool_calls': 0})
        if progress:
            progress('comparing')
        comparison = gemini.compare(outputs['image']['data'], worker.manifest['reports'], outputs['report']['data'])
        return {'initial': outputs['image'], 'reports': outputs['report'], 'comparison': comparison,
                'agents': traces, 'orchestrator': 'openswarm',
                'status': 'needs_human_review', 'version': 1}
    finally:
        await asyncio.gather(*(cleanup_registration(item) for item in registrations), return_exceptions=True)
