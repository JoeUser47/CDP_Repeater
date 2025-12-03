import asyncio
import json
import threading
import http.server
import socketserver
import urllib.request
import urllib.error
import websockets
import os
import platform
import subprocess
import time
import uuid

# --- Configuration ---
HTTP_PORT = 9999
WEBSOCKET_PORT = 8765
CHROME_DEBUG_PORT = 9222
USER_DATA_DIR_NAME = "ChromeRepeaterSession"

# --- Global State Management ---
request_history, request_order = {}, []
HISTORY_LIMIT = 500
ui_websocket_connection = None
browser_user_agent = None
MONITORED_SESSION_ID = None
ui_ready = asyncio.Event()
CDP_COMMAND_ID = 1000
pending_futures = {}
cdp_id_to_req_id = {}
network_id_to_fetch_id = {}
cdp_command_queue = asyncio.Queue()
ui_message_queue = asyncio.Queue() # New decoupled queue for UI updates

# --- Part 1: Self-Contained UI and Help Files ---
HELP_HTML_CONTENT = """
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>CDP Repeater - Help</title><style>body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #333; max-width: 800px; margin: 0 auto; padding: 20px; background-color: #f8f9fa; } h1, h2 { border-bottom: 2px solid #dee2e6; padding-bottom: 10px; color: #212529; } h1 { font-size: 2.5em; } h2 { font-size: 1.75em; margin-top: 40px;} code { font-family: "Courier New", Courier, monospace; background-color: #e9ecef; padding: 2px 6px; border-radius: 4px; font-size: 0.9em; } pre { background-color: #e9ecef; padding: 15px; border-radius: 5px; white-space: pre-wrap; word-wrap: break-word; } li { margin-bottom: 10px; } .container { background-color: #ffffff; padding: 40px; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.1); }</style></head><body><div class="container"><h1>CDP Repeater</h1><p>This is a lightweight, single-file HTTP repeater tool for web application security testing. It uses the Chrome DevTools Protocol (CDP) to monitor network traffic from a dedicated Chrome tab without needing to configure a traditional proxy.</p><h2>Features</h2><ul><li><strong>Single Python File:</strong> The entire tool is self-contained.</li><li><strong>Sandboxed Browser:</strong> Automatically launches a new, isolated Chrome instance.</li><li><strong>Explicit Tab Monitoring:</strong> Creates and instruments a dedicated tab for your browsing.</li><li><strong>High-Fidelity Repeater:</strong> The "Send" function executes requests via the browser's own engine, automatically including up-to-date cookies and the correct User-Agent.</li><li><strong>Render in Browser:</strong> A "Render in new tab" feature allows you to see the browser's rendered output from any repeated request.</li></ul><h2>Requirements</h2><ul><li>Python 3.8+</li><li>Google Chrome</li><li>The <code>websockets</code> Python library</li></ul><h2>Installation</h2><p>Install the required Python library using pip:</p><pre><code>pip install websockets</code></pre><h2>Usage Instructions</h2><ol><li>When this script is run, this help tab, a "CDP Repeater" control panel tab, and a blank tab are opened.</li><li><strong>Use the blank tab for all your browsing</strong> of the target application.</li><li>As you browse, requests from that tab will appear in the "History" pane of the control panel.</li><li>You can close this help tab at any time.</li></ol><h2>Workflow</h2><ul><li><strong>View a Request:</strong> Click any item in the "History" pane. The full original request and its corresponding response will be displayed.</li><li><strong>Repeat a Request:</strong> Modify the text in the "Request" pane and click the <strong>Send</strong> button. The response to your modified request will appear in the "Response" pane.</li><li><strong>Render a Response:</strong> Check the <strong>"Render in new tab"</strong> box before clicking <strong>Send</strong> to have the response body saved locally and opened in a new Chrome tab.</li></ul></div></body></html>
"""
HTML_CONTENT = """
<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8"><title>CDP Repeater</title><link rel="stylesheet" href="style.css"></head><body><div class="container"><div class="pane history-pane"><h2>History (Last 500)</h2><div class="controls"><button id="clear-history">Clear</button><input type="text" id="search-input" placeholder="Find (UUID, URL, Body)..."></div><ul id="history-list"></ul></div><div class="pane request-pane"><h2>Request</h2><div class="controls controls-row"><button id="send-btn" title="Send Request (Ctrl+Enter)">Send</button><button id="edit-btn">Edit</button><button id="curl-btn">Copy cURL</button><button id="py-btn">Copy Python</button><div class="checkbox-container"><input type="checkbox" id="render-checkbox" name="render-checkbox"><label for="render-checkbox">Render</label></div></div><div id="request-container"><pre id="request-view"></pre><textarea id="request-edit" class="hidden" spellcheck="false"></textarea></div></div><div class="pane response-pane"><h2>Response Headers</h2><pre id="response-headers"></pre><h2>Response Body</h2><pre id="response-body"></pre></div></div><script src="script.js"></script></body></html>
"""
CSS_CONTENT = """
body, html { margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #f0f0f0; height: 100%; }
.container { display: flex; height: 100vh; }
.pane { display: flex; flex-direction: column; padding: 10px; box-sizing: border-box; }
.history-pane { width: 30%; border-right: 1px solid #ccc; overflow-y: hidden; }
.request-pane { width: 40%; border-right: 1px solid #ccc; overflow-y: hidden; }
.response-pane { width: 30%; overflow-y: hidden; }
h2 { margin-top: 0; padding-bottom: 5px; border-bottom: 1px solid #ccc; flex-shrink: 0; }
.controls { margin-bottom: 10px; flex-shrink: 0; display: flex; gap: 5px; flex-wrap: wrap; }
.controls-row { display: flex; align-items: center; }
.checkbox-container { margin-left: 10px; display: flex; align-items: center; font-size: 0.9em; }
.checkbox-container label { margin-left: 5px; user-select: none; color: #333; }
button { padding: 5px 10px; border: 1px solid #ccc; background-color: #e9e9e9; cursor: pointer; min-width: 60px; font-size: 0.85em;}
button:hover { background-color: #ddd; }
input[type="text"]#search-input { padding: 5px; border: 1px solid #ccc; flex-grow: 1; min-width: 0; }
#send-btn { background-color: #d4edda; border-color: #c3e6cb; font-weight: bold; }
#send-btn:hover { background-color: #c3e6cb; }
#edit-btn { background-color: #fff3cd; border-color: #ffeeba; }
#edit-btn:hover { background-color: #ffeeba; }
#curl-btn, #py-btn { background-color: #d1ecf1; border-color: #bee5eb; }
#curl-btn:hover, #py-btn:hover { background-color: #bee5eb; }
#history-list { list-style: none; padding: 0; margin: 0; overflow-y: auto; flex-grow: 1; }
#history-list li { padding: 5px; cursor: pointer; border-bottom: 1px solid #eee; font-size: 0.9em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; display: flex; align-items: center; }
#history-list li.selected { background-color: #dbeaff; }
.status-indicator { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 8px; flex-shrink: 0; background-color: #ccc; }
.status-2xx { background-color: #28a745; }
.status-3xx { background-color: #17a2b8; }
.status-4xx { background-color: #ffc107; }
.status-5xx { background-color: #dc3545; }
.req-text { overflow: hidden; text-overflow: ellipsis; }
.highlight { background-color: #ffeb3b; color: #000; font-weight: bold; border-radius: 2px; }
#request-container { flex-grow: 1; position: relative; overflow: hidden; display: flex; flex-direction: column; }
textarea, #request-view { flex-grow: 1; width: 100%; box-sizing: border-box; font-family: "Courier New", Courier, monospace; font-size: 0.9em; border: 1px solid #ccc; margin: 0; padding: 5px; overflow-y: auto; white-space: pre-wrap; word-break: break-all; background-color: #fff; }
textarea { resize: none; }
.hidden { display: none !important; }
pre { background-color: #fff; white-space: pre-wrap; word-break: break-all; padding: 5px; border: 1px solid #ccc; font-family: "Courier New", Courier, monospace; font-size: 0.9em; margin: 0; }
#response-headers { height: 40%; overflow-y: auto; margin-bottom: 10px; flex-shrink: 0; }
#response-body { flex-grow: 1; overflow-y: auto; }
"""
JS_CONTENT = """
document.addEventListener('DOMContentLoaded', () => {
    const ws = new WebSocket(`ws://127.0.0.1:8765`);
    const historyList = document.getElementById('history-list');

    // Request Pane Elements
    const requestView = document.getElementById('request-view');
    const requestEdit = document.getElementById('request-edit');
    const sendBtn = document.getElementById('send-btn');
    const editBtn = document.getElementById('edit-btn');
    const curlBtn = document.getElementById('curl-btn');
    const pyBtn = document.getElementById('py-btn');
    const renderCheckbox = document.getElementById('render-checkbox');

    const responseHeaders = document.getElementById('response-headers');
    const responseBody = document.getElementById('response-body');
    const clearHistoryBtn = document.getElementById('clear-history');
    const searchInput = document.getElementById('search-input');

    let requests = {}, selectedRequestId = null;
    let requestCounter = 1;
    let isEditing = false;

    // --- Keyboard Shortcuts ---
    document.addEventListener('keydown', (e) => {
        // Ctrl+Enter or Cmd+Enter to Send
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            e.preventDefault();
            sendBtn.click();
        }
    });

    function escapeHtml(text) {
        if (!text) return '';
        return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
    }

    function applyHighlight(text, term) {
        const safeText = escapeHtml(text);
        if (!term || term.length === 0) return safeText;
        const escapedTerm = term.replace(/[.*+?^${}()|[\\]\\\\]/g, '\\\\$&');
        const parts = text.split(new RegExp(`(${escapedTerm})`, 'gi'));
        return parts.map(part => {
             if (part.toLowerCase() === term.toLowerCase()) {
                 return `<span class="highlight">${escapeHtml(part)}</span>`;
             }
             return escapeHtml(part);
        }).join('');
    }

    function parseAndDisplayResponse(rawResponse, highlightTerm) {
        if (!rawResponse) {
            responseHeaders.textContent = 'Waiting for response...';
            responseBody.textContent = '';
            return;
        }
        let headersStr = '', bodyStr = '';
        const headerEndIndex = rawResponse.indexOf('\\n\\n');
        if (headerEndIndex !== -1) {
            headersStr = rawResponse.substring(0, headerEndIndex);
            bodyStr = rawResponse.substring(headerEndIndex + 2);
        } else {
            headersStr = rawResponse;
        }
        responseHeaders.innerHTML = applyHighlight(headersStr, highlightTerm);
        responseBody.innerHTML = applyHighlight(bodyStr, highlightTerm);
    }

    function getStatusClass(statusCode) {
        if (!statusCode) return '';
        const code = parseInt(statusCode);
        if (code >= 200 && code < 300) return 'status-2xx';
        if (code >= 300 && code < 400) return 'status-3xx';
        if (code >= 400 && code < 500) return 'status-4xx';
        if (code >= 500) return 'status-5xx';
        return '';
    }

    function updateDetailsPanes(id) {
        if (!id || !requests[id]) return;

        if (isEditing) toggleEditMode();

        const req = requests[id];
        let rawRequest = `${req.method} ${req.url} HTTP/1.1\\n`;
        for (const [key, value] of Object.entries(req.headers)) { rawRequest += `${key}: ${value}\\n`; }
        if (req.postData) { rawRequest += `\\n${req.postData}`; }

        requestEdit.value = rawRequest;
        requestView.innerHTML = applyHighlight(rawRequest, searchInput.value.trim());

        parseAndDisplayResponse(req.response, searchInput.value.trim());
    }

    function toggleEditMode() {
        isEditing = !isEditing;
        if (isEditing) {
            requestView.classList.add('hidden');
            requestEdit.classList.remove('hidden');
            editBtn.textContent = 'Done';
            requestEdit.focus();
        } else {
            requestView.classList.remove('hidden');
            requestEdit.classList.add('hidden');
            editBtn.textContent = 'Edit';
            requestView.innerHTML = applyHighlight(requestEdit.value, searchInput.value.trim());
        }
    }

    function renderListItem(req, query) {
        const item = document.createElement('li');
        item.dataset.id = req.id;
        item.dataset.count = req.count;

        const statusDot = document.createElement('span');
        statusDot.className = 'status-indicator';

        if (req.response) {
            const firstLine = req.response.split('\\n')[0];
            // Regex Permissive Update for HTTP/2 and weird protocols
            const match = firstLine.match(/HTTP\\/.*?\\s(\\d{3})/);
            if (match) statusDot.classList.add(getStatusClass(match[1]));
        }

        const textSpan = document.createElement('span');
        textSpan.className = 'req-text';
        const labelText = `${req.count}. ${req.method} ${req.url}`;

        if (query) {
             textSpan.innerHTML = applyHighlight(labelText, query);
        } else {
             textSpan.textContent = labelText;
        }

        item.appendChild(statusDot);
        item.appendChild(textSpan);
        return item;
    }

    function filterHistory() {
        const query = searchInput.value.trim();
        const lowerQuery = query.toLowerCase();

        historyList.innerHTML = '';
        const sortedReqs = Object.values(requests).sort((a, b) => a.count - b.count);

        sortedReqs.forEach(req => {
            let searchable = `${req.method} ${req.url}`;
            if (req.postData) searchable += ` ${req.postData}`;
            for (const [key, value] of Object.entries(req.headers)) { searchable += ` ${key} ${value}`; }
            if (req.response) searchable += ` ${req.response}`;

            if (!query || searchable.toLowerCase().includes(lowerQuery)) {
                const item = renderListItem(req, query);
                if (selectedRequestId === req.id) item.classList.add('selected');
                historyList.appendChild(item);
            }
        });

        if (selectedRequestId && !isEditing) {
             requestView.innerHTML = applyHighlight(requestEdit.value, query);
             if (requests[selectedRequestId].response) {
                 parseAndDisplayResponse(requests[selectedRequestId].response, query);
             }
        }
    }

    function parseRequestParts(rawRequest) {
        const headerEndIndex = rawRequest.indexOf('\\n\\n');
        let headersPart = rawRequest;
        let bodyPart = '';
        if (headerEndIndex !== -1) {
            headersPart = rawRequest.substring(0, headerEndIndex);
            bodyPart = rawRequest.substring(headerEndIndex + 2);
        }
        const lines = headersPart.split('\\n');
        if (lines.length === 0) return null;
        const firstLine = lines[0].split(' ');
        const method = firstLine[0];
        const url = firstLine[1];

        const headers = {};
        for (let i = 1; i < lines.length; i++) {
            const line = lines[i];
            if (!line.trim()) continue;
            const colonIndex = line.indexOf(':');
            if (colonIndex !== -1) {
                const key = line.substring(0, colonIndex).trim();
                const val = line.substring(colonIndex + 1).trim();
                headers[key] = val;
            }
        }
        return { method, url, headers, body: bodyPart };
    }

    function generateCurl(rawRequest) {
        const p = parseRequestParts(rawRequest);
        if (!p) return '';
        const escapeSingle = (s) => s.replace(/'/g, "'\\\\''");
        let cmd = `curl -X ${p.method} '${escapeSingle(p.url)}'`;
        for (const [key, val] of Object.entries(p.headers)) {
            cmd += ` -H '${escapeSingle(key)}: ${escapeSingle(val)}'`;
        }
        if (p.body) cmd += ` --data-raw '${escapeSingle(p.body)}'`;
        return cmd;
    }

    function generatePython(rawRequest) {
        const p = parseRequestParts(rawRequest);
        if (!p) return '';

        let py = `import requests\\nimport json\\n\\n`;
        py += `url = "${p.url}"\\n`;
        py += `headers = ${JSON.stringify(p.headers, null, 4)}\\n`;

        if (p.body) {
            try {
                JSON.parse(p.body);
                py += `data = json.loads(${JSON.stringify(p.body)})\\n`;
                py += `response = requests.${p.method.toLowerCase()}(url, headers=headers, json=data)`;
            } catch (e) {
                py += `data = ${JSON.stringify(p.body)}\\n`;
                py += `response = requests.${p.method.toLowerCase()}(url, headers=headers, data=data)`;
            }
        } else {
            py += `response = requests.${p.method.toLowerCase()}(url, headers=headers)`;
        }

        py += `\\n\\nprint(response.status_code)\\nprint(response.text)`;
        return py;
    }

    ws.onopen = () => console.log('Connected to backend.');
    ws.onerror = (error) => console.error('WebSocket Error:', error);

    ws.onmessage = (event) => {
        const message = JSON.parse(event.data);
        if (message.type === 'new_request') {
            const req = message.data;
            req.count = requestCounter;
            requests[req.id] = req;
            requestCounter++;
            filterHistory();
        } else if (message.type === 'response_data') {
            const res = message.data;
            if (requests[res.id]) {
                requests[res.id].response = res.body;
                if (selectedRequestId === res.id) {
                    parseAndDisplayResponse(res.body, searchInput.value.trim());
                }
                filterHistory();
            }
        } else if (message.type === 'repeated_response') {
            parseAndDisplayResponse(message.data, searchInput.value.trim());
        } else if (message.type === 'remove_request') {
            const idToRemove = message.data.id;
            if (requests[idToRemove]) delete requests[idToRemove];
            filterHistory();
        }
    };

    historyList.addEventListener('click', (e) => {
        let target = e.target;
        while (target && target.nodeName !== 'LI' && target !== historyList) {
            target = target.parentElement;
        }

        if (target && target.nodeName === 'LI') {
            const id = target.dataset.id;
            selectedRequestId = id;
            filterHistory();
            updateDetailsPanes(id);
        }
    });

    sendBtn.addEventListener('click', () => {
        const rawRequest = requestEdit.value;
        if (!rawRequest) return;

        if (!isEditing) {
             requestView.innerHTML = applyHighlight(rawRequest, searchInput.value.trim());
        }

        const shouldRender = renderCheckbox.checked;
        responseHeaders.textContent = 'Sending request via browser...';
        responseBody.textContent = '';
        ws.send(JSON.stringify({ type: 'repeat_request', data: rawRequest, render: shouldRender }));
    });

    editBtn.addEventListener('click', toggleEditMode);

    function handleCopy(btn, generator) {
        const rawRequest = requestEdit.value;
        if (!rawRequest) return;
        const text = generator(rawRequest);
        navigator.clipboard.writeText(text).then(() => {
            const originalText = btn.textContent;
            btn.textContent = 'Copied!';
            setTimeout(() => btn.textContent = originalText, 1500);
        });
    }

    curlBtn.addEventListener('click', () => handleCopy(curlBtn, generateCurl));
    pyBtn.addEventListener('click', () => handleCopy(pyBtn, generatePython));

    clearHistoryBtn.addEventListener('click', () => {
        historyList.innerHTML = '';
        requests = {};
        selectedRequestId = null;
        requestEdit.value = '';
        requestView.textContent = '';
        responseHeaders.textContent = '';
        responseBody.textContent = '';
        requestCounter = 1;
        searchInput.value = '';
    });

    searchInput.addEventListener('input', filterHistory);
});
"""

# --- Part 2: Backend Logic ---

async def execute_cdp_command(method, params={}, session_id=None):
    global CDP_COMMAND_ID
    CDP_COMMAND_ID += 1; command_id = CDP_COMMAND_ID
    future = asyncio.Future()
    command = {"id": command_id, "method": method, "params": params, "future": future}
    if session_id: command["sessionId"] = session_id
    await cdp_command_queue.put(command)
    return await future

def host_response_body(response_data):
    try:
        _, _, body = response_data.partition('\n\n')
        filename = f"response-{uuid.uuid4().hex}.html"
        with open(filename, "w", encoding="utf-8", errors="replace") as f: f.write(body)
        print(f"Hosted response body in {filename}")
        return f"http://127.0.0.1:{HTTP_PORT}/{filename}"
    except Exception as e:
        print(f"Error hosting response body: {e}"); return None

async def wait_for_http_server(port, timeout=5):
    start_time = time.monotonic()
    while time.monotonic() - start_time < timeout:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}", timeout=1) as response:
                if response.status == 200: print("UI server is up and running."); return True
        except (urllib.error.URLError, ConnectionRefusedError): await asyncio.sleep(0.1)
    print("Error: UI server did not start within the timeout period."); return False

def create_ui_files():
    print("Creating UI files...")
    with open("index.html", "w", encoding="utf-8") as f: f.write(HTML_CONTENT)
    with open("style.css", "w", encoding="utf-8") as f: f.write(CSS_CONTENT)
    with open("script.js", "w", encoding="utf-8") as f: f.write(JS_CONTENT)
    with open("help.html", "w", encoding="utf-8") as f: f.write(HELP_HTML_CONTENT)

def launch_chrome(port, user_data_dir):
    system = platform.system()
    chrome_path = ""
    if system == 'Windows':
        possible_paths = [ os.path.join(os.environ["ProgramFiles"], "Google", "Chrome", "Application", "chrome.exe"), os.path.join(os.environ["ProgramFiles(x86)"], "Google", "Chrome", "Application", "chrome.exe"), os.path.join(os.environ["LOCALAPPDATA"], "Google", "Chrome", "Application", "chrome.exe") ]
        for path in possible_paths:
            if os.path.exists(path): chrome_path = path; break
    elif system == 'Darwin': chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    elif system == 'Linux': chrome_path = "google-chrome"
    if not chrome_path or (system != 'Linux' and not os.path.exists(chrome_path)):
         print("Error: Chrome executable not found."); return False

    command = [
        chrome_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={user_data_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-breakpad",
        "--disable-background-networking",
        f"http://127.0.0.1:{HTTP_PORT}/help.html"
    ]

    print(f"Launching Chrome with command: {' '.join(command)}")
    try: subprocess.Popen(command)
    except FileNotFoundError: print("Error: Chrome executable not found in system PATH (for Linux)."); return False
    return True

def get_websocket_url(port):
    url = f"http://127.0.0.1:{port}/json/version"
    print(f"Attempting to connect to Chrome's browser endpoint at {url}...")
    try:
        with urllib.request.urlopen(url) as response: return json.load(response)["webSocketDebuggerUrl"]
    except Exception: return None

def run_http_server(port):
    server_address = ("127.0.0.1", port); handler = http.server.SimpleHTTPRequestHandler
    with socketserver.TCPServer(server_address, handler) as httpd:
        print(f"UI server running at http://{server_address[0]}:{server_address[1]}"); httpd.serve_forever()

# --- Async UI Sender Loop (The Fix for Backpressure) ---
async def ui_sender_loop():
    """Reads messages from the queue and sends them to the websocket without blocking CDP."""
    while True:
        message = await ui_message_queue.get()
        if ui_websocket_connection:
            try:
                await ui_websocket_connection.send(json.dumps(message))
            except Exception:
                pass # Connection closed or error, just drop the message
        ui_message_queue.task_done()

async def ui_websocket_handler(websocket, path=None):
    global ui_websocket_connection
    ui_websocket_connection = websocket; print("UI connected via WebSocket."); ui_ready.set()
    try:
        async for message in websocket:
            command = json.loads(message)
            if command['type'] == 'repeat_request':
                should_render = command.get('render', False)
                response_data = await repeat_request_via_cdp(command['data'])
                if ui_websocket_connection: await ui_websocket_connection.send(json.dumps({"type": "repeated_response", "data": response_data}))
                if should_render and response_data:
                    local_url = host_response_body(response_data)
                    if local_url: await execute_cdp_command("Target.createTarget", {"url": local_url})
    finally:
        ui_websocket_connection = None; ui_ready.clear(); print("UI disconnected.")

async def repeat_request_via_cdp(raw_request):
    if not MONITORED_SESSION_ID: return "Error: No monitored tab is available to send the request from."
    try:
        cookie_data = await execute_cdp_command("Network.getAllCookies")
        cookies = {c['name']: c['value'] for c in cookie_data.get('cookies', [])}
        cookie_header = "; ".join([f"{name}={value}" for name, value in cookies.items()])
        headers_part, _, body_part = raw_request.partition('\n\n')
        request_lines = headers_part.split('\n'); method, url, _ = request_lines[0].split(' ', 2)
        headers = {line.split(': ', 1)[0]: line.split(': ', 1)[1] for line in request_lines[1:] if ': ' in line}
        headers['Cookie'] = cookie_header
        if browser_user_agent: headers['User-Agent'] = browser_user_agent
        js_headers = json.dumps(headers); js_body = json.dumps(body_part)
        js_expression = f"""(async () => {{ try {{ const response = await fetch("{url}", {{ method: "{method}", headers: {js_headers}, body: '{method}' === 'GET' || '{method}' === 'HEAD' ? undefined : {js_body}, credentials: "include", mode: 'cors' }}); const responseBody = await response.text(); const responseHeaders = {{}}; for (const [key, value] of response.headers.entries()) {{ responseHeaders[key] = value; }} return {{ status: response.status, statusText: response.statusText, headers: responseHeaders, body: responseBody }}; }} catch (e) {{ return {{ error: e.toString() }}; }} }})()"""
        result = await execute_cdp_command("Runtime.evaluate", { "expression": js_expression, "awaitPromise": True, "returnByValue": True }, session_id=MONITORED_SESSION_ID)
        if 'result' in result and 'value' in result['result']:
            res_val = result['result']['value']
            if 'error' in res_val: return f"Error executing fetch in browser: {res_val['error']}"
            status_line = f"HTTP/1.1 {res_val.get('status')} {res_val.get('statusText')}"
            headers_part = "\n".join([f"{k}: {v}" for k, v in res_val.get('headers', {}).items()])
            body_part = res_val.get('body', '')
            return f"{status_line}\n{headers_part}\n\n{body_part}"
        return f"Failed to get a valid response from browser. CDP Result: {result}"
    except Exception as e: return f"Error processing repeat request: {str(e)}"

async def cdp_client_logic(cdp_ws_url):
    global browser_user_agent, MONITORED_SESSION_ID
    async with websockets.connect(cdp_ws_url, max_size=None) as cdp_ws:
        print("Successfully connected to Chrome browser.")

        async def cdp_writer():
            global pending_futures
            while True:
                command = await cdp_command_queue.get()
                if 'future' in command: pending_futures[command['id']] = command.pop('future')
                await cdp_ws.send(json.dumps(command)); cdp_command_queue.task_done()

        async def cdp_reader():
            global request_history, request_order, CDP_COMMAND_ID, cdp_id_to_req_id, network_id_to_fetch_id
            while True:
                message = await cdp_ws.recv(); data = json.loads(message)
                session_id = data.get("sessionId")
                if session_id and session_id != MONITORED_SESSION_ID: continue
                method = data.get("method")
                if "id" in data:
                    cmd_id = data.get("id")
                    if cmd_id in pending_futures:
                        future = pending_futures.pop(cmd_id); future.set_result(data.get('result', {}))
                    elif cmd_id in cdp_id_to_req_id:
                        fetch_id = cdp_id_to_req_id.pop(cmd_id)
                        body = "[Response body not available]"

                        if 'error' not in data:
                            result = data.get("result", {})
                            if result.get("base64Encoded"): body = f"[Binary Content ({len(result.get('body', ''))} bytes, base64)]"
                            else: body = result.get("body", "")
                        else:
                            stored_error = request_history.get(fetch_id, {}).get('error_text')
                            if stored_error:
                                body = f"[Request Failed: {stored_error}]"
                            else:
                                body = f"[No Content / Body Unavailable (CDP Error: {data['error'].get('message', 'Unknown')})]"

                        if fetch_id in request_history:
                            headers = request_history[fetch_id].get('response_headers', 'HTTP/1.1 000 Unknown')
                            full_response = f"{headers}\n\n{body}"
                            # DECOUPLED: Put in queue, don't await
                            ui_message_queue.put_nowait({"type": "response_data", "data": { "id": fetch_id, "body": full_response }})

                elif method == "Fetch.requestPaused":
                    event = data["params"]; fetch_id = event["requestId"]; network_id = event.get("networkId")
                    if network_id:
                        network_id_to_fetch_id[network_id] = fetch_id

                    if ui_websocket_connection:
                        request_data = { "id": fetch_id, "url": event["request"]["url"], "method": event["request"]["method"], "headers": event["request"]["headers"], "postData": event["request"].get("postData") }
                        request_history[fetch_id] = request_data; request_order.append(fetch_id)
                        if len(request_order) > HISTORY_LIMIT:
                            oldest_id = request_order.pop(0)
                            if oldest_id in request_history: del request_history[oldest_id]
                            ui_message_queue.put_nowait({ "type": "remove_request", "data": {"id": oldest_id} })

                        # DECOUPLED: Put in queue
                        ui_message_queue.put_nowait({"type": "new_request", "data": request_data})

                    if not network_id and ui_websocket_connection:
                         ui_message_queue.put_nowait({"type": "response_data", "data": { "id": fetch_id, "body": "[Cached/Internal Request - No Network Body]" }})

                    CDP_COMMAND_ID += 1
                    # IMPORTANT: Queue the continue immediately
                    await cdp_command_queue.put({"id": CDP_COMMAND_ID, "method": "Fetch.continueRequest", "params": {"requestId": fetch_id}, "sessionId": MONITORED_SESSION_ID})

                elif method == "Network.responseReceived":
                    network_id = data["params"]["requestId"]
                    fetch_id = network_id_to_fetch_id.get(network_id)
                    if fetch_id and fetch_id in request_history:
                        response = data["params"]["response"]
                        status_line = f"HTTP/{response.get('protocol', '1.1')} {response['status']} {response['statusText']}"
                        headers = "\n".join([f"{k}: {v}" for k, v in response["headers"].items()])
                        request_history[fetch_id]['response_headers'] = f"{status_line}\n{headers}"

                elif method == "Network.loadingFinished":
                    network_id = data["params"]["requestId"]; fetch_id = network_id_to_fetch_id.pop(network_id, None)
                    if fetch_id and fetch_id in request_history:
                        CDP_COMMAND_ID += 1; cmd_id = CDP_COMMAND_ID
                        cdp_id_to_req_id[cmd_id] = fetch_id
                        await cdp_command_queue.put({"id": cmd_id, "method": "Network.getResponseBody", "params": {"requestId": network_id}, "sessionId": MONITORED_SESSION_ID})

                elif method == "Network.loadingFailed":
                    network_id = data["params"]["requestId"]
                    fetch_id = network_id_to_fetch_id.pop(network_id, None)
                    if fetch_id and fetch_id in request_history:
                        request_history[fetch_id]['error_text'] = data["params"].get("errorText", "Unknown Error")
                        CDP_COMMAND_ID += 1; cmd_id = CDP_COMMAND_ID
                        cdp_id_to_req_id[cmd_id] = fetch_id
                        await cdp_command_queue.put({"id": cmd_id, "method": "Network.getResponseBody", "params": {"requestId": network_id}, "sessionId": MONITORED_SESSION_ID})

        writer_task = asyncio.create_task(cdp_writer())
        reader_task = asyncio.create_task(cdp_reader())
        ui_sender = asyncio.create_task(ui_sender_loop()) # Start the UI sender loop

        version_info = await execute_cdp_command("Browser.getVersion")
        if 'userAgent' in version_info:
            browser_user_agent = version_info['userAgent']; print(f"Captured browser User-Agent: {browser_user_agent[:50]}...")

        print("Creating control panel tab..."); await execute_cdp_command("Target.createTarget", {"url": f"http://127.0.0.1:{HTTP_PORT}"})
        print("Creating a blank tab for you to browse in...")
        user_tab = await execute_cdp_command("Target.createTarget", {"url": "about:blank"})
        user_target_id = user_tab.get("targetId")
        if not user_target_id: print("FATAL: Could not create the user browsing tab. Exiting."); return
        print(f"Attaching listeners to user tab (ID: {user_target_id})...")
        attach_result = await execute_cdp_command("Target.attachToTarget", {"targetId": user_target_id, "flatten": True})
        MONITORED_SESSION_ID = attach_result.get("sessionId")
        if not MONITORED_SESSION_ID: print(f"FATAL: Could not attach to user tab. Exiting."); return

        print(f"Successfully attached with session ID: {MONITORED_SESSION_ID}")
        await execute_cdp_command("Network.enable", {}, session_id=MONITORED_SESSION_ID)
        await execute_cdp_command("Fetch.enable", {"patterns": [{"urlPattern": "*"}]}, session_id=MONITORED_SESSION_ID)

        print("Waiting for UI to connect..."); await ui_ready.wait()
        print("UI is ready. Please use the blank tab for browsing.")
        await asyncio.gather(reader_task, writer_task, ui_sender)

async def main():
    print("Starting CDP Repeater v6.3")
    create_ui_files()

    http_thread = threading.Thread(target=run_http_server, args=(HTTP_PORT,), daemon=True)
    http_thread.start()
    if not await wait_for_http_server(HTTP_PORT):
        print("Aborting due to UI server launch failure."); return

    user_data_dir = os.path.join(os.getcwd(), USER_DATA_DIR_NAME)
    if not launch_chrome(CHROME_DEBUG_PORT, user_data_dir): return

    print("Waiting for Chrome's debugging port to become available...")
    cdp_ws_url = None
    for attempt in range(10):
        cdp_ws_url = get_websocket_url(CHROME_DEBUG_PORT)
        if cdp_ws_url: break
        if attempt < 9: print(f"Connection failed. Retrying in 2 seconds..."); time.sleep(2)
    if not cdp_ws_url: print("Could not connect to Chrome after multiple attempts. Exiting."); return

    cdp_task = asyncio.create_task(cdp_client_logic(cdp_ws_url))

    async with websockets.serve(ui_websocket_handler, "127.0.0.1", WEBSOCKET_PORT):
        print("All services are running. Press Ctrl+C to shut down."); await asyncio.Future()

if __name__ == "__main__":
    try: asyncio.run(main())
    except KeyboardInterrupt:
        print("\nShutting down.")
        for item in os.listdir():
            if item.startswith("response-") and item.endswith(".html"):
                os.remove(item)
        for f in ["index.html", "style.css", "script.js", "help.html"]:
            if os.path.exists(f): os.remove(f)