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
