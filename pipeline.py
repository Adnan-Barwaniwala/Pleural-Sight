"""One TimeLens investigation, driven by OpenSwarm agents or the headless runner.

Both engines invoke exactly the same run-bound tools, so the result and trace
shape is identical whichever engine ran the case.
"""
import asyncio
from pathlib import Path

from analysis_mcp import Worker
import verdict

LABELS = {'image': 'Blind Reader', 'report': 'Report Reader', 'investigator': 'Investigator'}
TOOLS = {'image': 'read_pair', 'report': 'read_reports', 'investigator': 'reassess'}


def skipped(role, reason):
    return {'role': role, 'label': LABELS[role], 'tool': TOOLS[role], 'session_id': None, 'status': reason,
            'seconds': 0, 'tool_calls': 0, 'tool_attempts': 0, 'rejected_tool_calls': 0}


async def execute(manifest_path, engine, progress=None):
    manifest_path = Path(manifest_path)
    worker = Worker(manifest_path)
    manifest = worker.manifest
    gate = manifest['gate']
    note = progress or (lambda stage: None)
    base = {'gate': gate, 'orchestrator': engine.name, 'status': 'needs_human_review', 'version': 2}
    if not gate['comparable']:
        note('gate_stopped')
        agents = [skipped(role, 'skipped_gate_failed') for role in ('image', 'report', 'investigator')]
        return {**base, 'reading': None, 'reports': None, 'reassessment': None, 'agents': agents,
                'verdict': verdict.final(gate, None, manifest['reports'], {'claims': []})}
    roles = ['image'] + (['report'] if manifest['reports'] else [])
    note('readers_running')
    completed = await asyncio.gather(*(engine.invoke(role) for role in roles))
    outputs = {role: result for role, (result, _) in zip(roles, completed)}
    agents = [trace for _, trace in completed]
    if 'report' not in outputs:
        outputs['report'] = {'data': {'claims': []}, 'trace': {'model_requests': 0}}
        agents.append(skipped('report', 'skipped_no_report'))
    reading, extracted = outputs['image']['data'], outputs['report']['data']
    reassessment = None
    if verdict.disputes(reading, manifest['reports'], extracted):
        note('investigating')
        reassessment, trace = await engine.invoke('investigator')
        agents.append(trace)
    else:
        agents.append(skipped('investigator', 'skipped_no_dispute'))
    note('finalizing')
    return {**base, 'reading': outputs['image'], 'reports': outputs['report'], 'reassessment': reassessment,
            'agents': agents, 'verdict': verdict.final(gate, reading, manifest['reports'], extracted, reassessment)}
