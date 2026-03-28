# Canon ShutterCheck Web App — Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a local web app that reads Canon EOS camera data (shutter count, battery, firmware, serial, owner/artist/copyright) over USB via a Python/Flask + gphoto2 backend with an Anthropic-styled frontend.

**Architecture:** Flask server wraps `python-gphoto2` to communicate with Canon cameras over USB/PTP. Kills macOS `ptpcamerad` to claim the device. Serves a static vanilla HTML/JS/CSS frontend on the same origin. gphoto2 context is re-initialized per request.

**Tech Stack:** Python 3, Flask, python-gphoto2, vanilla HTML/JS/CSS, ES modules

**Spec:** `docs/superpowers/specs/2026-03-28-canon-shutter-check-design.md`

---

## File Structure

> **Spec deviation:** The spec places the camera DB in `static/js/camera-db.js` (client-side). This plan moves it to `camera_db.py` (server-side) because the server needs lifespan data to compute `wearPercent` in the API response. A client-side copy would be dead code. Tests directory is added for unit tests.

```
canon/
  server.py               — Flask app, gphoto2 wrapper, REST API, ptpcamerad killer, signal handler
  camera_db.py             — Model → rated lifespan lookup, name normalization
  requirements.txt         — python-gphoto2, flask
  tests/
    test_camera_db.py      — Unit tests for camera DB lookup and name normalization
    test_server.py         — API endpoint tests with mocked gphoto2
  static/
    index.html             — Single page, all markup, three tabs
    css/
      style.css            — Anthropic design system (colors, typography, layout, tabs, data rows)
    js/
      app.js               — UI state machine, tab switching, API calls, DOM rendering, share/export
```

---

## Chunk 1: Backend

### Task 1: Project setup and camera database

**Files:**
- Create: `canon/requirements.txt`
- Create: `canon/camera_db.py`
- Create: `canon/tests/test_camera_db.py`

- [ ] **Step 1: Create requirements.txt**

```
gphoto2
flask
```

- [ ] **Step 2: Install dependencies**

Run: `cd ~/pt/canon && pip install -r requirements.txt`
Expected: Successful install of gphoto2 and flask packages.

Note: `python-gphoto2` pip package is named `gphoto2`. It requires `libgphoto2` C library to be installed (`brew install libgphoto2`).

- [ ] **Step 3: Write camera_db.py tests**

```python
# tests/test_camera_db.py
from camera_db import get_rated_lifespan, normalize_model_name


def test_normalize_strips_canon_prefix():
    assert normalize_model_name("Canon EOS 5D Mark II") == "EOS 5D Mark II"


def test_normalize_preserves_eos_prefix():
    assert normalize_model_name("EOS 5D Mark II") == "EOS 5D Mark II"


def test_normalize_strips_whitespace():
    assert normalize_model_name("  Canon EOS 6D  ") == "EOS 6D"


def test_known_model_returns_lifespan():
    assert get_rated_lifespan("Canon EOS 5D Mark II") == 150000


def test_known_model_without_prefix():
    assert get_rated_lifespan("EOS 7D Mark II") == 200000


def test_unknown_model_returns_none():
    assert get_rated_lifespan("Canon EOS R5") is None


def test_all_models_have_positive_lifespan():
    from camera_db import CAMERA_DB
    for model, lifespan in CAMERA_DB.items():
        assert lifespan > 0, f"{model} has invalid lifespan {lifespan}"
```

- [ ] **Step 4: Run tests to verify they fail**

Run: `cd ~/pt/canon && python -m pytest tests/test_camera_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'camera_db'`

- [ ] **Step 5: Write camera_db.py**

```python
# camera_db.py
CAMERA_DB = {
    "EOS 5D Mark II": 150000,
    "EOS 5D Mark III": 150000,
    "EOS 5D Mark IV": 150000,
    "EOS 6D": 100000,
    "EOS 6D Mark II": 100000,
    "EOS 7D": 150000,
    "EOS 7D Mark II": 200000,
    "EOS 60D": 100000,
    "EOS 70D": 100000,
    "EOS 80D": 100000,
}


def normalize_model_name(name):
    """Strip 'Canon ' prefix and whitespace. gphoto2 reports 'Canon EOS 5D Mark II', DB keys use 'EOS 5D Mark II'."""
    name = name.strip()
    if name.startswith("Canon "):
        name = name[6:]
    return name


def get_rated_lifespan(model_name):
    """Return rated shutter lifespan for a model, or None if unknown."""
    normalized = normalize_model_name(model_name)
    return CAMERA_DB.get(normalized)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd ~/pt/canon && python -m pytest tests/test_camera_db.py -v`
Expected: All 7 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt camera_db.py tests/test_camera_db.py
git commit -m "feat: add camera database with model lifespan lookup"
```

---

### Task 2: Flask server with gphoto2 integration

**Files:**
- Create: `canon/server.py`

- [ ] **Step 1: Write server.py**

```python
# server.py
import os
import signal
import subprocess
import sys
import webbrowser

import gphoto2 as gp
from flask import Flask, jsonify, request, send_from_directory

from camera_db import get_rated_lifespan, normalize_model_name

app = Flask(__name__, static_folder="static", static_url_path="/static")


# --- ptpcamerad management ---

def kill_ptpcamerad():
    """Kill macOS ptpcamerad to release USB camera. Best-effort."""
    try:
        subprocess.run(["pkill", "-9", "ptpcamerad"], capture_output=True)
    except Exception:
        pass
    try:
        uid = os.getuid()
        subprocess.run(
            ["launchctl", "bootout", f"gui/{uid}/com.apple.ptpcamerad"],
            capture_output=True,
        )
    except Exception:
        pass


# --- gphoto2 camera access ---

def get_camera():
    """Detect and return a gphoto2 camera object, or None. Re-kills ptpcamerad if needed."""
    kill_ptpcamerad()
    try:
        camera = gp.Camera()
        camera.init()
        return camera
    except gp.GPhoto2Error:
        return None


def read_config_value(camera, path):
    """Read a single config value from camera. Returns string or None."""
    try:
        config = camera.get_single_config(path)
        return config.get_value()
    except gp.GPhoto2Error:
        return None


def read_summary(camera):
    """Parse camera summary for model, serial, firmware."""
    info = {}
    try:
        summary = camera.get_summary()
        for line in str(summary).split("\n"):
            line = line.strip()
            if line.startswith("Model:"):
                info["model"] = line.split(":", 1)[1].strip()
            elif line.startswith("Serial Number:"):
                info["serial"] = line.split(":", 1)[1].strip()
            elif line.startswith("Version:"):
                info["firmware"] = line.split(":", 1)[1].strip()
    except gp.GPhoto2Error:
        pass
    return info


def camera_request(fn):
    """Wrapper: get camera, call fn(camera), release camera. Returns JSON error on failure."""
    camera = get_camera()
    if camera is None:
        return jsonify({"connected": False, "error": "No camera found"}), 404
    try:
        result = fn(camera)
        return jsonify(result)
    except gp.GPhoto2Error as e:
        return jsonify({"connected": False, "error": str(e)}), 500
    finally:
        try:
            camera.exit()
        except Exception:
            pass


# --- API routes ---

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/status")
def api_status():
    camera = get_camera()
    if camera is None:
        return jsonify({"connected": False})
    try:
        summary = read_summary(camera)
        return jsonify({"connected": True, "model": summary.get("model", "Unknown")})
    finally:
        try:
            camera.exit()
        except Exception:
            pass


@app.route("/api/camera")
def api_camera_all():
    def read_all(camera):
        summary = read_summary(camera)
        model = summary.get("model", "Unknown")

        battery = read_config_value(camera, "/main/status/batterylevel")
        shutter = read_config_value(camera, "/main/status/shuttercounter")
        owner = read_config_value(camera, "/main/settings/ownername")
        artist = read_config_value(camera, "/main/settings/artist")
        copyright_ = read_config_value(camera, "/main/settings/copyright")

        shutter_count = int(shutter) if shutter and shutter.isdigit() else None
        rated = get_rated_lifespan(model)
        wear = round(shutter_count / rated * 100, 1) if shutter_count and rated else None

        return {
            "connected": True,
            "overview": {
                "model": model,
                "serial": summary.get("serial", ""),
                "firmware": summary.get("firmware", ""),
                "battery": battery or "Unknown",
            },
            "shutter": {
                "count": shutter_count,
                "ratedLifespan": rated,
                "wearPercent": wear,
            },
            "user": {
                "owner": owner or "",
                "artist": artist or "",
                "copyright": copyright_ or "",
            },
        }
    return camera_request(read_all)


@app.route("/api/camera/overview")
def api_camera_overview():
    def read_overview(camera):
        summary = read_summary(camera)
        battery = read_config_value(camera, "/main/status/batterylevel")
        return {
            "model": summary.get("model", "Unknown"),
            "serial": summary.get("serial", ""),
            "firmware": summary.get("firmware", ""),
            "battery": battery or "Unknown",
        }
    return camera_request(read_overview)


@app.route("/api/camera/shutter")
def api_camera_shutter():
    def read_shutter(camera):
        summary = read_summary(camera)
        model = summary.get("model", "Unknown")
        shutter = read_config_value(camera, "/main/status/shuttercounter")
        shutter_count = int(shutter) if shutter and shutter.isdigit() else None
        rated = get_rated_lifespan(model)
        wear = round(shutter_count / rated * 100, 1) if shutter_count and rated else None
        return {
            "count": shutter_count,
            "ratedLifespan": rated,
            "wearPercent": wear,
        }
    return camera_request(read_shutter)


@app.route("/api/camera/user", methods=["GET"])
def api_camera_user_get():
    def read_user(camera):
        owner = read_config_value(camera, "/main/settings/ownername")
        artist = read_config_value(camera, "/main/settings/artist")
        copyright_ = read_config_value(camera, "/main/settings/copyright")
        return {
            "owner": owner or "",
            "artist": artist or "",
            "copyright": copyright_ or "",
        }
    return camera_request(read_user)


@app.route("/api/camera/user", methods=["POST"])
def api_camera_user_post():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400

    def write_user(camera):
        fields = [
            ("/main/settings/ownername", "owner"),
            ("/main/settings/artist", "artist"),
            ("/main/settings/copyright", "copyright"),
        ]
        for config_key, json_key in fields:
            if json_key in data:
                try:
                    config = camera.get_single_config(config_key)
                    config.set_value(str(data[json_key]))
                    camera.set_single_config(config_key, config)
                except gp.GPhoto2Error:
                    pass

        # Read back to confirm what was stored
        owner = read_config_value(camera, "/main/settings/ownername")
        artist = read_config_value(camera, "/main/settings/artist")
        copyright_ = read_config_value(camera, "/main/settings/copyright")
        return {
            "owner": owner or "",
            "artist": artist or "",
            "copyright": copyright_ or "",
        }
    return camera_request(write_user)


# --- Graceful shutdown ---

def shutdown_handler(signum, frame):
    print("\nShutting down...")
    sys.exit(0)


# --- Main ---

if __name__ == "__main__":
    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    kill_ptpcamerad()
    print("Canon ShutterCheck server starting...")
    print("Opening http://localhost:5000")
    webbrowser.open("http://localhost:5000")
    app.run(host="127.0.0.1", port=5000, debug=False)
```

- [ ] **Step 2: Smoke test the server (camera connected)**

Run: `cd ~/pt/canon && sudo python3 server.py &`
Then: `curl -s http://localhost:5000/api/status | python3 -m json.tool`
Expected: `{ "connected": true, "model": "Canon EOS 5D Mark II" }` (or `connected: false` if no camera)
Then: `kill %1` to stop.

- [ ] **Step 3: Commit**

```bash
git add server.py
git commit -m "feat: add Flask server with gphoto2 camera API"
```

---

### Task 3: Server unit tests with mocked gphoto2

**Files:**
- Create: `canon/tests/test_server.py`

- [ ] **Step 1: Write server API tests**

```python
# tests/test_server.py
import json
from unittest.mock import MagicMock, patch

import pytest

from server import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@patch("server.get_camera")
def test_status_no_camera(mock_get_camera, client):
    mock_get_camera.return_value = None
    resp = client.get("/api/status")
    data = json.loads(resp.data)
    assert data["connected"] is False


@patch("server.get_camera")
def test_status_with_camera(mock_get_camera, client):
    mock_camera = MagicMock()
    mock_camera.get_summary.return_value = MagicMock(
        __str__=lambda self: "Model: Canon EOS 5D Mark II\nSerial Number: abc123\nVersion: 3-1.1.0\n"
    )
    mock_get_camera.return_value = mock_camera
    resp = client.get("/api/status")
    data = json.loads(resp.data)
    assert data["connected"] is True
    assert data["model"] == "Canon EOS 5D Mark II"


@patch("server.get_camera")
def test_camera_all_no_camera(mock_get_camera, client):
    mock_get_camera.return_value = None
    resp = client.get("/api/camera")
    assert resp.status_code == 404
    data = json.loads(resp.data)
    assert data["connected"] is False


@patch("server.get_camera")
def test_camera_all_with_data(mock_get_camera, client):
    mock_camera = MagicMock()
    mock_camera.get_summary.return_value = MagicMock(
        __str__=lambda self: "Model: Canon EOS 5D Mark II\nSerial Number: abc123\nVersion: 3-1.1.0\n"
    )

    def mock_get_single_config(key):
        values = {
            "/main/status/batterylevel": "100%",
            "/main/status/shuttercounter": "8360",
            "/main/settings/ownername": "Alex",
            "/main/settings/artist": "Alex V",
            "/main/settings/copyright": "(c) 2026",
        }
        mock_config = MagicMock()
        mock_config.get_value.return_value = values.get(key, "")
        return mock_config

    mock_camera.get_single_config = mock_get_single_config
    mock_get_camera.return_value = mock_camera

    resp = client.get("/api/camera")
    data = json.loads(resp.data)
    assert data["connected"] is True
    assert data["overview"]["model"] == "Canon EOS 5D Mark II"
    assert data["overview"]["battery"] == "100%"
    assert data["shutter"]["count"] == 8360
    assert data["shutter"]["ratedLifespan"] == 150000
    assert data["shutter"]["wearPercent"] == 5.6
    assert data["user"]["owner"] == "Alex"
    assert data["user"]["artist"] == "Alex V"
    assert data["user"]["copyright"] == "(c) 2026"


@patch("server.get_camera")
def test_post_user_writes_and_reads_back(mock_get_camera, client):
    mock_camera = MagicMock()
    written = {}

    def mock_get_single_config(key):
        mock_config = MagicMock()
        mock_config.get_value.return_value = written.get(key, "")
        def set_value(v):
            mock_config._pending_value = v
        mock_config.set_value = set_value
        return mock_config

    def mock_set_single_config(key, config):
        written[key] = config._pending_value

    mock_camera.get_single_config = mock_get_single_config
    mock_camera.set_single_config = mock_set_single_config
    mock_get_camera.return_value = mock_camera

    resp = client.post(
        "/api/camera/user",
        data=json.dumps({"owner": "New Owner", "artist": "New Artist"}),
        content_type="application/json",
    )
    data = json.loads(resp.data)
    assert data["owner"] == "New Owner"
    assert data["artist"] == "New Artist"
    assert data["copyright"] == ""


@patch("server.get_camera")
def test_post_user_no_body_returns_400(mock_get_camera, client):
    resp = client.post("/api/camera/user", content_type="application/json")
    assert resp.status_code == 400
```

- [ ] **Step 2: Run tests**

Run: `cd ~/pt/canon && python -m pytest tests/test_server.py -v`
Expected: All 6 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/test_server.py
git commit -m "test: add server API tests with mocked gphoto2"
```

---

## Chunk 2: Frontend

### Task 4: HTML structure and CSS design system

**Files:**
- Create: `canon/static/index.html`
- Create: `canon/static/css/style.css`

- [ ] **Step 1: Create index.html**

The HTML should contain:
- App header with title "ShutterCheck"
- A main card container (max-width 600px, centered)
- **Disconnected state:** app name + "Checking camera..." message
- **Connected state:** three-tab segmented control (Overview / Shutter / User)
- **Overview tab:** 4 data rows (Model, Serial, Battery, Firmware) — battery row includes a progress bar div
- **Shutter tab:** shutter count (large number), optional live view count, wear text, progress bar
- **User tab:** 3 text inputs (Owner, Artist, Copyright) with max lengths, Save button
- **Share button:** "Copy Report" in the header area
- **Toast container** for error messages
- Script tags loading `js/camera-db.js` and `js/app.js` as ES modules

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ShutterCheck</title>
    <link rel="stylesheet" href="/static/css/style.css">
</head>
<body>
    <div id="app">
        <!-- Disconnected state -->
        <div id="disconnected" class="card">
            <div class="app-header">
                <h1>ShutterCheck</h1>
                <p class="subtitle">Canon EOS Camera Inspector</p>
            </div>
            <div class="status-message">
                <div id="status-icon" class="spinner"></div>
                <p id="status-text">Checking camera...</p>
            </div>
        </div>

        <!-- Connected state -->
        <div id="connected" class="card" hidden>
            <div class="app-header">
                <h1>ShutterCheck</h1>
                <button id="copy-report" class="btn-secondary" title="Copy report to clipboard">Copy Report</button>
            </div>

            <!-- Tabs -->
            <div class="tabs">
                <button class="tab active" data-tab="overview">Overview</button>
                <button class="tab" data-tab="shutter">Shutter</button>
                <button class="tab" data-tab="user">User</button>
            </div>

            <!-- Overview Tab -->
            <div id="tab-overview" class="tab-content active">
                <div class="field">
                    <span class="field-label">Model</span>
                    <span class="field-value" id="val-model">—</span>
                </div>
                <div class="field">
                    <span class="field-label">Serial Number</span>
                    <span class="field-value" id="val-serial">—</span>
                </div>
                <div class="field">
                    <span class="field-label">Battery Level</span>
                    <div class="field-value-row">
                        <span id="val-battery">—</span>
                        <div class="progress-bar-container">
                            <div id="battery-bar" class="progress-bar"></div>
                        </div>
                    </div>
                </div>
                <div class="field">
                    <span class="field-label">Firmware Version</span>
                    <span class="field-value" id="val-firmware">—</span>
                </div>
            </div>

            <!-- Shutter Tab -->
            <div id="tab-shutter" class="tab-content">
                <div class="shutter-count-display">
                    <span class="shutter-label">Shutter Count</span>
                    <span class="shutter-value" id="val-shutter-count">—</span>
                    <span class="shutter-unit">actuations</span>
                </div>
                <div class="field" id="wear-section" hidden>
                    <p class="wear-text" id="val-wear-text"></p>
                    <div class="progress-bar-container large">
                        <div id="wear-bar" class="progress-bar"></div>
                    </div>
                </div>
            </div>

            <!-- User Tab -->
            <div id="tab-user" class="tab-content">
                <div class="field-input">
                    <label for="input-owner">Owner</label>
                    <input type="text" id="input-owner" maxlength="31" placeholder="Up to 31 ASCII characters">
                </div>
                <div class="field-input">
                    <label for="input-artist">Artist</label>
                    <input type="text" id="input-artist" maxlength="63" placeholder="Up to 63 ASCII characters">
                </div>
                <div class="field-input">
                    <label for="input-copyright">Copyright</label>
                    <input type="text" id="input-copyright" maxlength="63" placeholder="Up to 63 ASCII characters">
                </div>
                <button id="save-user" class="btn-primary">Save to Camera</button>
            </div>
        </div>

        <!-- Toast -->
        <div id="toast" class="toast" hidden></div>
    </div>

    <script type="module" src="/static/js/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create style.css**

Anthropic design system. Key elements:
- Body: `background: #FAFAF7`, Inter/system font
- `.card`: white bg, `box-shadow: 0 1px 3px rgba(0,0,0,0.08)`, `border-radius: 12px`, `max-width: 600px`, centered, `padding: 32px`
- `.tabs`: flex row, gap 0, pill-style segmented control with `border-radius: 8px`, `background: #f0ede8`
- `.tab`: padding 10px 20px, no border; `.tab.active`: white bg, shadow, `color: #D97757`
- `.field`: flex column, `padding: 16px 0`, `border-bottom: 1px solid #f0f0f0`
- `.field-label`: `color: #888`, `font-size: 13px`, `text-transform: uppercase`, `letter-spacing: 0.5px`
- `.field-value`: `font-size: 18px`, `font-weight: 600`, `color: #1a1a1a`
- `.btn-primary`: `background: #D97757`, white text, `border-radius: 8px`, `padding: 12px 24px`
- `.btn-secondary`: outlined, `border: 1px solid #D97757`, `color: #D97757`
- `.progress-bar-container`: `background: #f0ede8`, `border-radius: 4px`, `height: 8px`
- `.progress-bar`: `border-radius: 4px`, `height: 100%`, transitions
- `.progress-bar.green`: `background: #4ade80`; `.yellow`: `#facc15`; `.red`: `#f87171`
- `.shutter-value`: `font-size: 48px`, `font-weight: 700`
- `.spinner`: CSS-only spinning animation
- `.toast`: fixed bottom center, `background: #1a1a1a`, white text, `border-radius: 8px`, slide-up animation
- `.tab-content`: hidden by default; `.tab-content.active`: visible
- Responsive: card goes full-width below 640px

Write the full CSS implementing all of the above.

- [ ] **Step 3: Verify page loads**

Run: `cd ~/pt/canon && python3 -c "from flask import Flask; app = Flask(__name__, static_folder='static', static_url_path='/static'); app.route('/')(lambda: app.send_static_file('index.html')); app.run(port=5001)" &`
Then open `http://localhost:5001` in browser — should see the disconnected state with spinner and "Checking camera..."
Then: `kill %1`

- [ ] **Step 4: Commit**

```bash
git add static/index.html static/css/style.css
git commit -m "feat: add HTML structure and Anthropic CSS design system"
```

---

### Task 5: Frontend application logic (app.js)

**Files:**
- Create: `canon/static/js/app.js`

- [ ] **Step 1: Write app.js**

The app.js module handles:
1. **State machine:** `disconnected` → `connecting` → `connected`. Polls `/api/status` every 3s when disconnected.
2. **Tab switching:** click handlers on `.tab` buttons, toggle `.active` on tabs and `.tab-content` divs.
3. **Data loading:** On connect, fetch `/api/camera` once, populate all three tabs.
4. **Overview tab rendering:** Set text content for model, serial, firmware, battery. Set battery bar width and color class.
5. **Shutter tab rendering:** Format count with `toLocaleString()`. Calculate wear %, set wear text and bar.
6. **User tab rendering:** Set input values from API data. Save button POSTs to `/api/camera/user` with confirm dialog.
7. **Copy Report:** Build text string from current data, copy to clipboard via `navigator.clipboard.writeText()`.
8. **Toast notifications:** Show/hide with auto-dismiss after 5s.
9. **Error handling:** API failures show toast, set state to disconnected, resume polling.

```javascript
// app.js

let state = "disconnected"; // disconnected | connecting | connected
let cameraData = null;
let pollTimer = null;

// --- DOM refs ---
const $disconnected = document.getElementById("disconnected");
const $connected = document.getElementById("connected");
const $statusIcon = document.getElementById("status-icon");
const $statusText = document.getElementById("status-text");
const $toast = document.getElementById("toast");

// Overview
const $model = document.getElementById("val-model");
const $serial = document.getElementById("val-serial");
const $battery = document.getElementById("val-battery");
const $batteryBar = document.getElementById("battery-bar");
const $firmware = document.getElementById("val-firmware");

// Shutter
const $shutterCount = document.getElementById("val-shutter-count");
const $wearSection = document.getElementById("wear-section");
const $wearText = document.getElementById("val-wear-text");
const $wearBar = document.getElementById("wear-bar");

// User
const $owner = document.getElementById("input-owner");
const $artist = document.getElementById("input-artist");
const $copyright = document.getElementById("input-copyright");
const $saveUser = document.getElementById("save-user");

// --- API ---
async function api(path, options = {}) {
  const resp = await fetch(path, options);
  const data = await resp.json();
  if (!resp.ok && !data.connected) throw new Error(data.error || "API error");
  return data;
}

// --- State transitions ---
function setState(newState) {
  state = newState;
  $disconnected.hidden = state === "connected";
  $connected.hidden = state !== "connected";

  if (state === "disconnected") {
    $statusIcon.className = "spinner";
    $statusText.textContent = "Checking camera...";
    startPolling();
  } else if (state === "connected") {
    stopPolling();
  }
}

function startPolling() {
  stopPolling();
  pollTimer = setInterval(checkCamera, 3000);
  checkCamera();
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

async function checkCamera() {
  try {
    const status = await api("/api/status");
    if (status.connected) {
      await loadCameraData();
    }
  } catch {
    // Still disconnected, keep polling
  }
}

async function loadCameraData() {
  try {
    const isReconnect = state === "connected";
    cameraData = await api("/api/camera");
    renderOverview();
    renderShutter();
    if (!isReconnect) renderUser(); // Don't overwrite in-progress user edits on reconnect
    setState("connected");
  } catch (e) {
    showToast("Failed to read camera: " + e.message);
    setState("disconnected");
  }
}

// --- Render functions ---
function renderOverview() {
  const o = cameraData.overview;
  $model.textContent = o.model;
  $serial.textContent = o.serial || "—";
  $firmware.textContent = o.firmware || "—";
  $battery.textContent = o.battery;

  // Battery bar
  const pct = parseInt(o.battery);
  if (!isNaN(pct)) {
    $batteryBar.style.width = pct + "%";
    $batteryBar.className = "progress-bar " + (pct >= 50 ? "green" : pct >= 20 ? "yellow" : "red");
  } else {
    $batteryBar.style.width = "0%";
  }
}

function renderShutter() {
  const s = cameraData.shutter;
  $shutterCount.textContent = s.count !== null ? s.count.toLocaleString() : "—";

  if (s.ratedLifespan && s.wearPercent !== null) {
    $wearSection.hidden = false;
    $wearText.textContent = `Shutter wear is ${s.wearPercent}% of its rated lifespan of ${s.ratedLifespan.toLocaleString()} actuations.`;
    $wearBar.style.width = Math.min(s.wearPercent, 100) + "%";
    $wearBar.className = "progress-bar " + (s.wearPercent < 33 ? "green" : s.wearPercent < 66 ? "yellow" : "red");
  } else {
    $wearSection.hidden = true;
  }
}

function renderUser() {
  const u = cameraData.user;
  $owner.value = u.owner;
  $artist.value = u.artist;
  $copyright.value = u.copyright;
}

// --- Tabs ---
document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    document.querySelectorAll(".tab-content").forEach((c) => c.classList.remove("active"));
    tab.classList.add("active");
    document.getElementById("tab-" + tab.dataset.tab).classList.add("active");
  });
});

// --- Save user fields ---
$saveUser.addEventListener("click", async () => {
  if (!confirm("Write these values to camera?")) return;

  $saveUser.disabled = true;
  $saveUser.textContent = "Saving...";
  try {
    const result = await api("/api/camera/user", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        owner: $owner.value,
        artist: $artist.value,
        copyright: $copyright.value,
      }),
    });
    cameraData.user = result;
    renderUser();
    showToast("Saved to camera");
  } catch (e) {
    showToast("Failed to save: " + e.message);
  } finally {
    $saveUser.disabled = false;
    $saveUser.textContent = "Save to Camera";
  }
});

// --- Copy report ---
document.getElementById("copy-report").addEventListener("click", async () => {
  if (!cameraData) return;
  const o = cameraData.overview;
  const s = cameraData.shutter;
  let report = `${o.model}\nSerial: ${o.serial}\nFirmware: ${o.firmware}\nBattery: ${o.battery}`;
  if (s.count !== null) {
    report += `\nShutter Count: ${s.count.toLocaleString()} actuations`;
    if (s.wearPercent !== null && s.ratedLifespan) {
      report += `\nShutter Wear: ${s.wearPercent}% of ${s.ratedLifespan.toLocaleString()} rated lifespan`;
    }
  }
  try {
    await navigator.clipboard.writeText(report);
    showToast("Report copied to clipboard");
  } catch {
    showToast("Failed to copy");
  }
});

// --- Toast ---
let toastTimer = null;
function showToast(msg) {
  $toast.textContent = msg;
  $toast.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => ($toast.hidden = true), 5000);
}

// --- Init ---
setState("disconnected");
```

- [ ] **Step 2: Test full app with server running**

Run: `cd ~/pt/canon && sudo python3 server.py`
Open `http://localhost:5000` in any browser.
Expected:
- If camera connected: shows Overview tab with model, serial, battery, firmware
- Switch to Shutter tab: shows count and wear bar
- Switch to User tab: shows editable fields
- "Copy Report" copies text to clipboard
- If no camera: shows "Checking camera..." with spinner, polls every 3s

- [ ] **Step 3: Commit**

```bash
git add static/js/app.js
git commit -m "feat: add frontend application logic with state machine and tab UI"
```

---

## Chunk 3: Integration and polish

### Task 6: End-to-end integration test

- [ ] **Step 1: Run all backend tests**

Run: `cd ~/pt/canon && python -m pytest tests/ -v`
Expected: All tests pass (camera_db + server tests).

- [ ] **Step 2: Manual e2e test with real camera**

1. Connect Canon EOS camera via USB
2. Run: `sudo python3 server.py`
3. Browser opens to `http://localhost:5000`
4. Verify Overview tab shows correct model, serial, battery, firmware
5. Verify Shutter tab shows count and wear percentage
6. Verify User tab shows current owner/artist/copyright values
7. Try writing a test value to Owner field, click Save, verify it persists
8. Click Copy Report, paste somewhere, verify text format
9. Unplug camera — verify app shows "Checking camera..." and polls
10. Replug camera — verify app reconnects and shows data

- [ ] **Step 3: Commit any fixes from e2e testing**

```bash
git add server.py camera_db.py static/
git commit -m "fix: integration fixes from e2e testing"
```

---

### Task 7: Clean up test file and finalize

**Files:**
- Remove: `canon/test-webusb.html` (obsolete — WebUSB approach abandoned)
- Remove: `canon/grab-camera.sh` (development utility, no longer needed)

- [ ] **Step 1: Remove obsolete files**

```bash
rm canon/test-webusb.html canon/grab-camera.sh
```

- [ ] **Step 2: Final commit**

```bash
git add -A
git commit -m "chore: remove obsolete WebUSB test files"
```

---

## Summary

| Task | What | Files |
|------|------|-------|
| 1 | Camera DB + tests | `camera_db.py`, `tests/test_camera_db.py`, `requirements.txt` |
| 2 | Flask server + gphoto2 | `server.py` |
| 3 | Server unit tests | `tests/test_server.py` |
| 4 | HTML + CSS | `static/index.html`, `static/css/style.css` |
| 5 | Frontend app logic | `static/js/app.js` |
| 6 | E2E integration test | — |
| 7 | Cleanup | remove `test-webusb.html`, `grab-camera.sh` |
