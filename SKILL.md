---
name: resources-server
description: Interact with the in-memory resource server for storing and retrieving files via REST API.
metadata:
  clawdbot:
    emoji: "📦"
    requires:
      bins: [curl]
---

# Resources Server Skill

Temporary file storage and retrieval via REST API. Files are stored in memory only.

## Quick Start

```bash
cd ~/resources_server && ./init.sh start
curl http://localhost:3100/health
```

## Server Management

| Command | Action |
|---------|--------|
| `./init.sh start` | Start server |
| `./init.sh stop` | Stop server |
| `./init.sh restart` | Restart server |
| `./init.sh logs` | View logs |
| `./init.sh status` | Check status |

## API Usage

### Upload

```bash
# Upload a file
curl -X POST -F "file=@/path/to/file.html" -F "format=html" http://localhost:3100/upload

# Upload from stdin
echo '<h1>Hello</h1>' | curl -X POST -F "file=@-" -F "format=html" http://localhost:3100/upload
```

Response:
```json
{
  "id": "a1b2c3d4",
  "filename": "file.html",
  "url": "/resource/a1b2c3d4"
}
```

### Access Resource

**URL format:**
```
http://<HOST_IP>:3100/resource/{id}
```

> **Note:** Use the machine's network IP (not `localhost`) for external access. Get it with: `hostname -I | awk '{print $1}'`

Example:
```bash
# Get network IP
IP=$(hostname -I | awk '{print $1}')
echo "http://$IP:3100/resource/a1b2c3d4"
```

### Update / Delete

```bash
# Update resource
curl -X PUT -F "file=@new_file.html" -F "format=html" http://localhost:3100/resource/{id}

# List all resources
curl http://localhost:3100/resources
```

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| Port | 3100 | Server port |
| TTL | 24h | Resource lifetime |
| Storage | RAM only | Data lost on restart |

## Troubleshooting

```bash
# Check if running
./init.sh status

# Port in use
sudo lsof -i :3100 && ./init.sh restart

# Full reset
./init.sh down && ./init.sh start
```
