"""Deterministic MCP client used by TimeLens; can also be driven by OpenSwarm tools."""
import asyncio
import json
import os
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from gemini_direct import ModelError


async def execute(manifest_path):
    parameters = StdioServerParameters(command=sys.executable,
        args=[str(Path(__file__).parent/'analysis_mcp.py')],
        env={**os.environ, 'TIMELENS_RUN_MANIFEST': str(manifest_path)})
    async with stdio_client(parameters) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=120) as session:
            await session.initialize()

            async def call(name):
                result = await session.call_tool(name, {})
                text = ''.join(c.text for c in result.content if c.type == 'text')
                if result.is_error:
                    raise ModelError(text)
                return json.loads(text)

            results = await asyncio.gather(call('assess_images'), call('read_reports'), return_exceptions=True)
            for result in results:
                if isinstance(result, BaseException):
                    raise result
            images, reports = results
            comparison = await call('compare_findings')
            investigator, reassessment = None, None
            if comparison['investigate']:
                investigator = await call('investigate')
                if investigator['data']['request_reassessment']:
                    reassessment = await call('reassess_images')
            return {'initial': images, 'reports': reports, 'comparison': comparison,
                    'investigator': investigator, 'reassessment': reassessment,
                    'reassessment_disagrees': bool(reassessment and any(
                        images['data'][s]['state'] != reassessment['data'][s]['state'] for s in ('prior','current'))),
                    'status': 'needs_human_review', 'version': 1}
