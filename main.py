#!/usr/bin/env python3
"""
In-Memory Resource Server
Simple REST API for temporarily storing and sharing files in RAM.

Behavior is defined by high_level_spec.md. Access is intentionally open:
there is no authentication and anyone can replace any resource.

Endpoints live under /api and come from openapi.OPERATIONS, which also generates the
OpenAPI document at /api/openapi.json.
"""

import logging
import os
import secrets
import threading
import time
from datetime import datetime, timezone
from io import BytesIO

from flask import Flask, jsonify, redirect, render_template, request, send_file, url_for
from werkzeug.exceptions import RequestEntityTooLarge

from openapi import API_PREFIX, OPERATIONS, build_document

logger = logging.getLogger("resource_server")

MB = 1024 * 1024
RESOURCE_TTL = 24 * 3600  # Resources live 24 hours after upload or last replacement
MAX_FILE_SIZE = 10 * MB  # Largest file accepted, inclusive
MULTIPART_OVERHEAD = MB  # Room for form fields and boundaries around the file itself
MAX_FILENAME_LENGTH = 255
# Waitress buffers a whole request body before the app sees it. Bodies past this cap are
# refused up front (with Waitress's own plain-text 413); smaller oversized uploads reach
# the app and get the JSON error.
SERVER_MAX_BODY = 4 * MAX_FILE_SIZE
EXPIRING_SOON = 3600  # Highlight resources with less than an hour left
DEFAULT_CLEANUP_INTERVAL = 3600

FORMAT_CONTENT_TYPES = {
    "html": "text/html",
    "json": "application/json",
    "text": "text/plain",
    "pdf": "application/pdf",
}
DEFAULT_CONTENT_TYPE = "application/octet-stream"

# Uploaded pages still render and run scripts, but in an opaque origin, so they
# cannot read or script the listing page or call the API as the server's origin.
RESOURCE_CSP = "sandbox allow-scripts allow-forms allow-popups allow-modals allow-downloads"


def format_size(num_bytes):
    if num_bytes % MB == 0:
        return f"{num_bytes // MB} MB"
    return f"{num_bytes:,} bytes"


def format_duration(seconds):
    if seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def to_iso(timestamp):
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


class ResourceStore:
    """Thread-safe in-memory store. Records are replaced, never mutated in place."""

    def __init__(self, ttl=RESOURCE_TTL, clock=time.time):
        self.ttl = ttl
        self.clock = clock
        self._resources = {}
        self._lock = threading.Lock()

    def _is_expired(self, resource, now):
        return now - resource["created_at"] >= self.ttl

    def _new_id(self):
        while True:
            resource_id = secrets.token_hex(4)
            if resource_id not in self._resources:
                return resource_id

    def _record(self, resource_id, data, filename, content_type):
        created_at = self.clock()
        return {
            "id": resource_id,
            "data": data,
            "filename": filename,
            "content_type": content_type,
            "size": len(data),
            "created_at": created_at,
            "expires_at": created_at + self.ttl,
            # New on every write, so a replacement is never mistaken for a cached copy
            "etag": secrets.token_hex(8),
        }

    def add(self, data, filename, content_type):
        with self._lock:
            resource_id = self._new_id()
            record = self._record(resource_id, data, filename, content_type)
            self._resources[resource_id] = record
        return record

    def replace(self, resource_id, data, filename, content_type):
        """Replace a live resource and restart its lifetime. Returns None if missing or expired."""
        with self._lock:
            current = self._resources.get(resource_id)
            if current is None:
                return None
            if self._is_expired(current, self.clock()):
                del self._resources[resource_id]
                return None
            record = self._record(resource_id, data, filename, content_type)
            self._resources[resource_id] = record
        return record

    def get(self, resource_id):
        with self._lock:
            resource = self._resources.get(resource_id)
            if resource is None:
                return None
            if self._is_expired(resource, self.clock()):
                del self._resources[resource_id]
                return None
        return resource

    def list(self):
        now = self.clock()
        with self._lock:
            live = [r for r in self._resources.values() if not self._is_expired(r, now)]
        return sorted(live, key=lambda r: r["created_at"])

    def count(self):
        return len(self.list())

    def purge_expired(self):
        now = self.clock()
        with self._lock:
            expired_ids = [rid for rid, r in self._resources.items() if self._is_expired(r, now)]
            for rid in expired_ids:
                del self._resources[rid]
        return expired_ids


def start_cleanup_thread(store, interval):
    """Background task that removes expired resources every `interval` seconds.
    Returns an event that stops the task when set."""
    stop = threading.Event()

    def run():
        while not stop.wait(interval):
            for rid in store.purge_expired():
                logger.info("Cleaned up expired resource: %s", rid)

    threading.Thread(target=run, name="resource-cleanup", daemon=True).start()
    return stop


def clean_filename(filename):
    """Keep only the base name, drop control characters (invalid in headers) and cap the
    length, keeping a short extension so the file still opens correctly"""
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    name = "".join(ch for ch in base if ch.isprintable()).strip()
    if len(name) <= MAX_FILENAME_LENGTH:
        return name
    stem, ext = os.path.splitext(name)
    if len(ext) > 16:
        ext = ""
    return stem[:MAX_FILENAME_LENGTH - len(ext)] + ext


def resolve_content_type(client_type, format_hint):
    """An explicit format hint wins; otherwise trust the client's type unless it is generic"""
    if format_hint:
        return FORMAT_CONTENT_TYPES[format_hint]
    if client_type and client_type != DEFAULT_CONTENT_TYPE:
        return client_type
    return DEFAULT_CONTENT_TYPE


def badge_for(content_type):
    for key, label in (("html", "HTML"), ("json", "JSON"), ("pdf", "PDF"), ("text", "TEXT")):
        if key in content_type:
            return key, label
    return "other", "OTHER"


def create_app(store=None):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE + MULTIPART_OVERHEAD
    store = store or ResourceStore()
    app.extensions["resource_store"] = store
    started_at = time.time()

    def error(message, status):
        return jsonify({"error": message}), status

    def too_large():
        return error(f"File too large: maximum size is {format_size(MAX_FILE_SIZE)}", 413)

    @app.errorhandler(RequestEntityTooLarge)
    def handle_too_large(_exc):
        return too_large()

    def read_upload():
        """Validate the multipart upload. Returns (fields, None) or (None, error_response)."""
        file = request.files.get("file")
        if file is None:
            return None, error("No file provided", 400)
        filename = clean_filename(file.filename or "")
        if not filename:
            return None, error("Empty filename", 400)

        format_hint = request.form.get("format", "").strip().lower()
        if format_hint and format_hint not in FORMAT_CONTENT_TYPES:
            allowed = ", ".join(FORMAT_CONTENT_TYPES)
            return None, error(f"Unknown format '{format_hint}': use one of {allowed}", 400)

        data = file.stream.read(MAX_FILE_SIZE + 1)
        if len(data) > MAX_FILE_SIZE:
            return None, too_large()

        content_type = resolve_content_type(file.mimetype, format_hint)
        return {"data": data, "filename": filename, "content_type": content_type}, None

    def describe(record):
        return {
            "id": record["id"],
            "filename": record["filename"],
            "content_type": record["content_type"],
            "size": record["size"],
            "created_at": to_iso(record["created_at"]),
            "expires_at": to_iso(record["expires_at"]),
            "url": url_for("get_resource", resource_id=record["id"]),
            "link": url_for("get_resource", resource_id=record["id"], _external=True),
        }

    @app.route("/", methods=["GET"])
    def root():
        """Redirect root to /resources"""
        return redirect(url_for("list_resources"), code=302)

    def upload():
        """Upload a resource with optional format hint"""
        fields, failure = read_upload()
        if failure:
            return failure
        record = store.add(**fields)
        logger.info("Uploaded resource: %s (%d bytes)", record["id"], record["size"])
        return jsonify(describe(record)), 201

    def get_resource(resource_id):
        """Retrieve a resource by ID"""
        record = store.get(resource_id)
        if record is None:
            return error("Resource not found", 404)

        response = send_file(
            BytesIO(record["data"]),
            mimetype=record["content_type"],
            download_name=record["filename"],
            etag=record["etag"],
            max_age=0,
        )
        response.headers["X-Resource-ID"] = record["id"]
        response.headers["X-Created-At"] = to_iso(record["created_at"])
        response.headers["X-Expires-At"] = to_iso(record["expires_at"])
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = RESOURCE_CSP
        logger.info("Served resource: %s (%d bytes)", record["id"], record["size"])
        return response

    def update_resource(resource_id):
        """Replace an existing resource. Open to anyone by design."""
        fields, failure = read_upload()
        if failure:
            return failure
        record = store.replace(resource_id, **fields)
        if record is None:
            return error("Resource not found", 404)
        logger.info("Updated resource: %s (%d bytes)", record["id"], record["size"])
        body = describe(record)
        body["updated_at"] = body["created_at"]
        return jsonify(body), 200

    def list_resources():
        """List all live resources as an HTML page for browsers or JSON for tools"""
        now = store.clock()
        records = store.list()

        best = request.accept_mimetypes.best_match(["application/json", "text/html"])
        if best == "text/html":
            rows = []
            for r in records:
                badge_class, badge_label = badge_for(r["content_type"])
                rows.append({
                    "id": r["id"],
                    "filename": r["filename"],
                    "badge_class": badge_class,
                    "badge_label": badge_label,
                    "size": f"{r['size']:,} bytes",
                    "created_at": datetime.fromtimestamp(r["created_at"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "expires_at": datetime.fromtimestamp(r["expires_at"], tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                    "expiring_soon": r["expires_at"] - now < EXPIRING_SOON,
                    "url": url_for("get_resource", resource_id=r["id"]),
                })
            return render_template(
                "resources.html",
                resources=rows,
                count=len(rows),
                ttl_label=format_duration(store.ttl),
                max_size_label=format_size(MAX_FILE_SIZE),
            )

        items = []
        for r in records:
            item = describe(r)
            item["ttl_seconds"] = int(store.ttl)
            item["time_remaining_seconds"] = int(r["expires_at"] - now)
            items.append(item)
        return jsonify({
            "resources": items,
            "count": len(items),
            "ttl_hours": int(store.ttl / 3600),
            "max_file_size_bytes": MAX_FILE_SIZE,
        })

    def health():
        """Health check endpoint"""
        return jsonify({
            "status": "healthy",
            "resources_count": store.count(),
            "uptime_seconds": int(time.time() - started_at),
        })

    def openapi():
        """The OpenAPI document, generated from OPERATIONS"""
        return jsonify(build_document(
            request.url_root.rstrip("/"),
            max_file_size=MAX_FILE_SIZE,
            ttl_seconds=int(store.ttl),
            formats=FORMAT_CONTENT_TYPES,
        ))

    views = {
        "upload": upload,
        "get_resource": get_resource,
        "update_resource": update_resource,
        "list_resources": list_resources,
        "health": health,
        "openapi": openapi,
    }
    for op in OPERATIONS:
        view = views[op.endpoint]
        app.add_url_rule(API_PREFIX + op.path, op.endpoint, view, methods=[op.method])
        if op.legacy_path:
            app.add_url_rule(op.legacy_path, f"legacy_{op.endpoint}", view, methods=[op.method])

    return app


def make_server(app, host, port):
    from waitress import create_server

    # Single process on purpose: resources live in this process's memory
    return create_server(app, host=host, port=port, threads=8, max_request_body_size=SERVER_MAX_BODY)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    host = os.environ.get("RESOURCE_SERVER_HOST", "0.0.0.0")
    port = int(os.environ.get("RESOURCE_SERVER_PORT", 3100))
    cleanup_interval = int(os.environ.get("RESOURCE_CLEANUP_INTERVAL", DEFAULT_CLEANUP_INTERVAL))

    app = create_app()
    start_cleanup_thread(app.extensions["resource_store"], cleanup_interval)

    server = make_server(app, host, port)
    logger.info("Resource Server starting on %s:%d", host, port)
    server.run()


if __name__ == "__main__":
    main()
