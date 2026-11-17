"""Invoke the configured AWS MCP server from a terminal when not loaded by the agent."""
import asyncio
import json
import os
import sys
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    env = dict(os.environ, AWS_MCP_PROXY_PROFILES=os.getenv('AWS_PROFILE', 'system-design-simulator-free'), AWS_REGION='us-east-2')
    command = str(Path.home() / '.local/bin/uvx.exe') if os.name == 'nt' else 'uvx'
    params = StdioServerParameters(command=command, args=['mcp-proxy-for-aws@latest', 'https://aws-mcp.us-east-1.api.aws/mcp', '--metadata', 'AWS_REGION=us-east-2'], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            if len(sys.argv) == 1:
                result = await session.list_tools()
                for tool in result.tools:
                    if 'search_documentation' in tool.name or 'retrieve_skill' in tool.name:
                        print(json.dumps(tool.model_dump(), ensure_ascii=True))
                return
            else:
                argument = Path(sys.argv[2])
                payload = argument.read_text() if argument.is_file() else sys.argv[2]
                result = await session.call_tool(sys.argv[1], json.loads(payload))
            print(json.dumps(result.model_dump(), ensure_ascii=True, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
