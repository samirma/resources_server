# Resource Server

In-memory REST API for storing and retrieving binary resources with automatic expiration.

## Features

- **POST /upload** - Upload files with unique ID
- **GET /resource/<id>** - Retrieve binary resources
- **PUT /resource/<id>** - Update existing resources
- **GET /resources** - List all resources with expiration dates
- **GET /health** - Health check
- **Auto-cleanup** - Resources expire after 24 hours

## API Endpoints

### POST /upload
Upload a file and receive a unique resource ID.

**Request:**
```bash
curl -X POST -F "file=@document.pdf" -F "format=pdf" http://localhost:3100/upload
```

**Response:**
```json
{
  "id": "a1b2c3d4",
  "filename": "document.pdf",
  "content_type": "application/pdf",
  "size": 1024567,
  "created_at": "2026-03-20T19:23:45.123456",
  "url": "/resource/a1b2c3d4"
}
```

### GET /resource/<id>
Retrieve a resource by ID.

**Request:**
```bash
curl http://localhost:3100/resource/a1b2c3d4
```

**Response:** Binary data with appropriate Content-Type header

### PUT /resource/<id>
Update an existing resource.

**Request:**
```bash
curl -X PUT -F "file=@updated.pdf" -F "format=pdf" http://localhost:3100/resource/a1b2c3d4
```

### GET /resources
List all active resources with metadata and expiration information.

**Request:**
```bash
curl http://localhost:3100/resources
```

**Response:**
```json
{
  "resources": [
    {
      "id": "a1b2c3d4",
      "filename": "document.pdf",
      "content_type": "application/pdf",
      "size": 1024567,
      "created_at": "2026-03-20T19:23:45.123456",
      "expires_at": "2026-03-21T19:23:45.123456",
      "ttl_seconds": 86400,
      "time_remaining_seconds": 82000
    }
  ],
  "count": 1,
  "ttl_hours": 24
}
```

### GET /health
Health check endpoint.

**Request:**
```bash
curl http://localhost:3100/health
```

**Response:**
```json
{
  "status": "healthy",
  "resources_count": 1,
  "uptime": "running"
}
```

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| Port | 3100 | Server port |
| TTL | 24 hours | Resource lifetime |
| Cleanup Interval | 1 hour | Background cleanup frequency |

## Storage

**IMPORTANT:** Resources are stored **ONLY in RAM** (memory), not on disk. Resources:
- Exist only while the server is running
- Automatically expire after 24 hours
- Are lost if the server restarts

## Docker

Build and run with Docker Compose:

```bash
cd ~/resources_server
./init.sh start
```

## Docker Compose Commands

| Command | Description |
|---------|-------------|
| `./init.sh start` | Start the server (background) |
| `./init.sh stop` | Stop the server |
| `./init.sh restart` | Restart the server |
| `./init.sh down` | Stop and remove containers |
| `./init.sh rebuild` | Rebuild and start |
| `./init.sh logs` | View live logs |
| `./init.sh status` | Show container status |

## Running the Server

### Start the Server
```bash
cd ~/resources_server
./init.sh start
```

**Verify server is running:**
```bash
curl http://localhost:3100/health
```

### Stop the Server
```bash
./init.sh stop
```

### View Logs
```bash
./init.sh logs
```

### Rebuild (after code changes)
```bash
./init.sh rebuild
```

## Files

| File | Purpose |
|------|---------|
| `main.py` | Flask server with all endpoints |
| `Dockerfile` | Container configuration |
| `docker-compose.yml` | Docker Compose configuration |
| `requirements.txt` | Python dependencies |
| `README.md` | This documentation |
