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
