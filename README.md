# Resource Server

In-memory REST API for temporarily sharing files, with automatic expiration.
Behavior is defined in [high_level_spec.md](high_level_spec.md). AI agents use the
server through [SKILL.md](SKILL.md), specified by [agent_skill.md](agent_skill.md).

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

Read that document for parameters, responses, and errors; this README doesn't repeat it.

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
.venv/bin/python -m pytest
```

`./init.sh test` does the same, creating `.venv` if needed. Coverage of `main.py` and
`openapi.py` must be 100% of lines and branches (`.coveragerc`), or the run fails. The
Docker build runs the same suite in its `test` stage, so `./init.sh rebuild` fails too. Tests are organized by the
sections of `high_level_spec.md`. `tests/test_skill_doc.py` checks that `SKILL.md` stays in
step with the service, as `agent_skill.md` requires, and `tests/test_openapi.py` validates the OpenAPI document and checks
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
| `agent_skill.md` | What the agent skill must do |
| `SKILL.md` | Instructions for AI agents |
| `Dockerfile` | Container configuration, with a `test` stage that gates the build |
| `.coveragerc` | Coverage settings, including the 100% gate |
| `docker-compose.yml` | Docker Compose configuration |
| `init.sh` | Management script |
| `requirements.txt` / `requirements-dev.txt` | Runtime / test dependencies |
