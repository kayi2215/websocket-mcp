from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from typing import List, Dict, Any
import json
import asyncio
import logging
import os
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import subprocess
from pathlib import Path
from websocket_tool_manager import WebSocketToolManager, ToolResponse
from contextlib import asynccontextmanager
from asyncio import CancelledError
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse
from app.agent import WebSocketAgent

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Define paths
ROOT_DIR = str(Path(__file__).parent.parent.parent.parent)
CONFIG_PATH = str(Path(__file__).parent.parent / "config" / "mcp-servers.json")

# Initialize the GPT agent
agent = WebSocketAgent()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan context manager for FastAPI application startup and shutdown events"""
    try:
        # Startup
        logger.info("Starting WebSocket server...")
        await start_servers()  # Start servers first
        await mcp_manager.initialize_mcp_servers()  # Then initialize MCP
        
        yield
        
    finally:
        # Shutdown
        logger.info("Shutting down WebSocket server...")
        try:
            await mcp_manager.close_all_connections()
        except CancelledError:
            # Ignore cancellation during shutdown
            pass
        except Exception as e:
            logger.error(f"Error during shutdown: {e}")

app = FastAPI(lifespan=lifespan)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # React dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class MCPClient:
    def __init__(self, server_params: StdioServerParameters):
        self.server_params = server_params
        # Add /opt/homebrew/bin to PATH
        if 'env' not in self.server_params.__dict__:
            self.server_params.env = {}
        if 'PATH' in self.server_params.env:
            self.server_params.env['PATH'] = f"/opt/homebrew/bin:{self.server_params.env['PATH']}"
        else:
            self.server_params.env['PATH'] = "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
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
            
        logger.info("Requesting available tools from MCP server...")
        tools = await self.session.list_tools()
        _, tools_list = tools
        _, tools_list = tools_list
        logger.info(f"Received tools from MCP server: {tools_list}")
        return tools_list

    async def call_tool(self, tool_name: str, arguments: Dict) -> Any:
        """Call a specific tool"""
        if not self.session:
            raise RuntimeError("Not connected to MCP server")
            
        # Remove server prefix if present
        if '.' in tool_name:
            tool_name = tool_name.split('.', 1)[1]
            
        logger.info(f"Tool call request received - Tool: {tool_name}, Params: {arguments}")
        result = await self.session.call_tool(tool_name, arguments=arguments)
        logger.info(f"Tool call result: {result}")
        
        # Convert result to tool response format
        if hasattr(result, 'content') and hasattr(result, 'isError'):
            if result.isError:
                return {
                    "type": "tool_response",
                    "status": "error",
                    "result": {
                        "status": "error",
                        "error": result.content[0].text if result.content else "Unknown error"
                    }
                }
            else:
                return {
                    "type": "tool_response",
                    "status": "success",
                    "result": {
                        "status": "success",
                        "result": result.content[0].text if result.content else None
                    }
                }
        return {
            "type": "tool_response",
            "status": "success",
            "result": result
        }

class MCPManager:
    def __init__(self):
        """Initialize the MCP manager"""
        self.mcp_clients = {}
        self.client_tasks = {}  # Track tasks for each client
        self.tool_manager = WebSocketToolManager()

    async def initialize_mcp_servers(self):
        """Initialize server configurations"""
        try:
            with open(CONFIG_PATH, "r") as f:
                configs = json.load(f)
                
            for server_name, config in configs.items():
                server_params = StdioServerParameters(
                    command=config["command"],
                    args=config.get("args", []),
                    env=config.get("env", {})
                )
                self.mcp_clients[server_name] = MCPClient(server_params)
                # Connecter immédiatement le serveur
                await self.connect_to_server(server_name)
                
        except Exception as e:
            logger.error(f"Failed to initialize MCP servers: {e}")
            raise

    async def load_server_configs(self):
        """Load server configurations"""
        try:
            with open(CONFIG_PATH, "r") as f:
                configs = json.load(f)
                
            for server_name, config in configs.items():
                server_params = StdioServerParameters(
                    command=config["command"],
                    args=config.get("args", []),
                    env=config.get("env", {})
                )
                self.mcp_clients[server_name] = MCPClient(server_params)
                
        except Exception as e:
            logger.error(f"Failed to load server configurations: {e}")
            raise

    async def connect_to_server(self, server_name: str):
        """Connect to an MCP server and register its tools"""
        if server_name not in self.mcp_clients:
            raise ValueError(f"Unknown server: {server_name}")
            
        client = self.mcp_clients[server_name]
        
        try:
            # Create and await the connection task
            task = asyncio.create_task(client.__aenter__())
            self.client_tasks[server_name] = task
            await task
            
            # Get and register tools
            tools = await client.get_available_tools()
            
            # Register tools with the tool manager
            for tool in tools:
                # Créer une fonction de rappel spécifique pour cet outil
                async def tool_callback(arguments: Dict[str, Any]) -> Dict[str, Any]:
                    return await client.call_tool(tool.name, arguments)
                
                # Enregistrer l'outil avec le bon format
                self.tool_manager.register_tool(
                    name=f"{server_name}.{tool.name}",
                    func=tool_callback,
                    description=tool.description,
                    input_schema=tool.inputSchema
                )
                logger.info(f"Registered tool: {server_name}.{tool.name}")
                
            return tools
            
        except Exception as e:
            logger.error(f"Failed to connect to server {server_name}: {e}")
            if server_name in self.client_tasks:
                del self.client_tasks[server_name]
            raise

    async def ensure_connection(self, server_name: str) -> bool:
        """Ensure connection to server exists, attempting reconnection if needed"""
        try:
            if server_name not in self.mcp_clients:
                logger.error(f"Server {server_name} not found in mcp_clients")
                return False
                
            client = self.mcp_clients[server_name]
            
            # Vérifier si le client est déjà connecté
            if not client.session:
                logger.info(f"Connecting to server {server_name}...")
                await client.__aenter__()
            
            # Obtenir et réenregistrer les outils
            try:
                tools = await client.get_available_tools()
                
                # Re-register tools with the tool manager
                for tool in tools:
                    async def tool_callback(arguments: Dict[str, Any]) -> Dict[str, Any]:
                        return await client.call_tool(tool.name, arguments)
                        
                    self.tool_manager.register_tool(
                        name=f"{server_name}.{tool.name}",
                        func=tool_callback,
                        description=tool.description,
                        input_schema=tool.inputSchema
                    )
                logger.info(f"Successfully connected to server {server_name}")
                return True
            except Exception as tool_error:
                logger.error(f"Error getting tools from {server_name}: {tool_error}")
                return False
            
        except Exception as e:
            logger.error(f"Failed to connect to {server_name}: {e}")
            return False

    async def get_tools(self, server_name: str = None) -> List[Dict[str, Any]]:
        """Get available tools, optionally filtered by server"""
        tools = self.tool_manager.list_tools()
        
        # Convertir les outils au format attendu par le frontend
        formatted_tools = []
        for tool in tools:
            # Extraire le nom du serveur du nom complet de l'outil
            full_name = tool['name']
            server, tool_name = full_name.split('.', 1)
            
            formatted_tools.append({
                'name': tool_name,
                'serverName': server,
                'description': tool['description'],
                'input_schema': tool['input_schema']
            })
        
        # Filtrer par serveur si demandé
        if server_name:
            formatted_tools = [t for t in formatted_tools if t['serverName'] == server_name]
            
        return formatted_tools

    async def call_tool(self, server_name: str, tool_name: str, arguments: Dict) -> Dict:
        """Call a tool with given arguments"""
        if server_name not in self.mcp_clients:
            raise ValueError(f"Not connected to server: {server_name}")
            
        # Add server prefix to tool name if not present
        if not tool_name.startswith(f"{server_name}."):
            tool_name = f"{server_name}.{tool_name}"
            
        try:
            client = self.mcp_clients[server_name]
            result = await client.call_tool(tool_name, arguments)
            return result  # Return the response directly without modifying the type
        
        except Exception as e:
            logger.error(f"Error calling tool {tool_name}: {e}")
            return {
                "type": "tool_response",
                "status": "error",
                "result": {
                    "status": "error",
                    "error": str(e)
                }
            }

    async def close_all_connections(self):
        """Clean up all MCP client connections"""
        errors = []
        current_task = asyncio.current_task()
        
        for server_name, client in self.mcp_clients.items():
            try:
                # Only close connections that were created in the current task
                if server_name in self.client_tasks and self.client_tasks[server_name] == current_task:
                    await client.__aexit__(None, None, None)
                    del self.client_tasks[server_name]
            except Exception as e:
                errors.append(f"Error closing {server_name}: {e}")
                
        if errors:
            raise Exception("; ".join(errors))

    async def process_message(self, message: str, servers: List[str]) -> str:
        """Process a message with the AI agent"""
        # TO DO: implement AI agent processing
        return message

class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}  # client_id -> WebSocket
        self.client_servers: Dict[str, set] = {}  # client_id -> set of server names

    async def connect(self, websocket: WebSocket, client_id: str):
        """Connect a new WebSocket client"""
        await websocket.accept()
        self.active_connections[client_id] = websocket
        if client_id not in self.client_servers:
            self.client_servers[client_id] = set()
        logger.info(f"Client {client_id} connected")

    async def disconnect(self, websocket: WebSocket):
        """Disconnect a client but maintain their server connections"""
        # Find and remove client from active connections
        for client_id, ws in self.active_connections.items():
            if ws == websocket:
                del self.active_connections[client_id]
                logger.info(f"Client {client_id} disconnected")
                break

    def add_server_connection(self, client_id: str, server_name: str):
        """Track that a client is connected to a server"""
        if client_id not in self.client_servers:
            self.client_servers[client_id] = set()
        self.client_servers[client_id].add(server_name)
        logger.info(f"Added server connection {server_name} for client {client_id}")

    def get_client_servers(self, client_id: str) -> set:
        """Get the set of servers a client is connected to"""
        return self.client_servers.get(client_id, set())

manager = ConnectionManager()
mcp_manager = MCPManager()

@app.post("/servers/start")
async def start_servers():
    """Start all MCP servers"""
    try:
        await mcp_manager.load_server_configs()
        return {"status": "success", "message": "All servers started"}
    except Exception as e:
        logger.error(f"Error starting servers: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/tools")
async def get_tools():
    """Get all available tools"""
    try:
        # First, make sure we're connected to all servers
        for server_name in mcp_manager.mcp_clients.keys():
            await mcp_manager.connect_to_server(server_name)
        
        # Then get all tools
        tools = await mcp_manager.get_tools()
        return tools
    except Exception as e:
        logger.error(f"Error getting tools: {e}")
        return {"status": "error", "message": str(e)}

@app.get("/events")
async def events(request: Request):
    """SSE endpoint for real-time updates"""
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            
            # Send heartbeat every 15 seconds
            yield {
                "event": "heartbeat",
                "data": "ping"
            }
            
            await asyncio.sleep(15)
            
    return EventSourceResponse(event_generator())

@app.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    logger.info(f"New WebSocket connection request from client {client_id}")
    await manager.connect(websocket, client_id)
    
    try:
        # Send initial connection success
        await websocket.send_json({
            "type": "connection_established",
            "status": "connected",
            "client_id": client_id
        })
        logger.info(f"Sent connection success to client {client_id}")
        
        # Send available tools
        try:
            tools = await mcp_manager.get_tools()
            agent.set_available_tools(tools)  # Update agent's tools
            await websocket.send_json({
                "type": "tools",
                "tools": tools
            })
            logger.info(f"Sent tools list to client {client_id}")
        except Exception as e:
            logger.error(f"Error getting tools for client {client_id}: {e}")
            await websocket.send_json({
                "type": "error",
                "message": "Failed to get available tools"
            })
        
        while True:
            try:
                message = await websocket.receive_json()
                logger.info(f"Received message from client {client_id}: {message}")
                
                if message["type"] == "connect":
                    server_name = message["server"]
                    logger.info(f"Client {client_id} requesting connection to server {server_name}")
                    
                    try:
                        await mcp_manager.connect_to_server(server_name)
                        manager.add_server_connection(client_id, server_name)
                        
                        await websocket.send_json({
                            "type": "connection_established",
                            "server": server_name
                        })
                        
                        # Update tools after new connection
                        tools = await mcp_manager.get_tools()
                        agent.set_available_tools(tools)  # Update agent's tools
                        await websocket.send_json({
                            "type": "tools",
                            "tools": tools
                        })
                        
                    except Exception as e:
                        logger.error(f"Error connecting to server {server_name}: {e}")
                        await websocket.send_json({
                            "type": "error",
                            "message": f"Error connecting to server: {str(e)}"
                        })

                elif message["type"] == "agent_message":
                    # Process message with GPT agent
                    try:
                        response = await agent.process_message(message["content"])
                        await websocket.send_json({
                            "type": "response",
                            "content": response
                        })
                    except Exception as e:
                        logger.error(f"Error processing message with agent: {e}")
                        await websocket.send_json({
                            "type": "error",
                            "message": f"Error processing message: {str(e)}"
                        })
                
                else:
                    await websocket.send_json({
                        "type": "error",
                        "message": "Unknown message type"
                    })
                    
            except json.JSONDecodeError:
                logger.error(f"Invalid JSON received from client {client_id}")
                await websocket.send_json({
                    "type": "error",
                    "message": "Invalid message format"
                })
                
            except Exception as e:
                logger.error(f"Error processing message from client {client_id}: {e}")
                await websocket.send_json({
                    "type": "error",
                    "message": str(e)
                })
                
    except WebSocketDisconnect:
        logger.info(f"Client {client_id} disconnected")
        manager.disconnect(websocket)
        
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
