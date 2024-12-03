import asyncio
import json
import logging
import os
from pathlib import Path
from main import MCPManager

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Get the root directory of the project
CONFIG_PATH = str(Path(__file__).parent.parent / "config" / "mcp-servers.json")

def load_server_configs():
    """Load server configurations from mcp-servers.json."""
    try:
        with open(CONFIG_PATH, "r") as f:
            configs = json.load(f)
            return configs
    except Exception as e:
        logger.error(f"Failed to load server configs from {CONFIG_PATH}: {e}")
        raise

async def list_all_tools():
    """List available tools from all MCP servers."""
    configs = load_server_configs()
    manager = MCPManager()
    
    # List tools for each server in the config
    for server_name, server_config in configs.items():
        try:
            # Skip servers that require environment variables that aren't set
            if "env" in server_config:
                missing_vars = [key for key, _ in server_config["env"].items() if key not in os.environ]
                if missing_vars:
                    logger.warning(f"Skipping {server_name} server - missing required environment variables: {', '.join(missing_vars)}")
                    continue

            logger.info(f"\n{'='*50}")
            logger.info(f"Listing tools for {server_name} server")
            logger.info(f"{'='*50}")
            
            # Set environment variables if specified in config
            if "env" in server_config:
                for key, value in server_config["env"].items():
                    os.environ[key] = value
                    logger.info(f"Set environment variable {key}")
            
            try:
                tools = await manager.get_tools(server_name)
                logger.info(f"Available tools for {server_name}:")
                for tool in tools:
                    logger.info(f"- {tool.name}: {tool.description}")
            except Exception as e:
                logger.warning(f"Failed to get tools from {server_name} server: {e}")
                continue
                
            # Clean up environment variables
            if "env" in server_config:
                for key in server_config["env"].keys():
                    if key in os.environ:
                        del os.environ[key]
                        logger.info(f"Cleaned up environment variable {key}")
                        
        except Exception as e:
            logger.error(f"Error listing tools for {server_name}: {str(e)}")
            continue

if __name__ == "__main__":
    try:
        asyncio.run(list_all_tools())
    except KeyboardInterrupt:
        logger.info("\nScript interrupted by user")
    except Exception as e:
        logger.error(f"Error: {str(e)}")
