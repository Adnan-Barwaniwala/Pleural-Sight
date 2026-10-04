"""Headless engine: calls the same run-bound tools in-process, with no agents.

Used by the evaluation batch and as the fallback when OpenSwarm is unavailable.
"""
import time
from pathlib import Path

from analysis_mcp import Worker
import pipeline


class HeadlessEngine:
    name = 'headless'

    def __init__(self, manifest_path):
        self.worker = Worker(Path(manifest_path))

    async def invoke(self, role):
        started = time.monotonic()
        tool = pipeline.TOOLS[role]
        result = await self.worker.call(tool, {})
        return result, {'role': role, 'label': pipeline.LABELS[role], 'tool': tool, 'session_id': None,
                        'status': 'completed_headless', 'seconds': round(time.monotonic()-started, 3),
                        'tool_calls': 1, 'tool_attempts': 1, 'rejected_tool_calls': 0,
                        'tool_trace': result.get('trace')}


async def execute(manifest_path, progress=None):
    return await pipeline.execute(manifest_path, HeadlessEngine(manifest_path), progress)
