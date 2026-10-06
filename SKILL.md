---
name: resources-server
description: Publish a file or generated content (HTML page, report, JSON, text, PDF) as a temporary link that people on the local network can open in a browser. Use when the user wants to view, share, or preview something you produced, update a link you already shared, or check or manage the resource server.
metadata:
  clawdbot:
    emoji: "📦"
    requires:
      bins: [curl, python3]
---

# Resources Server

Temporary file sharing on the local network. Upload content, get a short ID, and hand the
user a link they can open in any browser on the network. The server lives in
`~/resources_server` and listens on port 3100.

## When to Use

- You generated a page, report, chart, or document and the user should open it in a browser
- The user asks for a link to a file, or to "share", "publish", or "preview" something
- You are iterating on content the user is already viewing: replace it under the same link

## When Not to Use

- Sensitive content (credentials, personal data): anyone on the network can open and
  overwrite any resource
- Files over 10 MB
- Anything that must last more than 24 hours or survive a restart
- Anything the user may want removed early: resources cannot be deleted, only replaced or
  left to expire

## Rules

| Rule | Value |
|------|-------|
| Max file size | 10 MB per file, for uploads and replacements |
| Lifetime | 24 hours after upload or last replacement |
| Storage | RAM only: everything is lost when the server restarts |
| Access | Open by design: no authentication, anyone can overwrite any resource |

## Publish Content (main workflow)

```bash
cd ~/resources_server
PORT=3100

# 1. Make sure the server is up (start it and wait if not)
if ! curl -fsS "http://localhost:$PORT/api/health" >/dev/null 2>&1; then
  ./init.sh start
  for i in $(seq 30); do curl -fsS "http://localhost:$PORT/api/health" >/dev/null 2>&1 && break; sleep 1; done
fi

# 2. Upload, and fail loudly on any error
RESP=$(curl -sS -w '\n%{http_code}' -X POST \
  -F "file=@/path/to/report.html" -F "format=html" \
  "http://localhost:$PORT/api/upload")
CODE=$(printf '%s' "$RESP" | tail -n1); BODY=$(printf '%s' "$RESP" | sed '$d')
[ "$CODE" = 201 ] || { echo "Upload failed ($CODE): $BODY"; exit 1; }
ID=$(printf '%s' "$BODY" | python3 -c 'import sys, json; print(json.load(sys.stdin)["id"])')

# 3. Build a link that works from other machines (not localhost)
IP=$(hostname -I | awk '{print $1}')
echo "http://$IP:$PORT/api/resource/$ID"
```

4. Give the user the network link and say it expires in 24 hours.
5. **Remember the ID.** If the user asks for changes, replace the content under the same ID
   so their link keeps working. Don't upload a new copy.

### Generated content without a file

Pipe it in and give it a filename. The filename's extension helps browsers.

```bash
printf '%s' "$HTML" | curl -sS -X POST -F "file=@-;filename=report.html" -F "format=html" \
  http://localhost:3100/api/upload
```

### Choosing `format`

| Content | `format` | Shown as |
|---------|----------|----------|
| Web page | `html` | Rendered page |
| Structured data | `json` | JSON |
| Plain text, logs, Markdown | `text` | Plain text |
| PDF | `pdf` | PDF document |
| Anything else (images, archives) | omit it | The type curl sends, e.g. `image/png` |

`format` is optional and takes priority over the type curl sends. Any other value is
rejected with `400`.

### Writing HTML that works here

Pages are served inside a browser sandbox: scripts run, but the page gets an isolated origin.
- Make pages **self-contained**: inline CSS, JS, and images (data URIs), or load them from
  public CDNs.
- Don't rely on `localStorage`, `sessionStorage`, or cookies. They are unavailable in the
  sandbox.
- Don't link to other resources by filename. Link to their full `/api/resource/{id}` URL.

## Update Content (same link)

Replacing restarts the 24-hour lifetime. It works only while the resource is live: after
expiry you get `404`, so upload again and give the user the new link.

```bash
curl -sS -X PUT -F "file=@/path/to/report.html" -F "format=html" \
  http://localhost:3100/api/resource/{id}
```

Open access means anyone can replace any resource, including ones you uploaded. If content
looks wrong, someone may have replaced it.

## Browse and Check

```bash
curl -sS http://localhost:3100/api/resources      # JSON: all live resources, with expiry times
curl -sS http://localhost:3100/api/health         # {"status": "healthy", "resources_count": N, "uptime_seconds": S}
curl -sS http://localhost:3100/api/resource/{id}  # Download a resource's content
```

People can browse everything at `http://<IP>:3100/`, which shows the list as a web page.

## Full API Description

Every endpoint, parameter, response, and limit is described by the OpenAPI document:

```bash
curl -sS http://localhost:3100/api/openapi.json
```

It is generated from the server's code, so it is always current. Read it when you need a
detail this guide doesn't cover. Older addresses without `/api` (from links shared earlier)
still work, but always use the `/api` addresses.

## Responses

Upload (`201`) and replace (`200`) both return:

```json
{
  "id": "a1b2c3d4",
  "filename": "report.html",
  "content_type": "text/html",
  "size": 15,
  "created_at": "2026-10-06T12:00:00+00:00",
  "expires_at": "2026-10-07T12:00:00+00:00",
  "url": "/api/resource/a1b2c3d4",
  "link": "http://localhost:3100/api/resource/a1b2c3d4"
}
```

- `link` uses the host you called. With `localhost` it only works on this machine, so build
  the network link yourself (step 3 above).
- Times are UTC.
- `filename` may differ from what you sent. Paths and control characters are removed, and
  names are cut to 255 characters.

## Errors

| Status | Meaning | What to do |
|--------|---------|------------|
| `400` | No file, empty filename, or unknown `format` | Fix the request |
| `404` | Resource not found or expired | Upload again and share the new link |
| `413` | File larger than 10 MB | Shrink or split it, or tell the user it can't be shared this way |
| No response | Server not running | `./init.sh start`, then retry |

Error bodies are JSON (`{"error": "..."}`), except uploads above 40 MB, which are refused
with a plain-text `413` before they are read. Check the status code, not the body.

## Server Management

Run from `~/resources_server`.

| Command | Action | Keeps resources? |
|---------|--------|------------------|
| `./init.sh start` | Start the server | Yes |
| `./init.sh status` | Show container status | Yes |
| `./init.sh logs` | Follow logs (Ctrl+C to exit) | Yes |
| `./init.sh test` | Run the test suite | Yes |
| `./init.sh stop` | Stop the server | **No** |
| `./init.sh restart` | Restart the server | **No** |
| `./init.sh down` | Stop and remove the container | **No** |
| `./init.sh rebuild` | Rebuild and start after code changes | **No** |

**Ask the user before running any command that doesn't keep resources.** It breaks every
link that has been shared.

## Troubleshooting

```bash
./init.sh status                    # Is the container up and healthy?
./init.sh logs                      # Recent errors
sudo lsof -i :3100                  # Something else holding the port?
./init.sh down && ./init.sh start   # Full reset (discards all resources; ask first)
```
