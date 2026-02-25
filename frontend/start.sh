#!/bin/bash

# AI Finance Platform - Frontend Quick Start Script
# This script helps you quickly start the frontend server

echo "🚀 AI Finance Platform - Frontend Server"
echo "========================================"
echo ""

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3 first."
    exit 1
fi

echo "✅ Python 3 found"
echo ""

# Get the directory where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Change to the frontend directory
cd "$SCRIPT_DIR"

echo "📂 Current directory: $SCRIPT_DIR"
echo ""

# Check if index.html exists
if [ ! -f "index.html" ]; then
    echo "❌ index.html not found. Are you in the frontend directory?"
    exit 1
fi

echo "✅ Frontend files found"
echo ""

# Default port
PORT=8080

# Check if port is already in use
if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "⚠️  Port $PORT is already in use. Trying port 8081..."
    PORT=8081
    
    if lsof -Pi :$PORT -sTCP:LISTEN -t >/dev/null 2>&1; then
        echo "⚠️  Port $PORT is also in use. Trying port 8082..."
        PORT=8082
    fi
fi

echo "🌐 Starting frontend server on port $PORT..."
echo ""
echo "📍 Access the application at:"
echo "   - Test Page:  http://localhost:$PORT/test.html"
echo "   - Dashboard:  http://localhost:$PORT/index.html"
echo ""
echo "⚠️  Make sure the backend is running on http://127.0.0.1:8000"
echo ""
echo "Press Ctrl+C to stop the server"
echo "========================================"
echo ""

# Start the Python HTTP server
python3 -m http.server $PORT
