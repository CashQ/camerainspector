# Camera Inspector

Read Canon EOS camera data over USB — shutter count, battery level, serial number, lens, firmware, and editable user metadata. No cloud, no subscriptions, runs entirely on your Mac.

![macOS](https://img.shields.io/badge/platform-macOS-lightgrey) ![Python](https://img.shields.io/badge/python-3.10+-blue) ![License](https://img.shields.io/badge/license-MIT-green)

## What It Does

Connect your Canon EOS camera via USB and instantly see:

- **Shutter Count** with wear percentage against the camera's rated lifespan
- **Battery Level** with 4-segment visual indicator
- **Serial Number**, firmware version, attached lens, system date/time
- **Owner / Artist / Copyright** fields — read and write directly to camera
- **Copy Report** — one click to copy all camera info to clipboard

## Supported Cameras

Works with any Canon EOS camera supported by [libgphoto2](http://gphoto.org/proj/libgphoto2/support.php). Shutter lifespan data included for: 5D Mark II/III/IV, 6D, 6D Mark II, 7D, 7D Mark II, 60D, 70D, 80D. Other Canon models show all data except wear percentage.

## Quick Start

```bash
# Clone
git clone https://github.com/CashQ/camerainspector.git
cd camerainspector

# Install dependencies
brew install gphoto2 libgphoto2
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Run (auto-requests sudo for USB access)
.venv/bin/python server.py
```

Connect your camera, and it opens automatically in your browser.

## How It Works

```
Browser  ◄── localhost ──►  Python Server  ◄── USB/PTP ──►  Canon Camera
                            (Flask + gphoto2)
```

The server needs `sudo` because macOS locks USB cameras behind a system daemon (`ptpcamerad`). The server kills it to claim the camera — this is safe and the daemon restarts when you unplug.

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/status` | GET | Connection check |
| `/api/camera` | GET | All camera data |
| `/api/camera/overview` | GET | Model, serial, firmware, battery |
| `/api/camera/shutter` | GET | Shutter count and wear |
| `/api/camera/user` | GET | Owner, artist, copyright |
| `/api/camera/user` | POST | Write owner, artist, copyright |

## Project Structure

```
server.py          — Flask + gphoto2 backend
camera_db.py       — Camera model → rated lifespan lookup
requirements.txt   — Python dependencies (flask, gphoto2)
static/
  index.html       — Single-page UI
  css/style.css    — Styling
  js/app.js        — Frontend logic
tests/
  test_camera_db.py
  test_server.py
```

## Privacy

Everything runs locally. No data leaves your machine. No analytics, no tracking, no internet required.

## License

MIT
