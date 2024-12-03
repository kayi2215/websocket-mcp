from typing import Dict, Any, Optional, List
import logging
import json
from dataclasses import dataclass
from jsonschema import validate, ValidationError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@dataclass
class ToolResponse:
    """Standardized response format for tool execution"""
    toolUseId: str  # Changed from tool_id to match reference
    content: List[Dict[str, str]]  # Changed to match reference format
    status: str  # 'success' or 'error'

class WebSocketToolManager:
    """
    Manages tool registration, validation, and execution for WebSocket server.
    Provides a standardized interface for tool operations.
    """
    
    def __init__(self):
        self._tools: Dict[str, Dict[str, Any]] = {}
        self._execution_history: List[Dict[str, Any]] = []

    def register_tool(self, name: str, func: callable, description: str, input_schema: Dict[str, Any]) -> None:
        """
        Register a new tool with validation schema
        
        Args:
            name: Tool identifier
            func: Async function to execute
            description: Tool description
            input_schema: JSON schema for input validation
        """
        if name in self._tools:
            logger.warning(f"Tool {name} already registered. Overwriting.")
            
        self._tools[name] = {
            'function': func,
            'description': description,
            'input_schema': input_schema
        }
        logger.info(f"Registered tool: {name}")

    def get_tool_schema(self, name: str) -> Optional[Dict[str, Any]]:
        """Get the input schema for a specific tool"""
        if name not in self._tools:
            return None
        return self._tools[name]['input_schema']

    def list_tools(self) -> List[Dict[str, Any]]:
        """List all registered tools with their descriptions and schemas"""
        return [
            {
                'name': name,
                'description': tool['description'],
                'input_schema': tool['input_schema']
            }
            for name, tool in self._tools.items()
        ]

    async def execute_tool(self, tool_request: Dict[str, Any]) -> ToolResponse:
        """
        Execute a tool with validation and error handling
        
        Args:
            tool_request: Dictionary containing:
                - toolUseId: Unique identifier for this execution
                - name: Tool name
                - input: Tool arguments
                
        Returns:
            ToolResponse object containing execution results
        """
        tool_use_id = tool_request.get('toolUseId', 'unknown')
        tool_name = tool_request.get('name')
        tool_input = tool_request.get('input', {})

        # Log execution request
        self._execution_history.append({
            'toolUseId': tool_use_id,
            'tool_name': tool_name,
            'input': tool_input,
            'timestamp': 'timestamp'  # TODO: Add actual timestamp
        })

        try:
            # Validate tool exists
            if tool_name not in self._tools:
                raise ValueError(f"Unknown tool: {tool_name}")

            tool = self._tools[tool_name]
            
            # Validate input against schema
            try:
                validate(instance=tool_input, schema=tool['input_schema'])
            except ValidationError as e:
                return ToolResponse(
                    toolUseId=tool_use_id,
                    content=[{'text': f"Invalid input: {str(e)}"}],
                    status='error'
                )

            # Execute tool
            result = await tool['function'](tool_name, tool_input)
            
            return ToolResponse(
                toolUseId=tool_use_id,
                content=[{'text': str(result)}],
                status='success'
            )

        except Exception as e:
            logger.error(f"Error executing tool {tool_name}: {str(e)}")
            return ToolResponse(
                toolUseId=tool_use_id,
                content=[{'text': str(e)}],
                status='error'
            )

    def get_execution_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get recent tool execution history"""
        return self._execution_history[-limit:]

    def clear_history(self) -> None:
        """Clear execution history"""
        self._execution_history.clear()
