// app.js — Camera Inspector

let state = "disconnected";
let cameraData = null;
let pollTimer = null;

// --- DOM refs ---
const $title = document.getElementById("camera-title");
const $statusMessage = document.getElementById("status-message");
const $fields = document.getElementById("fields-container");
const $toast = document.getElementById("toast");
const $copyReport = document.getElementById("copy-report");
const $saveUser = document.getElementById("save-user");

// Battery
const $batteryDisplay = document.getElementById("battery-display");
const $batteryText = document.getElementById("val-battery");
const $batSegs = [
  document.getElementById("bat-seg-1"),
  document.getElementById("bat-seg-2"),
  document.getElementById("bat-seg-3"),
  document.getElementById("bat-seg-4"),
];

// Fields
const $firmware = document.getElementById("val-firmware");
const $shutter = document.getElementById("val-shutter");
const $wearRow = document.getElementById("wear-row");
const $wearBar = document.getElementById("wear-bar");
const $wearText = document.getElementById("val-wear-text");
const $serial = document.getElementById("val-serial");
const $lens = document.getElementById("val-lens");
const $datetime = document.getElementById("val-datetime");
const $owner = document.getElementById("input-owner");
const $artist = document.getElementById("input-artist");
const $copyright = document.getElementById("input-copyright");

// --- API ---
async function api(path, options = {}) {
  const resp = await fetch(path, options);
  const data = await resp.json();
  if (!resp.ok && !data.connected) throw new Error(data.error || "API error");
  return data;
}

// --- State ---
function setState(newState) {
  state = newState;
  if (state === "disconnected") {
    $title.textContent = "Camera Not Connected";
    $statusMessage.hidden = false;
    $fields.hidden = true;
    $batteryDisplay.hidden = true;
    $copyReport.hidden = true;
    $saveUser.hidden = true;
    clearFields();
    startPolling();
  } else if (state === "connected") {
    $statusMessage.hidden = true;
    $fields.hidden = false;
    $copyReport.hidden = false;
    $saveUser.hidden = false;
    stopPolling();
  }
}

function clearFields() {
  $firmware.textContent = "";
  $shutter.textContent = "";
  $serial.textContent = "";
  $lens.textContent = "";
  $datetime.textContent = "";
  $owner.value = "";
  $artist.value = "";
  $copyright.value = "";
  $wearRow.hidden = true;
  $batSegs.forEach(s => { s.className = "battery-seg"; });
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
    // keep polling
  }
}

async function loadCameraData() {
  try {
    const wasConnected = state === "connected";
    cameraData = await api("/api/camera");
    renderData(wasConnected);
    setState("connected");
  } catch (e) {
    showToast("Failed to read camera: " + e.message);
    setState("disconnected");
  }
}

// --- Render ---
function renderData(skipUserFields) {
  const o = cameraData.overview;
  const s = cameraData.shutter;
  const u = cameraData.user;

  $title.textContent = o.model || "Unknown Camera";
  $firmware.textContent = o.firmware || "";
  $shutter.textContent = s.count !== null ? s.count.toLocaleString() : "";
  $serial.textContent = o.serial || "";
  $lens.textContent = o.lens || "";
  $datetime.textContent = o.datetime || "";
  // copyright rendered in user fields section below

  // Wear bar
  if (s.ratedLifespan && s.wearPercent !== null) {
    $wearRow.hidden = false;
    $wearBar.style.width = Math.min(s.wearPercent, 100) + "%";
    $wearBar.className = "progress-bar " + (s.wearPercent < 33 ? "green" : s.wearPercent < 66 ? "yellow" : "red");
    $wearText.textContent = `${s.wearPercent}% of ${s.ratedLifespan.toLocaleString()}`;
  } else {
    $wearRow.hidden = true;
  }

  // Battery — 4 segments
  const pct = parseInt(o.battery);
  if (!isNaN(pct)) {
    $batteryDisplay.hidden = false;
    $batteryText.textContent = "Battery Level : " + o.battery;
    const filledCount = pct >= 88 ? 4 : pct >= 63 ? 3 : pct >= 38 ? 2 : pct >= 10 ? 1 : 0;
    const color = pct >= 50 ? "green" : pct >= 20 ? "yellow" : "red";
    $batSegs.forEach((seg, i) => {
      seg.className = "battery-seg" + (i < filledCount ? ` filled ${color}` : "");
    });
  } else {
    $batteryDisplay.hidden = true;
  }

  // User fields — don't overwrite if editing
  if (!skipUserFields) {
    $owner.value = u.owner || "";
    $artist.value = u.artist || "";
    $copyright.value = u.copyright || "";
  }
}

// --- Save user fields ---
$saveUser.addEventListener("click", async () => {
  if (!confirm("Write Owner, Artist and Copyright to camera?")) return;
  $saveUser.disabled = true;
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
    showToast("Saved to camera");
  } catch (e) {
    showToast("Failed to save: " + e.message);
  } finally {
    $saveUser.disabled = false;
  }
});

// --- Copy report ---
$copyReport.addEventListener("click", async () => {
  if (!cameraData) return;
  const o = cameraData.overview;
  const s = cameraData.shutter;
  const u = cameraData.user;
  let report = o.model;
  report += `\nFirmware: ${o.firmware}`;
  if (s.count !== null) report += `\nShutter Count: ${s.count.toLocaleString()} actuations`;
  if (s.wearPercent !== null && s.ratedLifespan) report += `\nShutter Wear: ${s.wearPercent}% of ${s.ratedLifespan.toLocaleString()} rated lifespan`;
  report += `\nSerial: ${o.serial}`;
  if (o.lens) report += `\nLens: ${o.lens}`;
  report += `\nBattery: ${o.battery}`;
  if (o.datetime) report += `\nDate/Time: ${o.datetime}`;
  if (u.owner) report += `\nOwner: ${u.owner}`;
  if (u.artist) report += `\nArtist: ${u.artist}`;
  if (u.copyright) report += `\nCopyright: ${u.copyright}`;
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
