"""Nonclinical image-transport probe, using the official MCP SDK."""
import asyncio
import base64
import json
import os
from pathlib import Path
import mcp.types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

ROOT = Path(os.environ['TIMELENS_PROBE_DIR'])
SCHEMAS = {
    'get_probe_pair': {'type': 'object', 'properties': {}, 'additionalProperties': False},
    'submit_probe': {'type': 'object', 'properties': {'first': {'type': 'string'}, 'second': {'type': 'string'}, 'forbidden_access': {'type': 'string'}}, 'required': ['first', 'second', 'forbidden_access'], 'additionalProperties': False},
}

async def list_tools(context, params):
    return types.ListToolsResult(tools=[types.Tool(name=name, description='TimeLens nonclinical integration probe: '+name, inputSchema=schema) for name, schema in SCHEMAS.items()])

async def call_tool(context, params):
    if params.name == 'get_probe_pair':
        content = []
        for i in [1, 2]:
            content += [types.TextContent(type='text', text=f'Image {i}'), types.ImageContent(type='image', mimeType='image/png', data=base64.b64encode((ROOT/f'{i}.png').read_bytes()).decode())]
        return types.CallToolResult(content=content)
    if params.name == 'submit_probe':
        result = ROOT/'answer.json'
        result.write_text(json.dumps(params.arguments, indent=2))
        return types.CallToolResult(content=[types.TextContent(type='text', text='Recorded. Stop now.')])
    return types.CallToolResult(isError=True, content=[types.TextContent(type='text', text='Forbidden tool')])

server = Server('timelens-probe', on_list_tools=list_tools, on_call_tool=call_tool, get_tool_input_schema=SCHEMAS.get)

async def main():
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())

if __name__ == '__main__':
    asyncio.run(main())
