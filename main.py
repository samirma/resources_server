#!/usr/bin/env python3
"""
In-Memory Resource Server
Simple REST API for storing and retrieving resources in RAM
"""

import uuid
import threading
import time
import os
from datetime import datetime, timedelta
from flask import Flask, request, send_file, jsonify, make_response
from io import BytesIO

app = Flask(__name__)

# In-memory storage: {id: {"data": bytes, "content_type": str, "created_at": timestamp}}
resources = {}
resources_lock = threading.Lock()
cleanup_interval = 3600  # Check for expired resources every hour
resource_ttl = 86400  # 24 hours in seconds

def cleanup_expired_resources():
    """Background task to remove resources older than 24 hours"""
    while True:
        time.sleep(cleanup_interval)
        now = time.time()
        with resources_lock:
            expired_ids = [
                rid for rid, data in resources.items()
                if now - data["created_at"] > resource_ttl
            ]
            for rid in expired_ids:
                del resources[rid]
                print(f"🗑️ Cleaned up expired resource: {rid}")

# Start cleanup thread
cleanup_thread = threading.Thread(target=cleanup_expired_resources, daemon=True)
cleanup_thread.start()

@app.route('/upload', methods=['POST'])
def upload():
    """Upload a resource with optional format hint"""
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Empty filename"}), 400
    
    # Get format hint from form data
    format_hint = request.form.get('format', '')
    
    # Generate unique ID
    resource_id = str(uuid.uuid4())[:8]
    
    # Read file data into memory
    file_data = file.read()
    
    # Determine content type
    content_type = file.content_type
    if not content_type or content_type == 'application/octet-stream':
        if format_hint == 'html':
            content_type = 'text/html'
        elif format_hint == 'json':
            content_type = 'application/json'
        elif format_hint == 'text':
            content_type = 'text/plain'
        elif format_hint == 'pdf':
            content_type = 'application/pdf'
        else:
            content_type = 'application/octet-stream'
    
    # Store in memory
    with resources_lock:
        resources[resource_id] = {
            "data": file_data,
            "content_type": content_type,
            "filename": file.filename,
            "format_hint": format_hint,
            "created_at": time.time(),
            "size": len(file_data)
        }
    
    print(f"✅ Uploaded resource: {resource_id} ({len(file_data)} bytes)")
    
    return jsonify({
        "id": resource_id,
        "filename": file.filename,
        "content_type": content_type,
        "size": len(file_data),
        "created_at": datetime.now().isoformat(),
        "url": f"/resource/{resource_id}"
    }), 201

@app.route('/resource/<resource_id>', methods=['GET'])
def get_resource(resource_id):
    """Retrieve a resource by ID"""
    with resources_lock:
        if resource_id not in resources:
            return jsonify({"error": "Resource not found"}), 404
        
        resource = resources[resource_id]
        
        # Check if expired
        if time.time() - resource["created_at"] > resource_ttl:
            del resources[resource_id]
            return jsonify({"error": "Resource expired"}), 404
        
        # Make a copy of the data to return
        data_copy = resource["data"]
        content_type = resource["content_type"]
        filename = resource.get("filename", "")
        created_at = resource["created_at"]
    
    # Return binary data
    response = make_response(data_copy)
    response.headers["Content-Type"] = content_type
    response.headers["X-Resource-ID"] = resource_id
    response.headers["X-Created-At"] = datetime.fromtimestamp(created_at).isoformat()
    
    # Set filename if it's a download
    if filename:
        response.headers["Content-Disposition"] = f'inline; filename="{filename}"'
    
    print(f"📤 Served resource: {resource_id} ({len(data_copy)} bytes)")
    return response

@app.route('/resource/<resource_id>', methods=['PUT'])
def update_resource(resource_id):
    """Update an existing resource"""
    with resources_lock:
        if resource_id not in resources:
            return jsonify({"error": "Resource not found"}), 404
    
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400
    
    file = request.files['file']
    format_hint = request.form.get('format', '')
    
    # Read new data
    file_data = file.read()
    
    # Determine content type
    content_type = file.content_type
    if not content_type or content_type == 'application/octet-stream':
        if format_hint == 'html':
            content_type = 'text/html'
        elif format_hint == 'json':
            content_type = 'application/json'
        elif format_hint == 'text':
            content_type = 'text/plain'
        else:
            content_type = 'application/octet-stream'
    
    # Update resource
    with resources_lock:
        resources[resource_id] = {
            "data": file_data,
            "content_type": content_type,
            "filename": file.filename,
            "format_hint": format_hint,
            "created_at": time.time(),  # Reset timestamp on update
            "size": len(file_data)
        }
    
    print(f"📝 Updated resource: {resource_id} ({len(file_data)} bytes)")
    
    return jsonify({
        "id": resource_id,
        "filename": file.filename,
        "content_type": content_type,
        "size": len(file_data),
        "updated_at": datetime.now().isoformat()
    }), 200

@app.route('/resources', methods=['GET'])
def list_resources():
    """List all resources with metadata and expiration dates (HTML or JSON)"""
    now = time.time()
    accept_header = request.headers.get('Accept', '')
    
    with resources_lock:
        result = []
        for rid, data in resources.items():
            if now - data["created_at"] <= resource_ttl:
                expires_at = data["created_at"] + resource_ttl
                result.append({
                    "id": rid,
                    "filename": data["filename"],
                    "content_type": data["content_type"],
                    "size": data["size"],
                    "created_at": data["created_at"],
                    "expires_at": expires_at,
                    "time_remaining": expires_at - now
                })
    
    # Return HTML if browser requests it
    if 'text/html' in accept_header or 'application/xhtml' in accept_header:
        html = generate_resources_html(result, len(result))
        return make_response(html, 200, {'Content-Type': 'text/html'})
    
    # Otherwise return JSON
    json_result = []
    for r in result:
        json_result.append({
            "id": r["id"],
            "filename": r["filename"],
            "content_type": r["content_type"],
            "size": r["size"],
            "created_at": datetime.fromtimestamp(r["created_at"]).isoformat(),
            "expires_at": datetime.fromtimestamp(r["expires_at"]).isoformat(),
            "ttl_seconds": int(resource_ttl),
            "time_remaining_seconds": int(r["time_remaining"])
        })
    return jsonify({
        "resources": json_result,
        "count": len(json_result),
        "ttl_hours": int(resource_ttl / 3600)
    })

def generate_resources_html(resources, count):
    """Generate HTML page for resources list"""
    rows = []
    for r in resources:
        expires_class = "expires"
        if r["time_remaining"] < 3600:  # Less than 1 hour
            expires_class = "expires-soon"
        
        # Determine badge class
        content_type = r["content_type"]
        if "html" in content_type:
            badge_class = "badge-html"
            badge_text = "HTML"
        elif "json" in content_type:
            badge_class = "badge-json"
            badge_text = "JSON"
        elif "text" in content_type:
            badge_class = "badge-text"
            badge_text = "TEXT"
        elif "pdf" in content_type:
            badge_class = "badge-pdf"
            badge_text = "PDF"
        else:
            badge_class = "badge-other"
            badge_text = "OTHER"
        
        rows.append(f"""<tr>
            <td><span class="resource-id">{r['id']}</span></td>
            <td><span class="filename">{r['filename']}</span></td>
            <td><span class="badge {badge_class}">{badge_text}</span></td>
            <td><span class="size">{r['size']:,} bytes</span></td>
            <td><span class="datetime">{datetime.fromtimestamp(r['created_at']).strftime('%Y-%m-%d %H:%M:%S')}</span></td>
            <td><span class="{expires_class}">{datetime.fromtimestamp(r['expires_at']).strftime('%Y-%m-%d %H:%M:%S')}</span></td>
            <td><a href="/resource/{r['id']}" class="view-link">View</a></td>
        </tr>""")
    
    rows_html = ''.join(rows) if rows else '''<tr><td colspan="7" class="empty-state"><h2>No resources available</h2><p>Upload files using POST /upload</p></td></tr>'''
    
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Resource Server - Available Resources</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
            color: #eee;
            min-height: 100vh;
            padding: 40px 20px;
        }}
        .container {{ max-width: 1200px; margin: 0 auto; }}
        header {{
            text-align: center;
            margin-bottom: 40px;
            padding: 30px;
            background: rgba(255,255,255,0.05);
            border-radius: 15px;
            border: 1px solid rgba(255,255,255,0.1);
        }}
        h1 {{
            color: #00ff88;
            font-size: 2.5em;
            margin-bottom: 10px;
        }}
        .subtitle {{ color: #888; font-size: 1.1em; }}
        .stats {{
            display: flex;
            justify-content: center;
            gap: 40px;
            margin-top: 20px;
        }}
        .stat {{
            text-align: center;
        }}
        .stat-value {{
            font-size: 2em;
            font-weight: bold;
            color: #f7931a;
        }}
        .stat-label {{
            color: #888;
            font-size: 0.9em;
            text-transform: uppercase;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            background: rgba(255,255,255,0.05);
            border-radius: 15px;
            overflow: hidden;
            border: 1px solid rgba(255,255,255,0.1);
        }}
        th {{
            background: rgba(0,255,136,0.2);
            color: #00ff88;
            padding: 15px;
            text-align: left;
            font-weight: bold;
            text-transform: uppercase;
            font-size: 0.85em;
            letter-spacing: 1px;
        }}
        td {{
            padding: 15px;
            border-bottom: 1px solid rgba(255,255,255,0.05);
            color: #ccc;
        }}
        tr:hover {{
            background: rgba(255,255,255,0.05);
        }}
        tr:last-child td {{ border-bottom: none; }}
        .resource-id {{
            font-family: monospace;
            color: #f7931a;
            font-weight: bold;
        }}
        .filename {{
            color: #fff;
            font-weight: 500;
        }}
        .size {{
            font-family: monospace;
            color: #00ff88;
        }}
        .content-type {{
            color: #888;
            font-size: 0.9em;
        }}
        .datetime {{
            font-family: monospace;
            color: #ccc;
            font-size: 0.9em;
        }}
        .expires {{
            color: #ff4757;
            font-weight: bold;
        }}
        .expires-soon {{
            color: #ffa502;
        }}
        .view-link {{
            display: inline-block;
            padding: 8px 16px;
            background: rgba(0,255,136,0.2);
            color: #00ff88;
            text-decoration: none;
            border-radius: 5px;
            font-size: 0.85em;
            transition: all 0.3s;
        }}
        .view-link:hover {{
            background: rgba(0,255,136,0.3);
        }}
        .empty-state {{
            text-align: center;
            padding: 60px;
            color: #888;
        }}
        .empty-state h2 {{
            color: #666;
            margin-bottom: 10px;
        }}
        footer {{
            text-align: center;
            margin-top: 40px;
            padding: 20px;
            color: #666;
            font-size: 0.9em;
        }}
        .badge {{
            display: inline-block;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 0.75em;
            font-weight: bold;
            text-transform: uppercase;
        }}
        .badge-html {{ background: rgba(227, 79, 38, 0.3); color: #e34f26; }}
        .badge-json {{ background: rgba(168, 196, 30, 0.3); color: #a8c41e; }}
        .badge-text {{ background: rgba(200, 200, 200, 0.3); color: #ccc; }}
        .badge-pdf {{ background: rgba(222, 82, 70, 0.3); color: #de5246; }}
        .badge-other {{ background: rgba(100, 100, 100, 0.3); color: #888; }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>📦 Resource Server</h1>
            <div class="subtitle">In-Memory Storage with Auto-Cleanup</div>
            <div class="stats">
                <div class="stat">
                    <div class="stat-value">{count}</div>
                    <div class="stat-label">Active Resources</div>
                </div>
                <div class="stat">
                    <div class="stat-value">24h</div>
                    <div class="stat-label">TTL</div>
                </div>
            </div>
        </header>
        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Filename</th>
                    <th>Type</th>
                    <th>Size</th>
                    <th>Created</th>
                    <th>Expires</th>
                    <th>Action</th>
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
        <footer>
            <p>Resource Server | In-Memory Storage | Auto-cleanup after 24h</p>
        </footer>
    </div>
</body>
</html>"""

@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint"""
    with resources_lock:
        count = len(resources)
    return jsonify({
        "status": "healthy",
        "resources_count": count,
        "uptime": "running"
    })

if __name__ == '__main__':
    import socket
    from werkzeug.serving import WSGIRequestHandler
    
    # Allow socket reuse to avoid "Address already in use" errors
    WSGIRequestHandler.protocol_version = "HTTP/1.1"
    
    PORT = int(os.environ.get('RESOURCE_SERVER_PORT', 3100))
    
    print(f"🚀 Resource Server starting on port {PORT}...")
    app.run(host='0.0.0.0', port=PORT, debug=False, threaded=True, use_reloader=False)
