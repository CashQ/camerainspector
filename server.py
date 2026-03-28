# server.py — Camera Inspector backend
# Reads Canon EOS camera data over USB via libgphoto2

import logging
import os
import signal
import socket
import subprocess
import sys
import traceback
import webbrowser
from datetime import datetime as dt, timezone

import gphoto2 as gp
from flask import Flask, jsonify, request, send_from_directory

from camera_db import get_rated_lifespan

# --- Logging ---
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("camerainspector")

app = Flask(__name__, static_folder="static", static_url_path="/static")


# --- ptpcamerad management (macOS only) ---

def kill_ptpcamerad():
    """Kill macOS ptpcamerad to release USB camera. Best-effort, no-op on non-macOS."""
    if sys.platform != "darwin":
        return
    try:
        result = subprocess.run(["pkill", "-9", "ptpcamerad"], capture_output=True, text=True)
        if result.returncode == 0:
            log.info("Killed ptpcamerad")
    except Exception as e:
        log.debug("pkill ptpcamerad: %s", e)
    try:
        uid = os.getuid()
        subprocess.run(
            ["launchctl", "bootout", f"gui/{uid}/com.apple.ptpcamerad"],
            capture_output=True,
        )
    except Exception:
        pass


# --- gphoto2 helpers ---

def get_camera():
    """Detect and return a gphoto2 camera, or None."""
    kill_ptpcamerad()
    try:
        camera = gp.Camera()
        camera.init()
        log.info("Camera connected")
        return camera
    except gp.GPhoto2Error as e:
        log.warning("Camera init failed: %s", e)
        return None


def read_config(camera, name):
    """Read a single config value by short name. Returns string or None."""
    try:
        widget = camera.get_single_config(name)
        value = widget.get_value()
        log.debug("Config '%s' = '%s'", name, value)
        return value
    except gp.GPhoto2Error as e:
        log.debug("Config '%s' unavailable: %s", name, e)
        return None


def read_summary(camera):
    """Parse camera summary text for model, serial, firmware."""
    info = {}
    try:
        raw = str(camera.get_summary())
        for line in raw.split("\n"):
            line = line.strip()
            if line.startswith("Model:"):
                info["model"] = line.split(":", 1)[1].strip()
            elif line.startswith("Serial Number:"):
                info["serial"] = line.split(":", 1)[1].strip()
            elif line.startswith("Version:"):
                info["firmware"] = line.split(":", 1)[1].strip()
        log.info("Summary: %s", info)
    except gp.GPhoto2Error as e:
        log.error("get_summary failed: %s", e)
    return info


def resolve_serial(camera, summary):
    """Get real camera serial number. Tries EOS config first, falls back to PTP summary."""
    return (
        read_config(camera, "eosserialnumber")
        or read_config(camera, "serialnumber")
        or summary.get("serial", "")
    )


def parse_shutter(camera, model):
    """Read shutter count and compute wear stats."""
    raw = read_config(camera, "shuttercounter")
    count = None
    if raw:
        try:
            count = int(raw)
        except ValueError:
            log.warning("Could not parse shutter count: '%s'", raw)
    rated = get_rated_lifespan(model)
    wear = round(count / rated * 100, 1) if count and rated else None
    return {"count": count, "ratedLifespan": rated, "wearPercent": wear}


def format_datetime(camera):
    """Read camera datetime (unix timestamp) and format it."""
    raw = read_config(camera, "datetimeutc") or read_config(camera, "datetime")
    if not raw:
        return ""
    try:
        ts = int(raw)
        return dt.fromtimestamp(ts, tz=timezone.utc).astimezone().strftime(
            "%A, %B %d, %Y, %I:%M:%S %p"
        )
    except (ValueError, OSError):
        return raw


def camera_request(fn):
    """Wrapper: get camera, call fn(camera), release camera. Returns JSON error on failure."""
    camera = get_camera()
    if camera is None:
        return jsonify({"connected": False, "error": "No camera found"}), 404
    try:
        return jsonify(fn(camera))
    except gp.GPhoto2Error as e:
        log.error("gphoto2 error: %s", e)
        return jsonify({"connected": False, "error": str(e)}), 500
    except Exception as e:
        log.error("Unexpected error: %s\n%s", e, traceback.format_exc())
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
        serial = resolve_serial(camera, summary)
        shutter = parse_shutter(camera, model)

        return {
            "connected": True,
            "overview": {
                "model": model,
                "serial": serial,
                "firmware": summary.get("firmware", ""),
                "battery": read_config(camera, "batterylevel") or "Unknown",
                "lens": read_config(camera, "lensname") or "No lens attached",
                "datetime": format_datetime(camera),
            },
            "shutter": shutter,
            "user": {
                "owner": read_config(camera, "ownername") or "",
                "artist": read_config(camera, "artist") or "",
                "copyright": read_config(camera, "copyright") or "",
            },
        }
    return camera_request(read_all)


@app.route("/api/camera/overview")
def api_camera_overview():
    def read_overview(camera):
        summary = read_summary(camera)
        return {
            "model": summary.get("model", "Unknown"),
            "serial": resolve_serial(camera, summary),
            "firmware": summary.get("firmware", ""),
            "battery": read_config(camera, "batterylevel") or "Unknown",
        }
    return camera_request(read_overview)


@app.route("/api/camera/shutter")
def api_camera_shutter():
    def read_shutter(camera):
        summary = read_summary(camera)
        return parse_shutter(camera, summary.get("model", "Unknown"))
    return camera_request(read_shutter)


@app.route("/api/camera/user", methods=["GET"])
def api_camera_user_get():
    def read_user(camera):
        return {
            "owner": read_config(camera, "ownername") or "",
            "artist": read_config(camera, "artist") or "",
            "copyright": read_config(camera, "copyright") or "",
        }
    return camera_request(read_user)


@app.route("/api/camera/user", methods=["POST"])
def api_camera_user_post():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400

    def write_user(camera):
        for config_key, json_key in [("ownername", "owner"), ("artist", "artist"), ("copyright", "copyright")]:
            if json_key in data:
                try:
                    widget = camera.get_single_config(config_key)
                    widget.set_value(str(data[json_key]))
                    camera.set_single_config(config_key, widget)
                    log.info("Wrote '%s' = '%s'", config_key, data[json_key])
                except gp.GPhoto2Error as e:
                    log.error("Write '%s' failed: %s", config_key, e)

        return {
            "owner": read_config(camera, "ownername") or "",
            "artist": read_config(camera, "artist") or "",
            "copyright": read_config(camera, "copyright") or "",
        }
    return camera_request(write_user)


# --- Graceful shutdown ---

def shutdown_handler(signum, frame):
    log.info("Shutting down...")
    sys.exit(0)


# --- Main ---

if __name__ == "__main__":
    # Auto-escalate to root if not already (needed for USB device access on macOS)
    if sys.platform == "darwin" and os.getuid() != 0:
        log.info("Requesting root access for USB camera communication...")
        os.execvp("sudo", ["sudo", sys.executable] + sys.argv)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    kill_ptpcamerad()

    def find_free_port(start=5050, end=5100):
        for port in range(start, end):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                if s.connect_ex(("127.0.0.1", port)) != 0:
                    return port
        log.error("No free port found in range %d-%d", start, end)
        sys.exit(1)

    port = find_free_port()
    log.info("Camera Inspector starting on http://localhost:%d", port)
    webbrowser.open(f"http://localhost:{port}")
    app.run(host="127.0.0.1", port=port, debug=False)
