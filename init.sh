#!/bin/bash
# Resources Server - Docker Compose Management Script

set -e

cd "$(dirname "$0")"

case "${1:-start}" in
  start)
    echo "🚀 Starting Resource Server..."
    docker compose up -d
    echo "✅ Resource Server started on port 3100"
    echo "   Health: http://localhost:3100/health"
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
  *)
    echo "Usage: $0 {start|stop|down|restart|rebuild|logs|status}"
    exit 1
    ;;
esac
