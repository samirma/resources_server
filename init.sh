#!/bin/bash
# Resources Server - Docker Compose Management Script

set -e

cd "$(dirname "$0")"

PORT="${RESOURCE_SERVER_PORT:-3100}"

case "${1:-start}" in
  start)
    echo "🚀 Starting Resource Server..."
    docker compose up -d
    echo "✅ Resource Server started on port $PORT"
    echo "   Health: http://localhost:$PORT/health"
    ;;
  stop)
    echo "🛑 Stopping Resource Server..."
    docker compose stop
    echo "✅ Resource Server stopped"
    ;;
  down)
    echo "🗑️ Removing Resource Server..."
    docker compose down
    echo "✅ Resource Server removed"
    ;;
  restart)
    echo "🔄 Restarting Resource Server..."
    docker compose restart
    echo "✅ Resource Server restarted"
    ;;
  rebuild)
    echo "🔨 Rebuilding Resource Server..."
    docker compose up -d --build
    echo "✅ Resource Server rebuilt"
    ;;
  logs)
    docker compose logs -f
    ;;
  status)
    docker compose ps
    ;;
  test)
    echo "🧪 Running tests..."
    if [ ! -x .venv/bin/python ]; then
      python3 -m venv .venv
      .venv/bin/pip install -q -r requirements-dev.txt
    fi
    .venv/bin/python -m pytest --cov=main --cov-report=term-missing
    ;;
  *)
    echo "Usage: $0 {start|stop|down|restart|rebuild|logs|status|test}"
    exit 1
    ;;
esac
