# Camera Inspector

A local web app that reads Canon EOS camera data over USB — shutter count, battery level, serial number, lens info, firmware version, and editable user metadata.

![Camera Inspector](https://img.shields.io/badge/platform-macOS-lightgrey) ![Python](https://img.shields.io/badge/python-3.10+-blue) ![License](https://img.shields.io/badge/license-MIT-green)

## Features

- **Shutter Count** — read actuations with wear percentage against rated lifespan
- **Camera Info** — model, serial number, firmware version, battery level, lens name, date/time
- **User Settings** — read and write Owner Name, Artist, and Copyright fields on camera
- **Copy Report** — one-click copy of all camera info to clipboard
- **Battery Display** — 4-segment battery indicator with level percentage
- **Zero config** — auto-detects camera, auto-finds free port, auto-opens browser

## Supported Cameras

Any Canon EOS camera supported by [libgphoto2](http://gphoto.org/proj/libgphoto2/support.php). Shutter lifespan data included for:

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

Other Canon models will show all data except shutter wear percentage.

## Requirements

- **macOS** (required — uses gphoto2 to bypass macOS's PTP camera daemon)
- **Python 3.10+**
- **Homebrew** (for installing gphoto2)

## Installation

```bash
git clone https://github.com/CashQ/camerainspector.git
cd camerainspector

# Install system dependency
brew install gphoto2 libgphoto2

# Create virtual environment and install Python packages
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

1. Connect your Canon EOS camera via USB
2. Close any other app using the camera (Image Capture, EOS Utility, Lightroom, etc.)
3. Run:

```bash
.venv/bin/python server.py
```

The server will:
- Request `sudo` access (needed to release macOS's grip on the USB camera)
- Kill the `ptpcamerad` daemon that blocks camera access
- Find a free port (5050-5100)
- Open your browser automatically

## How It Works

```
┌─────────────────────┐    localhost    ┌──────────────────────┐
│   Web Browser       │ ◄── REST API ─► │  Python Server       │
│   (any browser)     │                 │  Flask + libgphoto2  │
└─────────────────────┘                 └──────────────────────┘
                                                │ USB / PTP
                                                ▼
                                        ┌──────────────────┐
                                        │  Canon EOS       │
                                        │  Camera          │
                                        └──────────────────┘
```

**Why does it need `sudo`?**

On macOS, a system daemon called `ptpcamerad` automatically claims any PTP camera connected via USB. This prevents other applications (including gphoto2) from communicating with the camera. The server needs root access to kill this daemon and claim the USB device.

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Web UI |
| `/api/status` | GET | Connection status |
| `/api/camera` | GET | All camera data |
| `/api/camera/overview` | GET | Model, serial, firmware, battery |
| `/api/camera/shutter` | GET | Shutter count and wear |
| `/api/camera/user` | GET | Owner, artist, copyright |
| `/api/camera/user` | POST | Write owner, artist, copyright |

## Development

```bash
# Run tests
.venv/bin/python -m pytest tests/ -v

# Project structure
├── server.py          # Flask + gphoto2 backend
├── camera_db.py       # Camera model → rated lifespan lookup
├── requirements.txt   # Python dependencies
├── static/
│   ├── index.html     # Single-page UI
│   ├── css/style.css  # Styling
│   └── js/app.js      # Frontend logic
└── tests/
    ├── test_camera_db.py
    └── test_server.py
```

## Privacy

- Runs entirely on your machine — no data leaves localhost
- No analytics, telemetry, cookies, or tracking
- No internet connection required (after installation)

## License

MIT
