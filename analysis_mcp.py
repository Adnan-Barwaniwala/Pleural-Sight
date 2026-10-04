"""Run-bound MCP worker: Gemini receives bytes directly, MCP returns text only.

The trusted backend supplies an immutable run manifest at process startup.
Callers cannot supply prompts, report text, paths, or another run ID through tools.
Each OpenSwarm agent gets a connector exposing only its role's tool, and the
stages table in the run folder is the shared blackboard between agents.
"""
import asyncio
import json
import os
from pathlib import Path
import sqlite3

import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server
import gemini_direct as gemini
import verdict

EMPTY = {'type': 'object', 'properties': {}, 'additionalProperties': False}
NAMES = ['read_pair', 'read_reports', 'reassess']
SCHEMAS = {name: EMPTY for name in NAMES}
ROLE_TOOLS = {'image': ['read_pair'], 'report': ['read_reports'], 'investigator': ['reassess']}
DESCRIPTIONS = {
    'read_pair': 'Blind Reader: reads both films twice (slots swapped) without any report. Takes no arguments.',
    'read_reports': 'Report Reader: extracts effusion claims from report text only. Takes no arguments.',
    'reassess': 'Investigator: one targeted, report-blind second look at the disputed film. Takes no arguments.',
}


class Worker:
    def __init__(self, manifest_path):
        path = Path(manifest_path)
        self.manifest = json.loads(path.read_text())
        self.db = path.parent/'stages.sqlite'
        with self.connect() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS stages (name TEXT PRIMARY KEY, status TEXT, payload TEXT)')

    def connect(self):
        return sqlite3.connect(self.db, timeout=10)

    def get(self, name):
        with self.connect() as conn:
            row = conn.execute('SELECT status,payload FROM stages WHERE name=?', (name,)).fetchone()
        if row is None or row[0] != 'complete':
            return None
        return json.loads(row[1])

    def failure(self, name):
        with self.connect() as conn:
            row = conn.execute('SELECT status,payload FROM stages WHERE name=?', (name,)).fetchone()
        if row and row[0] == 'failed':
            return json.loads(row[1]).get('error') if row[1] else 'unknown error'
        return None

    def require(self, name):
        value = self.get(name)
        if value is None:
            raise gemini.ModelError(f'Complete {name} first.')
        return value

    def images(self):
        return Path(self.manifest['prior']).read_bytes(), Path(self.manifest['current']).read_bytes()

    def reports_output(self):
        if not self.manifest['reports']:
            return {'data': {'claims': []}, 'trace': {'model_requests': 0}}
        return self.require('read_reports')

    async def call(self, name, arguments):
        if name not in SCHEMAS or arguments:
            raise gemini.ModelError('Unknown tool or forbidden arguments.')
        existing = self.get(name)
        if existing is not None:
            return existing
        if not self.manifest.get('gate', {}).get('comparable', True):
            raise gemini.ModelError('Comparability gate failed; no model call is permitted for this run.')
        if name == 'reassess':
            scopes = verdict.disputes(self.require('read_pair')['data'], self.manifest['reports'],
                                      self.reports_output()['data'])
            if not scopes:
                raise gemini.ModelError('No disputed film; reassessment is not permitted.')
        # Reject duplicate in-flight calls across processes; reassess runs at most once per run.
        with self.connect() as conn:
            try:
                conn.execute('INSERT INTO stages VALUES (?, ?, NULL)', (name, 'running'))
            except sqlite3.IntegrityError:
                raise gemini.ModelError('Stage already ran or is running; it cannot be repeated.') from None
        try:
            if name == 'read_pair':
                result = await gemini.read_pair(*self.images())
            elif name == 'read_reports':
                reports = self.manifest['reports']
                result = await gemini.read_reports(reports) if reports else {'data': {'claims': []}, 'trace': {'model_requests': 0}}
            else:
                result = await gemini.reassess(*self.images(), verdict.targeted_question(scopes))
                result['data']['scopes'] = scopes
        except BaseException as exc:
            message = str(exc) if isinstance(exc, gemini.ModelError) else 'local error'
            with self.connect() as conn:
                conn.execute('UPDATE stages SET status=?,payload=? WHERE name=?', ('failed', json.dumps({'error': message}), name))
            raise
        with self.connect() as conn:
            conn.execute('UPDATE stages SET status=?,payload=? WHERE name=?', ('complete', json.dumps(result), name))
        return result


def create_server(worker, role=None):
    exposed = ROLE_TOOLS.get(role, NAMES if role is None else [])
    if not exposed:
        raise gemini.ModelError('Unknown TimeLens MCP role.')

    async def list_tools(context, params):
        return types.ListToolsResult(tools=[types.Tool(name=n, description=DESCRIPTIONS[n], inputSchema=EMPTY) for n in exposed])

    async def call_tool(context, params):
        try:
            if params.name not in exposed:
                raise gemini.ModelError('Tool is not available to this role.')
            result = await worker.call(params.name, params.arguments or {})
            return types.CallToolResult(content=[types.TextContent(type='text', text=json.dumps(summarize(params.name, result)))])
        except gemini.ModelError as exc:
            return types.CallToolResult(isError=True, content=[types.TextContent(type='text', text=str(exc))])
        except Exception:
            return types.CallToolResult(isError=True, content=[types.TextContent(type='text', text='TimeLens operation failed; check local configuration.')])

    return Server('timelens-analysis', on_list_tools=list_tools, on_call_tool=call_tool, get_tool_input_schema=SCHEMAS.get)


def summarize(name, result):
    """What the agent sees: structured findings only, never image bytes or report text."""
    data = result['data']
    if name == 'read_pair':
        return {'reading_a': data['reading_a']['label'], 'reading_b': data['reading_b']['label'],
                'order_swap_consistent': data['consistent'], 'stored': True}
    if name == 'read_reports':
        return {'claims': [{'report_index': c['report_index'], 'state': c['state']} for c in data['claims']], 'stored': True}
    return {'question': data['question'], 'reassessment_label': data['label'], 'stored': True}


async def main():
    server = create_server(Worker(os.environ['TIMELENS_RUN_MANIFEST']), os.environ.get('TIMELENS_ROLE'))
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == '__main__':
    asyncio.run(main())
