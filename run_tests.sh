#!/bin/bash

# Kill any existing process using port 8000
echo "Checking for existing processes on port 8000..."
lsof -ti:8000 | xargs kill -9 2>/dev/null || true

# Start the MCP filesystem server in the background
echo "Starting MCP filesystem server..."
/opt/homebrew/bin/npx -y @modelcontextprotocol/server-filesystem "/Users/younesbami/Claude" &
MCP_PID=$!

# Wait for MCP server to start
sleep 2

# Start the WebSocket server in the background
echo "Starting WebSocket server..."
python app/main.py &
SERVER_PID=$!

# Wait for the server to start and be ready
echo "Waiting for server to start..."
sleep 5  # Increased wait time

# Function to check if server is ready
check_server() {
    curl -s http://localhost:8000/docs > /dev/null
    return $?
}

# Wait for server to be ready
echo "Checking if server is ready..."
COUNTER=0
while ! check_server && [ $COUNTER -lt 10 ]; do
    sleep 1
    let COUNTER=COUNTER+1
done

if ! check_server; then
    echo "Server failed to start"
    kill $SERVER_PID 2>/dev/null || true
    kill $MCP_PID 2>/dev/null || true
    exit 1
fi

echo "Server is ready"

# Run the tests
echo "Running tests..."
python tests/test_websocket.py
TEST_EXIT_CODE=$?

# Clean up - kill both servers
echo "Cleaning up..."
kill $SERVER_PID 2>/dev/null || true
kill $MCP_PID 2>/dev/null || true

# Exit with the test exit code
exit $TEST_EXIT_CODE
