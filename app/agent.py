import os
from dotenv import load_dotenv
import json
from openai import AsyncOpenAI
import logging
from typing import List, Dict, Any
from app.mcp_tools import MCPToolManager

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)

class WebSocketAgent:
    def __init__(self, model="gpt-4-turbo-preview"):
        self.model = model
        self.api_key = os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            logger.error("OPENAI_API_KEY environment variable is not set")
            raise ValueError("OPENAI_API_KEY environment variable is not set")
        self.client = AsyncOpenAI(api_key=self.api_key)
        self.system_prompt = """You are an AI assistant integrated with an MCP (Multi-tool Command Protocol) system.
Your primary role is to help users interact with various tools through the MCP protocol.
When users request actions like creating folders or files, you should:
1. Identify the appropriate MCP tool for the task
2. Use the tool with the correct parameters
3. Provide feedback about the action's success or failure

For example, if a user asks to create a folder, you should:
- Use the appropriate MCP file system tool
- Pass the correct path and parameters
- Confirm the creation or explain any errors

Always try to understand the user's intent and use the available tools appropriately.
Respond in a helpful and conversational manner."""
        self.messages = [{"role": "system", "content": self.system_prompt}]
        self.tool_manager = MCPToolManager()
        
    def set_available_tools(self, tools: List[Dict[str, Any]]):
        """Update available tools and system prompt with tool descriptions"""
        logger.info("Updating available tools")
        self.tool_manager.update_tools(tools)
        tools_description = "\n\nAvailable tools:\n"
        for tool in tools:
            tools_description += f"- {tool['name']}: {tool['description']} (from {tool['serverName']})\n"
        self.system_prompt += tools_description
        # Reset conversation history when tools are updated
        self.messages = [{"role": "system", "content": self.system_prompt}]
        logger.info("Tools updated successfully")

    async def process_message(self, message: str) -> str:
        """Process a user message and return a response"""
        logger.info("Processing message: %s", message)
        self.messages.append({"role": "user", "content": message})

        try:
            response = await self._get_gpt_response()
            result = await self._handle_response(response)
            logger.info("Got response from GPT: %s", result)
            return result
        except Exception as e:
            logger.error("Error processing message: %s", str(e), exc_info=True)
            return f"Sorry, I encountered an error while processing your message: {str(e)}"

    async def _get_gpt_response(self):
        """Get response from GPT model"""
        logger.info("Getting GPT response with model: %s", self.model)
        functions = []
        if self.tool_manager:
            for tool in self.tool_manager.tools:
                functions.append({
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": {
                            "type": "object",
                            "properties": tool.get("parameters", {}),
                            "required": tool.get("required", [])
                        }
                    }
                })

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=self.messages,
                tools=functions if functions else None,
                tool_choice="auto"
            )
            return response
        except Exception as e:
            logger.error("Error getting GPT response: %s", str(e), exc_info=True)
            raise

    async def _handle_response(self, response):
        """Handle the response from the model"""
        try:
            message = response.choices[0].message

            # Check if the model wants to use a tool
            if message.tool_calls:
                logger.info("Model wants to use tools")
                tool_responses = []
                
                for tool_call in message.tool_calls:
                    try:
                        tool_request = {
                            "name": tool_call.function.name,
                            "input": json.loads(tool_call.function.arguments)
                        }
                        logger.info("Executing tool: %s with input: %s", 
                                  tool_request["name"], tool_request["input"])
                        tool_result = await self.tool_manager.execute_tool(tool_request)
                        tool_responses.append({
                            "tool_call_id": tool_call.id,
                            "output": json.dumps(tool_result)
                        })
                    except Exception as e:
                        logger.error("Error executing tool %s: %s", 
                                   tool_call.function.name, str(e), exc_info=True)
                        tool_responses.append({
                            "tool_call_id": tool_call.id,
                            "output": f"Error: {str(e)}"
                        })

                # Add assistant's message with tool calls
                self.messages.append(message)
                
                # Add tool response messages
                for tool_response in tool_responses:
                    self.messages.append({
                        "role": "tool",
                        "tool_call_id": tool_response["tool_call_id"],
                        "content": tool_response["output"]
                    })

                # Get final response after tool use
                return await self.process_message("Please provide a response based on the tool results.")
            else:
                # Regular response without tool use
                logger.info("Regular response without tool use")
                self.messages.append(message)
                return message.content
        except Exception as e:
            logger.error("Error handling response: %s", str(e), exc_info=True)
            raise
