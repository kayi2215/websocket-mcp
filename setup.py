from setuptools import setup, find_packages

setup(
    name="websocket_server",
    version="0.1",
    packages=find_packages(),
    install_requires=[
        "fastapi>=0.109.0",
        "uvicorn>=0.32.0",
        "websockets==12.0",
        "python-dotenv==1.0.0",
        "openai==1.12.0",
        "pydantic>=2.8.0",
        "jsonschema>=4.21.1",
        "sse-starlette>=2.0.0",
        "mcp>=1.0.0"
    ],
)
