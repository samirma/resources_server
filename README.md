# Resource Server

In-memory REST API for temporarily sharing files, with automatic expiration.
Behavior is defined in [high_level_spec.md](high_level_spec.md). AI agents use the
server through [SKILL.md](SKILL.md).

## Features

- **GET /** - Redirects to the resource list
- **POST /api/upload** - Upload a file (max 10 MB) and get a unique ID
- **GET /api/resource/<id>** - Retrieve a resource
- **PUT /api/resource/<id>** - Replace an existing resource (restarts its 24h lifetime)
- **GET /api/resources** - List all resources (web page in browsers, JSON otherwise)
- **GET /api/health** - Health check
- **Auto-cleanup** - Resources expire after 24 hours

## Rules

| Rule | Value |
|------|-------|
| Max file size | 10 MB per file, for uploads and replacements |
| Lifetime | 24 hours after upload or last replacement |
| Storage | RAM only, lost on restart |
| Access | Open by design: no authentication, anyone can overwrite any resource |

Open access is intentional. Run the server on a trusted network and only share
non-sensitive content. Resources cannot be deleted; they expire on their own.

## API Endpoints

All endpoints are under `/api/`. The full description is the OpenAPI 3.1 document at
`/api/openapi.json`, generated from the operation list in `openapi.py` (the same list that
registers the routes), so it always matches the server:

```bash
curl http://localhost:3100/api/openapi.json
```

The original addresses without `/api` (`/upload`, `/resource/<id>`, `/resources`, `/health`)
still work as aliases, so links shared before the change keep working. Use `/api/` in new
clients.

### POST /api/upload
Upload a file and receive a unique resource ID.

**Request:**
```bash
curl -X POST -F "file=@document.pdf" -F "format=pdf" http://localhost:3100/api/upload
```

`format` is optional: `html`, `json`, `text` or `pdf`. When given, it sets the content type;
otherwise the type sent by the client is used. Other values are rejected.

**Response (`201`):**
```json
{
  "id": "a1b2c3d4",
  "filename": "document.pdf",
  "content_type": "application/pdf",
  "size": 1024567,
  "created_at": "2026-10-05T12:00:00+00:00",
  "expires_at": "2026-10-06T12:00:00+00:00",
  "url": "/api/resource/a1b2c3d4",
  "link": "http://localhost:3100/api/resource/a1b2c3d4"
}
```

### GET /api/resource/<id>
Retrieve a resource by ID.

```bash
curl http://localhost:3100/api/resource/a1b2c3d4
```

Returns the file with its content type, served inline with its original filename.
Responses are sandboxed (`Content-Security-Policy: sandbox ...`) so uploaded web pages
render and run scripts without acting as the server's own origin.

### PUT /api/resource/<id>
Replace an existing resource. The ID stays the same and the lifetime restarts.
Takes the same fields as `/api/upload`. Returns `404` if the resource is unknown or expired.

```bash
curl -X PUT -F "file=@updated.pdf" -F "format=pdf" http://localhost:3100/api/resource/a1b2c3d4
```

### GET /api/resources
List all live resources. Browsers (which send `Accept: text/html`) get a web page; other
clients get JSON.

```bash
curl http://localhost:3100/api/resources
```

```json
{
  "resources": [
    {
      "id": "a1b2c3d4",
      "filename": "document.pdf",
      "content_type": "application/pdf",
      "size": 1024567,
      "created_at": "2026-10-05T12:00:00+00:00",
      "expires_at": "2026-10-06T12:00:00+00:00",
      "url": "/api/resource/a1b2c3d4",
      "link": "http://localhost:3100/api/resource/a1b2c3d4",
      "ttl_seconds": 86400,
      "time_remaining_seconds": 82000
    }
  ],
  "count": 1,
  "ttl_hours": 24,
  "max_file_size_bytes": 10485760
}
```

### GET /api/health

```bash
curl http://localhost:3100/api/health
```

```json
{
  "status": "healthy",
  "resources_count": 1,
  "uptime_seconds": 3600
}
```

### Errors

Errors return JSON: `{"error": "..."}`. Request bodies above 40 MB are refused by Waitress
before they are buffered, with its own plain-text 413.

| Status | Meaning |
|--------|---------|
| 400 | No file, empty filename, or unknown `format` |
| 404 | Resource not found or expired |
| 413 | File larger than 10 MB |

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `RESOURCE_SERVER_PORT` | 3100 | Port to listen on (host port under Docker Compose) |
| `RESOURCE_SERVER_HOST` | 0.0.0.0 | Address to bind |
| `RESOURCE_CLEANUP_INTERVAL` | 3600 | Seconds between background cleanups |

The 10 MB limit and 24-hour lifetime are fixed by the spec.

The server runs on [Waitress](https://docs.pylonsproject.org/projects/waitress/) as a
single process, because resources live in that process's memory. Do not run it with
multiple worker processes.

## Docker Compose Commands

| Command | Description |
|---------|-------------|
| `./init.sh start` | Start the server (background) |
| `./init.sh stop` | Stop the server |
| `./init.sh restart` | Restart the server |
| `./init.sh down` | Stop and remove containers |
| `./init.sh rebuild` | Rebuild and start (after code changes) |
| `./init.sh logs` | View live logs |
| `./init.sh status` | Show container status |
| `./init.sh test` | Run the test suite with coverage |

The container runs as a non-root user and has a built-in health check.

## Development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest --cov=main --cov=openapi
```

`./init.sh test` does the same, creating `.venv` if needed. Tests are organized by the
sections of `high_level_spec.md`. `tests/test_skill_doc.py` checks that `SKILL.md` stays in
step with the service, and `tests/test_openapi.py` validates the OpenAPI document and checks
it against the real routes and responses.

To add or change an endpoint, edit its entry in `OPERATIONS` (`openapi.py`) and its view in
`create_app` (`main.py`); the route and the document follow from that one entry.

## Files

| File | Purpose |
|------|---------|
| `main.py` | Flask app: store, endpoint views, cleanup thread, entry point |
| `openapi.py` | Operation list (routes) and the generated OpenAPI document |
| `templates/resources.html` | Resource list web page |
| `tests/` | Test suite |
| `high_level_spec.md` | What the service must do |
| `SKILL.md` | Instructions for AI agents |
| `Dockerfile` | Container configuration |
| `docker-compose.yml` | Docker Compose configuration |
| `init.sh` | Management script |
| `requirements.txt` / `requirements-dev.txt` | Runtime / test dependencies |
