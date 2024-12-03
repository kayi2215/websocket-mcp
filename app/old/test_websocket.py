import asyncio
import websockets
import json
import logging
import traceback
from typing import Dict, Any

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class WebSocketTestClient:
    def __init__(self, uri: str = "ws://localhost:8000/ws/test-client"):
        self.uri = uri
        self.websocket = None
        
    async def __aenter__(self):
        """Async context manager entry"""
        logger.info(f"Connecting to WebSocket server at {self.uri}")
        try:
            # Increase timeout to 30 seconds
            self.websocket = await websockets.connect(
                self.uri,
                open_timeout=30,
                close_timeout=30
            )
            logger.info("Successfully connected to WebSocket server")
            return self
        except Exception as e:
            logger.error(f"Failed to connect to WebSocket server: {str(e)}")
            raise
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self.websocket:
            try:
                await self.websocket.close()
                logger.info("WebSocket connection closed")
            except Exception as e:
                logger.error(f"Error closing WebSocket connection: {str(e)}")
            
    async def receive_json(self) -> Dict[str, Any]:
        """Receive and parse JSON message"""
        try:
            response = await asyncio.wait_for(self.websocket.recv(), timeout=30)
            logger.info(f"Received: {response}")
            return json.loads(response)
        except Exception as e:
            logger.error(f"Error receiving message: {str(e)}")
            raise
        
    async def send_json(self, data: Dict[str, Any]):
        """Send JSON message"""
        try:
            message = json.dumps(data)
            logger.info(f"Sending: {message}")
            await asyncio.wait_for(self.websocket.send(message), timeout=30)
            logger.info("Message sent successfully")
        except Exception as e:
            logger.error(f"Error sending message: {str(e)}")
            raise
        
    async def test_connection(self):
        """Test initial connection"""
        try:
            logger.info("Testing initial connection...")
            response = await self.receive_json()
            assert response["type"] == "connection_established"
            assert response["status"] == "connected"
            logger.info("✅ Connection test passed")
        except Exception as e:
            logger.error(f"Connection test failed: {str(e)}")
            raise
        
    async def test_connect_to_server(self, server_name: str):
        """Test connecting to an MCP server"""
        try:
            logger.info(f"Testing connection to {server_name} server...")
            await self.send_json({
                "type": "connect",
                "server": server_name
            })
            response = await self.receive_json()
            assert response["type"] == "connect_response"
            assert response["status"] == "success"
            logger.info(f"✅ Server connection test passed for {server_name}")
        except Exception as e:
            logger.error(f"Server connection test failed for {server_name}: {str(e)}")
            raise
        
    async def test_get_tools(self, server_name: str):
        """Test getting available tools"""
        try:
            logger.info(f"Testing get tools for {server_name} server...")
            await self.send_json({
                "type": "get_tools",
                "server": server_name
            })
            response = await self.receive_json()
            assert response["type"] == "tools_response"
            assert response["status"] == "success"
            assert "tools" in response
            
            # Vérifier le format des outils
            for tool in response["tools"]:
                assert "name" in tool, "Tool must have a name"
                assert "serverName" in tool, "Tool must have a serverName"
                assert "description" in tool, "Tool must have a description"
                assert "input_schema" in tool, "Tool must have an input_schema"
                assert tool["serverName"] == server_name, f"Tool serverName must match {server_name}"
            
            logger.info(f"✅ Get tools test passed for {server_name}")
            return response["tools"]
        except Exception as e:
            logger.error(f"Get tools test failed for {server_name}: {str(e)}")
            raise
        
    async def test_call_tool(self, server_name: str, tool_name: str, arguments: Dict[str, Any]):
        """Test calling a specific tool"""
        try:
            logger.info(f"Testing tool call for {tool_name} on {server_name}...")
            await self.send_json({
                "type": "call_tool",
                "server": server_name,
                "tool": tool_name,
                "arguments": arguments
            })
            response = await self.receive_json()
            assert response["type"] == "tool_response"
            assert response["status"] == "success"
            assert "result" in response, "Tool response must include a result"
            
            logger.info(f"Tool response: {json.dumps(response, indent=2)}")
            logger.info("✅ Tool call test passed")
            return response
        except Exception as e:
            logger.error(f"Tool call test failed for {tool_name}: {str(e)}")
            raise

    async def test_reconnection(self):
        """Test reconnection functionality"""
        try:
            logger.info("Testing reconnection...")
            
            # First connect to the filesystem server
            await self.send_json({
                "type": "connect",
                "server": "filesystem"
            })
            response = await self.receive_json()
            assert response["type"] == "connect_response"
            assert response["status"] == "success"
            logger.info("✅ Initial server connection successful")

            # Close the websocket to simulate a disconnection
            await self.websocket.close()
            logger.info("Closed WebSocket connection")

            # Wait a moment before reconnecting
            await asyncio.sleep(1)

            # Reconnect with a new websocket
            self.websocket = await websockets.connect(self.uri)
            logger.info("Reconnected to WebSocket")

            # Should receive connection established message
            response = await self.receive_json()
            assert response["type"] == "connection_established"
            assert response["status"] == "connected"
            logger.info("✅ Reconnection handshake successful")

            # Should receive reconnection status with reconnected servers
            response = await self.receive_json()
            assert response["type"] == "reconnection_status"
            assert "reconnected_servers" in response
            assert "filesystem" in response["reconnected_servers"]
            logger.info("✅ Server connections restored")

            # Verify we can still use tools
            await self.test_get_tools("filesystem")
            logger.info("✅ Tools still accessible after reconnection")
            
            logger.info("✅ Reconnection test passed")
        except Exception as e:
            logger.error(f"Reconnection test failed: {str(e)}")
            raise

async def run_tests():
    """Run all WebSocket tests"""
    try:
        logger.info("Starting WebSocket tests...")
        logger.info(f"Connecting to WebSocket server at {WebSocketTestClient().uri}")
        
        async with WebSocketTestClient() as client:
            # Test 1: Initial connection
            await client.test_connection()
            
            # Test 2: Connect to filesystem server
            await client.test_connect_to_server("filesystem")
            
            # Test 3: Get available tools
            tools = await client.test_get_tools("filesystem")
            
            # Test 4: Call a tool
            if tools:
                # Utiliser le premier outil disponible pour le test
                tool = tools[0]
                await client.test_call_tool(
                    server_name="filesystem",
                    tool_name=tool["name"],
                    arguments={}  # Utiliser un argument vide pour le test
                )
            
            # Test 5: Test reconnection
            await client.test_reconnection()
            
            logger.info("✅ All tests passed successfully!")
            
    except Exception as e:
        logger.error("Tests failed with error:")
        logger.error(traceback.format_exc())
        raise

if __name__ == "__main__":
    # Run the tests
    asyncio.run(run_tests())
