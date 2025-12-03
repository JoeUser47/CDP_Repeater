# CDP_Repeater
Chrome DevTools Protocol web request repeater using Python.

**Current Version:** 6.3
**Author:** Gemini (Assisted)

A lightweight, single-file HTTP repeater designed for web application security testing. Unlike traditional proxies (like Burp Suite or Caido) that sit *between* the browser and the server, CDP Repeater sits *on top* of the browser using the Chrome DevTools Protocol (CDP).

This allows for "High-Fidelity" repeating: every request you modify and resend is executed by the actual Chrome rendering engine, ensuring perfect handling of complex JavaScript signatures, updated cookies, and browser fingerprinting.

## ⚠️ Security & Operational Warnings

Before running this tool, please acknowledge the following:

1.  **Open Ports:** This script opens two local servers by default:
    * **HTTP Port 9999:** Hosts the UI and any rendered response bodies.
    * **WebSocket Port 8765:** Handles real-time communication between the UI and the Python backend.
    * *Advisory:* These bind to `127.0.0.1`. Do not expose these ports to a public network. If you are running this on a remote VPS, ensure you are tunneling these ports via SSH and not exposing them to the open internet, as there is no authentication mechanism.

2.  **Sensitive Data:** The tool captures and displays headers, cookies, and response bodies in plain text within the UI. This data is stored in memory (`request_history`) while the script is running.

3.  **Chrome Isolation:** The script launches a specific instance of Chrome using a temporary user data directory (`./ChromeRepeaterSession`). It **does not** use your default Chrome profile, passwords, or extensions. This is a security feature to keep your testing sandboxed.

4.  **Chrome Flags:** The browser is launched with flags to suppress background noise (`--disable-background-networking`, `--disable-sync`, etc.). This creates a cleaner history but may differ slightly from a standard user's browser fingerprint regarding background telemetry.

## Features

* **Zero-Config Proxy:** No need to mess with system proxy settings or CA certificates.
* **Asynchronous Architecture:** Uses a "Fire-and-Forget" queue system to prevent the UI from blocking browser traffic during high-volume loads.
* **Search & Highlight:** Real-time filtering of request history with syntax highlighting for search terms in headers and bodies.
* **Smart Editor:** * Toggle between a syntax-highlighted view (for reading) and a raw Textarea (for editing).
    * Supports `Ctrl+Enter` (or `Cmd+Enter`) to quick-send requests.
* **Export Options:**
    * **Copy cURL:** Generates a cURL command with the current cookies and headers.
    * **Copy Python:** Generates a `requests` script, automatically handling JSON bodies and `null`/`true` conversion.

## Prerequisites

* **Python 3.8+**
* **Google Chrome** (Must be installed in a standard location)
* **Python Libraries:**
    ```bash
    pip install websockets
    ```

## Installation & Usage

1.  **Download:** Save `cdp_repeater.py` to a dedicated directory.
2.  **Run:**
    ```bash
    python cdp_repeater.py
    ```
3.  **The Interface:**
    * The script will launch Chrome automatically.
    * **Tab 1 (Help):** Basic instructions.
    * **Tab 2 (Control Panel):** This is where you view history and modify requests.
    * **Tab 3 (Blank):** **Use this tab for your target browsing.**

4.  **Repeating:**
    * Browse the target site in the blank tab.
    * Switch to the Control Panel tab.
    * Click a request in the History list (left pane).
    * Click **Edit**, modify the payload, and click **Send**.

5. **Cleanup:**
    * Exiting the script with Ctrl-C will delete the self-created css, js, and html files.
    * The ChromeRepeaterSession may be deleted manually if you want a fresh session without history.

## Configuration

You can adjust the following constants at the top of `cdp_repeater.py` to suit your environment:

```python
HTTP_PORT = 9999            # Port for the UI
WEBSOCKET_PORT = 8765       # Port for data stream
CHROME_DEBUG_PORT = 9222    # Port for CDP connection
HISTORY_LIMIT = 500         # How many requests to keep in memory
```

## Troubleshooting

  * **"Chrome executable not found":** \* Ensure Chrome is installed.
      * If on Linux, ensure `google-chrome` is in your PATH.
      * If using a non-standard install, edit the `launch_chrome` function in the script.
  * **History is Empty:**
      * Ensure you are browsing in the specific **blank tab** opened by the tool (or any new tab opened *within* that specific browser window). Requests from your standard daily browser instance will not appear here.
  * **Stuck "Waiting for response...":**
      * If the target server keeps the connection open indefinitely (e.g., a long poll), the repeater might wait. You can use the "Copy cURL" feature to debug this in a terminal.

