# Canon ShutterCheck Web App — Design Spec

## Overview

A free, local web application that reads Canon EOS camera data over USB — shutter count, battery level, firmware, serial number, and user metadata (owner/artist/copyright). Modeled after [ShutterCheck.app](https://shuttercheck.app/) but running entirely in the browser + a local Python companion server.

## Architecture

```
┌─────────────────────┐     localhost:5000     ┌──────────────────────┐
│   Web Frontend      │ ◄──── REST API ──────► │  Python Server       │
│   (static HTML/JS)  │                        │  (Flask + gphoto2)   │
│   Anthropic style   │                        │  kills ptpcamerad    │
│   3 tabs            │                        │  claims USB/PTP      │
└─────────────────────┘                        └──────────────────────┘
                                                       │ USB/PTP
                                                       ▼
                                               ┌──────────────────┐
                                               │  Canon EOS       │
                                               │  Camera           │
                                               └──────────────────┘
```

### Why not WebUSB?

WebUSB was the original plan (zero-install, browser-native). Testing proved it's unworkable on macOS:

- macOS `ptpcamerad` (system daemon) auto-claims all PTP cameras via USB
- It's managed by `launchd` and respawns instantly when killed
- WebUSB cannot access devices already claimed by a kernel driver
- Chrome's USB device picker doesn't show claimed devices

The companion server approach works because `gphoto2` (via `libgphoto2`) can detach kernel drivers when run as root.

### Validated with real hardware

All data points confirmed readable from a Canon EOS 5D Mark II:

| Field | Source | Confirmed |
|-------|--------|-----------|
| Model | `--summary` → Model | Yes |
| Serial Number | `--summary` → Serial Number | Yes |
| Firmware Version | `--summary` → Version | Yes |
| Battery Level | `--get-config /main/status/batterylevel` | Yes (100%) |
| Shutter Count | `--get-config /main/status/shuttercounter` | Yes (8,360) |
| Owner Name | `--get-config /main/settings/ownername` | Yes (writable) |
| Artist | `--get-config /main/settings/artist` | Yes (writable) |
| Copyright | `--get-config /main/settings/copyright` | Yes (writable) |

## Backend: Python Companion Server

### Technology

- **Python 3** + **Flask** (lightweight, no overhead)
- **python-gphoto2** bindings (direct libgphoto2 access, no subprocess shelling)
- Runs with `sudo` to detach macOS kernel driver

### REST API

```
GET  /api/status          → { connected: bool, model?: string }
GET  /api/camera          → full camera info (overview + shutter + user)
GET  /api/camera/overview → { model, serial, firmware, battery }
GET  /api/camera/shutter  → { count, ratedLifespan, wearPercent }
GET  /api/camera/user     → { owner, artist, copyright }
POST /api/camera/user     → { owner?, artist?, copyright? } → write to camera
```

### Startup sequence

1. Kill `ptpcamerad` via `kill -9 $(pgrep ptpcamerad)`
2. Attempt `launchctl bootout gui/<uid>/com.apple.ptpcamerad` to prevent respawn (best-effort, may require elevated privileges)
3. Initialize gphoto2, detect Canon camera
4. Open PTP session
5. Serve REST API on `localhost:5000` (Flask with `debug=False`)
6. Auto-open browser to `http://localhost:5000`
7. Register `SIGINT`/`SIGTERM` handler to close gphoto2 session cleanly on shutdown

### Connection lifecycle

- gphoto2 context is re-initialized per API request (avoids stale-handle issues on unplug/replug)
- If no camera on startup: server starts anyway, returns `{ connected: false }` — frontend polls `/api/status` every 3 seconds
- On camera disconnect mid-session: gphoto2 call fails, server catches error, next request re-detects
- If `ptpcamerad` reclaims between requests: server re-kills it before each gphoto2 operation (background check)

### Error handling

- If no camera found: return `{ connected: false }`, frontend shows "Connect your camera"
- If camera disconnects: detect via failed gphoto2 call, return error, frontend shows reconnect state
- All errors return JSON with `{ error: string }` and appropriate HTTP status

### POST /api/camera/user response

Returns the values read back from camera after writing, confirming what was actually stored (Canon may silently truncate strings exceeding max length):
```json
{ "owner": "Alex V", "artist": "", "copyright": "" }
```

### Camera database

Static lookup table for rated shutter lifespans:

| Model | Rated Lifespan |
|-------|---------------|
| EOS 5D Mark II | 150,000 |
| EOS 5D Mark III | 150,000 |
| EOS 5D Mark IV | 150,000 |
| EOS 6D | 100,000 |
| EOS 6D Mark II | 100,000 |
| EOS 7D | 150,000 |
| EOS 7D Mark II | 200,000 |
| EOS 60D | 100,000 |
| EOS 70D | 100,000 |
| EOS 80D | 100,000 |

Unknown models: show all available data, skip lifespan percentage.

Model name matching: normalize by stripping "Canon " prefix before lookup (gphoto2 may report "Canon EOS 5D Mark II" while DB keys use "EOS 5D Mark II").

## Frontend: Static Web UI

### Technology

- Vanilla HTML/JS/CSS (no build step, no framework)
- ES modules via `<script type="module">`
- Served by the Flask backend at `/` (same origin, no CORS needed — do not open via `file://`)

### File structure

```
canon/
  server.py               — Flask + gphoto2 backend
  requirements.txt         — python-gphoto2, flask
  static/
    index.html             — Single page
    css/style.css           — Anthropic design system
    js/
      app.js               — UI state machine, tab switching, API calls
      camera-db.js          — Model → lifespan lookup
```

### Design: Anthropic style

- **Background:** warm off-white `#FAFAF7`
- **Card:** white, subtle shadow, 12px border-radius, max-width 600px, centered
- **Accent:** Anthropic terracotta `#D97757` (buttons, active tab, progress bar)
- **Typography:** Inter / system font stack
- **Tabs:** pill-style segmented control (Overview / Shutter / User)
- **Data rows:** label in muted gray above, bold value below, thin divider between rows

### Tab: Overview

| Field | Display |
|-------|---------|
| Model | Text, e.g. "Canon EOS 5D Mark II" |
| Serial Number | Text |
| Battery Level | Text + colored bar (green ≥50%, yellow ≥20%, red <20%) |
| Firmware Version | Text |

### Tab: Shutter

| Field | Display |
|-------|---------|
| Shutter Count | Large formatted number (e.g. "8,360") |
| Shutter Count Incl. Live View | Same format (shown only if camera reports a separate value via gphoto2 — not validated on 5D Mark II, may be available on newer models) |
| Wear indicator | "Shutter wear is X% of its rated lifespan of Y actuations" |
| Progress bar | Colored: green <33%, yellow 33-66%, red >66% |

### Tab: User

| Field | Display |
|-------|---------|
| Owner | Text input, max 31 ASCII chars |
| Artist | Text input, max 63 ASCII chars |
| Copyright | Text input, max 63 ASCII chars |
| Save button | Writes values to camera via `POST /api/camera/user` |
| Confirm dialog | "Write these values to camera?" before saving |

### UI States

```
disconnected → connecting → connected (tabs) → disconnected
                                    ↓
                              error (toast)
```

- **Disconnected:** centered card with app name + "Connect Camera" button
- **Connecting:** spinner
- **Connected:** tabbed data view, auto-refreshes on reconnect
- **Error:** toast notification with message, auto-dismiss after 5s
- **Browser incompatibility:** N/A (all browsers work since it's localhost HTTP)

### Share/Export

"Copy Report" button copies a text summary to clipboard:
```
Canon EOS 5D Mark II
Serial: db8cf2474f56473991a82df2f72e5bf
Firmware: 3-1.1.0
Battery: 100%
Shutter Count: 8,360 actuations
Shutter Wear: 5.6% of 150,000 rated lifespan
```

## Supported cameras (initial)

10 popular Canon EOS models. The server will attempt to read data from any Canon camera detected by gphoto2 — the database only affects the "rated lifespan" display.

## Non-goals (v1)

- No monetization / paywall
- No cloud / remote reports
- No shutter life histogram database
- No blog / marketing pages
- No multi-camera simultaneous support
- No Windows/Linux — macOS only for v1 (ptpcamerad handling is macOS-specific)

## Installation & Usage

```bash
# One-time setup
cd canon
pip install -r requirements.txt
brew install gphoto2 libgphoto2  # if not already installed

# Run (requires sudo for USB access)
sudo python3 server.py
# Opens http://localhost:5000 automatically
```

## Security considerations

- Server binds to `localhost` only — not exposed to network
- No data leaves the machine
- No telemetry, cookies, or analytics
- `sudo` is required only for USB device access (killing ptpcamerad + claiming interface)
