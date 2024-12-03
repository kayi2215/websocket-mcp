from typing import Any, List, Dict
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import logging

logger = logging.getLogger(__name__)

class MCPClient:
    def __init__(self, server_params: StdioServerParameters):
        self.server_params = server_params
        self.session = None
        self._client = None
        
    async def __aenter__(self):
        """Async context manager entry"""
        await self.connect()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.session:
            await self.session.__aexit__(exc_type, exc_val, exc_tb)
        if self._client:
            await self._client.__aexit__(exc_type, exc_val, exc_tb)

    async def connect(self):
        """Establishes connection to MCP server"""
        self._client = stdio_client(self.server_params)
        self.read, self.write = await self._client.__aenter__()
        session = ClientSession(self.read, self.write)
        self.session = await session.__aenter__()
        await self.session.initialize()

    async def get_available_tools(self) -> List[Any]:
        """List available tools"""
        if not self.session:
            raise RuntimeError("Not connected to MCP server")
            
        tools = await self.session.list_tools()
        _, tools_list = tools
        _, tools_list = tools_list
        return tools_list

    async def call_tool(self, tool_name: str, arguments: dict) -> Any:
        """Call a tool with given arguments"""
        if not self.session:
            raise RuntimeError("Not connected to MCP server")
            
        result = await self.session.call_tool(tool_name, arguments=arguments)
        return result

class MCPToolManager:
    def __init__(self):
        self.tools = []
        self.mcp_clients: Dict[str, MCPClient] = {}
        
    def update_tools(self, tools: List[Dict[str, Any]]):
        """Update the list of available tools"""
        self.tools = tools
        
    async def execute_tool(self, tool_request: Dict[str, Any]) -> Any:
        """Execute a tool request"""
        tool_name = tool_request["name"]
        tool_input = tool_request.get("input", {})
        
        # Find the server for this tool
        server_name = None
        for tool in self.tools:
            if tool["name"] == tool_name:
                server_name = tool["serverName"]
                break
                
        if not server_name:
            raise ValueError(f"Tool {tool_name} not found")
            
        # Get or create MCP client for this server
        if server_name not in self.mcp_clients:
            server_params = self._get_server_params(server_name)
            client = MCPClient(server_params)
            await client.connect()
            self.mcp_clients[server_name] = client
            
        client = self.mcp_clients[server_name]
        return await client.call_tool(tool_name, tool_input)
        
    def _get_server_params(self, server_name: str) -> StdioServerParameters:
        """Get server parameters for a given server name"""
        return StdioServerParameters(
            command=["python", "-m", "mcp.server"],
            cwd=f"/Users/younesbami/Projects/claude/servers/src/{server_name}"
        )
