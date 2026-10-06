"""End-to-end checks against a real Waitress server, which the Flask test client bypasses."""

import http.client
import json
import threading
import uuid

import pytest

import main
from main import MAX_FILE_SIZE, SERVER_MAX_BODY


@pytest.fixture(scope="module")
def server():
    srv = main.make_server(main.create_app(), "127.0.0.1", 0)
    thread = threading.Thread(target=srv.run, daemon=True)
    thread.start()
    yield srv.effective_port
    srv.close()


def post_file(port, size, filename="f.bin"):
    boundary = uuid.uuid4().hex
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: application/octet-stream\r\n\r\n"
    ).encode()
    body = head + b"x" * size + f"\r\n--{boundary}--\r\n".encode()
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
    try:
        conn.request("POST", "/upload", body=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        res = conn.getresponse()
        return res.status, res.getheader("Content-Type", ""), res.read()
    except (BrokenPipeError, ConnectionResetError):
        # Waitress may close the connection before the whole body is sent
        return 413, "", b""
    finally:
        conn.close()


def test_upload_at_limit_accepted(server):
    status, _, body = post_file(server, MAX_FILE_SIZE)
    assert status == 201
    assert json.loads(body)["size"] == MAX_FILE_SIZE


def test_moderately_oversized_upload_gets_json_error(server):
    status, content_type, body = post_file(server, MAX_FILE_SIZE * 2)
    assert status == 413
    assert content_type.startswith("application/json")
    assert json.loads(body)["error"] == "File too large: maximum size is 10 MB"


def test_huge_upload_refused_by_server(server):
    status, _, _ = post_file(server, SERVER_MAX_BODY + 1)
    assert status == 413


def test_health(server):
    conn = http.client.HTTPConnection("127.0.0.1", server, timeout=5)
    conn.request("GET", "/health")
    res = conn.getresponse()
    assert res.status == 200
    assert json.loads(res.read())["status"] == "healthy"
    conn.close()
