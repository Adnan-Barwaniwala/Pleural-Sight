"""Run-bound MCP worker: Gemini receives bytes directly, MCP returns text only.

The trusted backend supplies an immutable run manifest at process startup.
Callers cannot supply prompts, report text, paths, or another run ID through tools.
This is application input isolation, not an OS sandbox for OpenSwarm itself.
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

EMPTY = {'type': 'object', 'properties': {}, 'additionalProperties': False}
NAMES = ['assess_images', 'read_reports', 'compare_findings', 'investigate', 'reassess_images']
SCHEMAS = {name: EMPTY for name in NAMES}
ROLE_TOOLS = {'image': ['assess_images'], 'report': ['read_reports']}


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

    def require(self, name):
        value = self.get(name)
        if value is None:
            raise gemini.ModelError(f'Complete {name} first.')
        return value

    async def call(self, name, arguments):
        if name not in SCHEMAS or arguments:
            raise gemini.ModelError('Unknown tool or forbidden arguments.')
        existing = self.get(name)
        if existing is not None:
            return existing
        # Reject duplicate in-flight calls across processes; never silently replay paid calls.
        if name == 'compare_findings':
            self.require('assess_images')
            self.require('read_reports')
        if name == 'investigate' and not self.require('compare_findings')['investigate']:
            return {'skipped': True, 'reason': 'No discrepancy or unresolved assessment.'}
        if name == 'reassess_images' and not self.require('investigate')['data']['request_reassessment']:
            raise gemini.ModelError('Investigator did not request reassessment.')
        with self.connect() as conn:
            try:
                conn.execute('INSERT INTO stages VALUES (?, ?, NULL)', (name, 'running'))
            except sqlite3.IntegrityError:
                raise gemini.ModelError('Stage is already running, failed or interrupted; explicit recovery is required.') from None
        try:
            if name in ('assess_images','reassess_images'):
                # Both initial and reassessment calls use exactly the same neutral inputs.
                result = await gemini.assess_images(
                    Path(self.manifest['prior']).read_bytes(), Path(self.manifest['current']).read_bytes())
            elif name == 'read_reports':
                reports = self.manifest['reports']
                result = await gemini.read_reports(reports) if reports else {'data': {'claims': []}, 'trace': {'model_requests': 0}}
            elif name == 'compare_findings':
                result = gemini.compare(self.require('assess_images')['data'], self.manifest['reports'], self.require('read_reports')['data'])
            else:
                result = await gemini.investigate({'images': self.require('assess_images')['data'],
                                                 'comparison': self.require('compare_findings')})
        except BaseException:
            with self.connect() as conn:
                conn.execute('UPDATE stages SET status=? WHERE name=?', ('failed',name))
            raise
        with self.connect() as conn:
            conn.execute('UPDATE stages SET status=?,payload=? WHERE name=?', ('complete',json.dumps(result),name))
        return result


def create_server(worker, role=None):
    exposed = ROLE_TOOLS.get(role, NAMES if role is None else [])
    if not exposed:
        raise gemini.ModelError('Unknown TimeLens MCP role.')

    async def list_tools(context, params):
        return types.ListToolsResult(tools=[types.Tool(name=n, description='Run-bound TimeLens operation: '+n, inputSchema=EMPTY) for n in exposed])

    async def call_tool(context, params):
        try:
            if params.name not in exposed:
                raise gemini.ModelError('Tool is not available to this role.')
            result = await worker.call(params.name, params.arguments or {})
            return types.CallToolResult(content=[types.TextContent(type='text', text=json.dumps(result))])
        except gemini.ModelError as exc:
            return types.CallToolResult(isError=True, content=[types.TextContent(type='text', text=str(exc))])
        except Exception:
            return types.CallToolResult(isError=True, content=[types.TextContent(type='text', text='TimeLens operation failed; check local configuration.')])

    return Server('timelens-analysis', on_list_tools=list_tools, on_call_tool=call_tool, get_tool_input_schema=SCHEMAS.get)


async def main():
    server = create_server(Worker(os.environ['TIMELENS_RUN_MANIFEST']), os.environ.get('TIMELENS_ROLE'))
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


if __name__ == '__main__':
    asyncio.run(main())
