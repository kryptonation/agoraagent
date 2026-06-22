#!/bin/bash

# AgoraAgent Web Dashboard Runner

# Exit on interrupt
trap cleanup INT

cleanup() {
  echo -e "\n\033[1;31mShutting down services...\033[0m"
  # Kill all child jobs
  kill $(jobs -p) 2>/dev/null
  exit 0
}

echo -e "\033[1;35m====================================================\033[0m"
echo -e "\033[1;35m            AGORAAGENT WEB DASHBOARD                \033[0m"
echo -e "\033[1;35m====================================================\033[0m"

# 1. Sync backend dependencies
echo -e "\033[1;34m[1/3] Syncing python packages with uv...\033[0m"
uv sync
if [ $? -ne 0 ]; then
  echo -e "\033[1;31mError: Python sync failed.\033[0m"
  exit 1
fi

# 2. Build or verify frontend node modules
echo -e "\033[1;34m[2/3] Checking frontend dependencies...\033[0m"
if [ ! -d "frontend/node_modules" ]; then
  echo -e "\033[1;33mNode modules not found, installing packages...\033[0m"
  cd frontend && npm install && cd ..
fi

# 3. Start Python API Backend
echo -e "\033[1;34m[3/3] Starting FastAPI negotiation backend...\033[0m"
export PYTHONPATH=.
.venv/bin/python src/morekick/server.py &
BACKEND_PID=$!

# Wait briefly for backend to initialize
sleep 2

# Check if backend started successfully
if ! kill -0 $BACKEND_PID 2>/dev/null; then
  echo -e "\033[1;31mError: FastAPI server failed to start. Check ports or logs.\033[0m"
  exit 1
fi
echo -e "\033[1;32mFastAPI negotiation backend is running on http://localhost:8000\033[0m"

# 4. Start React Frontend
echo -e "\033[1;34mStarting Vite dev server...\033[0m"
cd frontend
npm run dev &
FRONTEND_PID=$!

cd ..
echo -e "\033[1;32mBoth services are running!\033[0m"
echo -e "\033[1;36mOpen http://localhost:5173 to access the dashboard.\033[0m"
echo -e "\033[1;33mPress Ctrl+C to terminate both servers.\033[0m"

# Keep the shell script alive to monitor background tasks
wait
