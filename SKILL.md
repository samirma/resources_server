---
name: resources-server
description: Publish a file or generated content (HTML page, report, JSON, text, PDF) as a temporary link that people on the local network can open in a browser. Use when the user wants to view, share, or preview something you produced, update a link you already shared, or check or manage the resource server.
metadata:
  clawdbot:
    emoji: "📦"
    requires:
      bins: [curl]
---

# Resources Server

Temporary file sharing on the local network. Upload content, get a short ID, and hand the
user a link they can open in any browser on the network. Everything below needs only a
POSIX shell and `curl`.

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

## Find the Server

Run this first. It sets `BASE` to the first address that answers: the one the user gave
(put it in `RESOURCES_SERVER_URL`), the one cached by an earlier run, then the home server's
known addresses.

```bash
CACHE="${XDG_CACHE_HOME:-$HOME/.cache}/resources-server"
BASE=""
for url in "$RESOURCES_SERVER_URL" "$(cat "$CACHE/base_url" 2>/dev/null)" \
           http://raspberry-server.local:3100 http://192.168.0.2:3100; do
  [ -n "$url" ] && curl -fsS -m 3 "$url/api/health" >/dev/null 2>&1 && { BASE=$url; break; }
done
[ -n "$BASE" ] || { echo "Resource server not found"; exit 1; }
mkdir -p "$CACHE" && printf '%s\n' "$BASE" > "$CACHE/base_url"
```

If nothing answers, ask the user for the server's address. If you are on the machine that
runs it, start it instead (see Server Management) and run this again.

## Publish Content (main workflow)

```bash
RESP=$(curl -sS -w '\n%{http_code}' -X POST \
  -F "file=@/path/to/report.html" -F "format=html" "$BASE/api/upload")
CODE=$(printf '%s' "$RESP" | tail -n1); BODY=$(printf '%s' "$RESP" | sed '$d')
[ "$CODE" = 201 ] || { echo "Upload failed ($CODE): $BODY"; exit 1; }
ID=$(printf '%s' "$BODY" | sed -n 's/.*"id": *"\([^"]*\)".*/\1/p')
LINK=$(printf '%s' "$BODY" | sed -n 's/.*"link": *"\([^"]*\)".*/\1/p')
echo "$LINK"
```

1. Give the user `LINK` and say it expires in 24 hours. It uses the address you called,
   so it works for everyone on the network.
2. **Remember the ID.** If the user asks for changes, replace the content under the same ID
   so their link keeps working. Don't upload a new copy.

### Generated content without a file

Pipe it in and give it a filename. The filename's extension helps browsers.

```bash
printf '%s' "$HTML" | curl -sS -X POST -F "file=@-;filename=report.html" -F "format=html" \
  "$BASE/api/upload"
```

### Choosing `format`

| Content | `format` | Shown as |
|---------|----------|----------|
| Web page | `html` | Rendered page |
| Structured data | `json` | JSON |
| Plain text, logs, Markdown | `text` | Plain text |
| PDF | `pdf` | PDF document |
| Anything else (images, archives) | omit it | The type curl sends, e.g. `image/png` |

### Writing HTML that works here

Pages are served inside a browser sandbox: scripts run, but the page gets an isolated origin.
- Make pages **self-contained**: inline CSS, JS, and images (data URIs), or load them from
  public CDNs.
- Don't rely on `localStorage`, `sessionStorage`, or cookies. They are unavailable in the
  sandbox.
- Don't link to other resources by filename. Link to their full `/api/resource/{id}` URL.

## Update Content (same link)

Replacing restarts the 24-hour lifetime. It works only while the resource is live.

```bash
curl -sS -X PUT -F "file=@/path/to/report.html" -F "format=html" "$BASE/api/resource/{id}"
```

Open access means anyone can replace any resource, including ones you uploaded. If content
looks wrong, someone may have replaced it.

## Browse and Check

```bash
curl -sS "$BASE/api/resources"      # All live resources, with expiry times
curl -sS "$BASE/api/health"         # Is it up, and how many resources it holds
curl -sS "$BASE/api/resource/{id}"  # A resource's content
```

People can browse everything at `$BASE/`, which shows the list as a web page.

## Full API Description

The OpenAPI document is the authoritative description of every endpoint, parameter,
response, error, and limit. It is generated from the server's code, so it is always current.
Read it for any detail this skill doesn't cover:

```bash
curl -sS "$BASE/api/openapi.json"
```

## When a Call Fails

| Result | What to do |
|--------|------------|
| `400` | Fix the request; the error message says what is wrong |
| `404` | The resource expired or never existed: upload again and share the new link |
| `413` | Over 10 MB: shrink or split it, or tell the user it can't be shared this way |
| No answer | Run Find the Server again; if it is still down, see Server Management |

## Server Management

Only on the machine that runs the server, from the project checkout (the folder with
`init.sh`).

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
