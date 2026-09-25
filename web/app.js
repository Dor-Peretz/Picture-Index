const els = {
  folder: document.getElementById("folder"),
  browse: document.getElementById("browse-btn"),
  index: document.getElementById("index-btn"),
  theme: document.getElementById("theme-btn"),
  progress: document.getElementById("progress"),
  indexingBadge: document.getElementById("indexing-badge"),
  progressTitle: document.getElementById("progress-title"),
  progressCount: document.getElementById("progress-count"),
  pause: document.getElementById("pause-btn"),
  cancel: document.getElementById("cancel-btn"),
  bar: document.getElementById("bar-fill"),
  heatmap: document.getElementById("heatmap"),
  heatmapCanvas: document.getElementById("heatmap-canvas"),
  heatmapNote: document.getElementById("heatmap-note"),
  grid: document.getElementById("grid"),
  empty: document.getElementById("empty"),
  more: document.getElementById("more-btn"),
  search: document.getElementById("search"),
  faces: document.getElementById("faces"),
  faceActions: document.getElementById("face-actions"),
  faceMerge: document.getElementById("face-merge"),
  mergeWith: document.getElementById("merge-with"),
  mergeBtn: document.getElementById("merge-btn"),
  personFilter: document.getElementById("person-filter"),
  folderFilter: document.getElementById("folder-filter"),
  groupBy: document.getElementById("group-by"),
  radiusField: document.getElementById("radius-field"),
  radius: document.getElementById("radius"),
  takenFrom: document.getElementById("taken-from"),
  takenTo: document.getElementById("taken-to"),
  detail: document.getElementById("detail"),
  remove: document.getElementById("remove-btn"),
  status: document.getElementById("status-count"),
  picker: document.getElementById("picker"),
  pickerPath: document.getElementById("picker-path"),
  pickerList: document.getElementById("picker-list"),
  pickerBack: document.getElementById("picker-back"),
  pickerUp: document.getElementById("picker-up"),
  pickerCancel: document.getElementById("picker-cancel"),
  pickerChoose: document.getElementById("picker-choose"),
};

const state = {
  photos: [],
  mapPhotos: [],
  hotSpots: [],
  activePlace: null,
  total: 0,
  selectedId: null,
  faceId: null,
  jobId: null,
  scanGeneration: 0,
  paused: false,
  offset: 0,
};

let pickerParent = "";
let pickerHistory = [];
let pickerResolve = null;

function escapeHtml(text) {
  return String(text ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function api(path, options) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail;
    throw new Error(typeof detail === "string" ? detail : "Request failed");
  }
  return data;
}

function formatBytes(size) {
  if (!size && size !== 0) return "";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(0)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function formatWhen(value) {
  if (!value) return "No date";
  return value.replace("T", " ").slice(0, 16);
}

function debounce(fn, ms) {
  let timer = 0;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

async function loadStatus() {
  const data = await api("/api/status");
  els.folder.value = data.folder || "";
  els.status.textContent = `${data.photos} photo${data.photos === 1 ? "" : "s"}`;
  const job = data.job;
  if (job && ["queued", "running", "paused"].includes(job.status)) {
    state.jobId = job.id;
    state.paused = Boolean(job.paused || job.status === "paused");
    els.pause.textContent = state.paused ? "Resume" : "Pause";
    state.scanGeneration += 1;
    pollJob(job.id, state.scanGeneration);
  }
}

function showIndexing(job) {
  const active = job && !["done", "cancelled", "error"].includes(job.status);
  els.progress.classList.toggle("hidden", !active);
  document.body.classList.toggle("indexing", Boolean(active));
  els.index.textContent = active ? "Indexing…" : "Index folder";
  els.index.disabled = Boolean(active);
  document.title = active ? "Indexing · Picture Index" : "Picture Index";
  if (!active) return;
  const paused = Boolean(job.paused || job.status === "paused");
  const total = job.total || 0;
  const done = job.done || 0;
  const finding = !total || job.stage === "Finding photos" || job.stage === "Queued";
  els.bar.parentElement.classList.toggle("indeterminate", !paused && finding);
  els.bar.style.width = !finding && total ? `${Math.min(100, Math.round((done / total) * 100))}%` : "";
  els.indexingBadge.textContent = paused ? "Paused" : "Indexing";
  if (paused) {
    els.progressTitle.textContent = "Indexing is paused";
    els.progressCount.textContent = total ? `${done} / ${total}` : "";
  } else if (finding) {
    els.progressTitle.textContent = "Looking through the folder for photos";
    els.progressCount.textContent = job.offline ? `${job.offline} folders waiting on Dropbox` : "";
  } else {
    const file = job.stage && !/^\d+\s\//.test(job.stage) && !job.stage.startsWith("Done") ? job.stage : "";
    els.progressTitle.textContent = file ? `Reading ${file}` : "Reading photos";
    els.progressCount.textContent = `${done} / ${total}`;
  }
}

async function loadFolders() {
  const data = await api("/api/folders");
  const current = els.folderFilter.value;
  els.folderFilter.innerHTML = `<option value="">All folders</option>${data.folders
    .map((folder) => `<option value="${escapeHtml(folder)}">${escapeHtml(folder)}</option>`)
    .join("")}`;
  els.folderFilter.value = current;
}

function filterParams() {
  const params = new URLSearchParams();
  if (els.search.value.trim()) params.set("q", els.search.value.trim());
  if (els.folderFilter.value) params.set("folder", els.folderFilter.value);
  if (els.takenFrom.value) params.set("taken_from", els.takenFrom.value);
  if (els.takenTo.value) params.set("taken_to", els.takenTo.value);
  if (state.faceId) params.set("face", String(state.faceId));
  return params;
}

function queryString() {
  const params = filterParams();
  params.set("limit", "80");
  params.set("offset", String(state.offset));
  return params.toString();
}

async function loadFaces() {
  const data = await api("/api/faces");
  if (!data.faces.length) {
    state.faceList = [];
    els.faces.innerHTML = `<span class="muted">Faces appear here after indexing.</span>`;
    els.faceActions.classList.add("hidden");
    els.faceMerge.classList.add("hidden");
    return;
  }
  state.faceList = data.faces;
  els.faces.innerHTML = data.faces
    .map(
      (face) => `
      <div class="face-card">
        <button type="button" class="face${face.id === state.faceId ? " selected" : ""}" draggable="true" data-face="${face.id}" title="${escapeHtml(face.label || "Unnamed")} · ${face.count} photos. Drag onto another face to merge.">
          <img draggable="false" src="/api/faces/${face.id}/thumb" alt="" />
        </button>
        <input class="face-name" data-face="${face.id}" value="${escapeHtml(face.label)}" placeholder="Name" />
      </div>`
    )
    .join("");
  const others = data.faces.filter((face) => face.id !== state.faceId);
  els.faceActions.classList.toggle("hidden", !state.faceId);
  els.faceMerge.classList.toggle("hidden", !state.faceId || others.length === 0);
  els.mergeWith.innerHTML = others
    .map((face) => `<option value="${face.id}">${escapeHtml(face.label || "Unnamed")} (${face.count})</option>`)
    .join("");
  const selectedPerson = state.faceId ? String(state.faceId) : "";
  els.personFilter.innerHTML = `<option value="">All people</option>${data.faces
    .map((face) => `<option value="${face.id}">${escapeHtml(face.label || "Unnamed")} (${face.count})</option>`)
    .join("")}`;
  els.personFilter.value = data.faces.some((face) => String(face.id) === selectedPerson) ? selectedPerson : "";
}

async function search(reset) {
  if (reset) {
    state.offset = 0;
    state.photos = [];
    state.activePlace = null;
  }
  const data = await api(`/api/photos?${queryString()}`);
  state.total = data.total;
  state.photos = reset ? data.items : state.photos.concat(data.items);
  state.offset = state.photos.length;
  if (els.groupBy.value === "location") {
    const located = await api(`/api/locations?${filterParams()}`);
    state.mapPhotos = located.items;
  }
  renderGrid();
  els.status.textContent = `${data.total} photo${data.total === 1 ? "" : "s"}`;
  if (state.selectedId && !state.photos.some((photo) => photo.id === state.selectedId)) {
    state.selectedId = null;
    renderDetail(null);
  }
}

function dayLabel(value) {
  if (!value || value === "No date") return "No date";
  const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  const [year, month, day] = value.slice(0, 10).split("-");
  const monthName = months[Number(month) - 1] || month;
  return `${Number(day)} ${monthName} ${year}`;
}

function metersBetween(a, b) {
  const earth = 6371000;
  const toRad = Math.PI / 180;
  const dLat = (b.latitude - a.latitude) * toRad;
  const dLng = (b.longitude - a.longitude) * toRad;
  const lat1 = a.latitude * toRad;
  const lat2 = b.latitude * toRad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return 2 * earth * Math.asin(Math.sqrt(h));
}

function locationGroups(photos, radius) {
  const placed = [];
  const groups = [];
  for (const photo of photos) {
    if (photo.latitude == null || photo.longitude == null) continue;
    const near = groups.find((group) => metersBetween(group.center, photo) <= radius);
    if (!near) {
      groups.push({ key: `${photo.latitude.toFixed(3)}, ${photo.longitude.toFixed(3)}`, photos: [photo], center: photo, count: 1 });
    } else {
      near.photos.push(photo);
      near.count += 1;
      near.center = {
        latitude: (near.center.latitude * (near.count - 1) + photo.latitude) / near.count,
        longitude: (near.center.longitude * (near.count - 1) + photo.longitude) / near.count,
      };
    }
    placed.push(photo.id);
  }
  const missing = photos.filter((photo) => !placed.includes(photo.id));
  groups.sort((a, b) => b.photos.length - a.photos.length);
  if (missing.length) groups.push({ key: "No location", photos: missing });
  return groups;
}

function placeLabel(group) {
  if (!group.center) return "No location";
  const lat = `${Math.abs(group.center.latitude).toFixed(3)}° ${group.center.latitude >= 0 ? "N" : "S"}`;
  const lng = `${Math.abs(group.center.longitude).toFixed(3)}° ${group.center.longitude >= 0 ? "E" : "W"}`;
  return `${lat}, ${lng}`;
}

function heatColor(t) {
  const stops = [
    [0, [30, 70, 180]],
    [0.35, [30, 170, 160]],
    [0.62, [230, 190, 40]],
    [1, [210, 40, 30]],
  ];
  let lower = stops[0];
  let upper = stops[stops.length - 1];
  for (let i = 1; i < stops.length; i += 1) {
    if (t <= stops[i][0]) {
      lower = stops[i - 1];
      upper = stops[i];
      break;
    }
  }
  const span = upper[0] - lower[0] || 1;
  const mix = (t - lower[0]) / span;
  return lower[1].map((channel, index) => Math.round(channel + (upper[1][index] - channel) * mix));
}

function renderHeatMap(groups) {
  const located = groups.filter((group) => group.center);
  const points = located.flatMap((group) => group.photos);
  const show = els.groupBy.value === "location" && state.total > 0;
  els.heatmap.classList.toggle("hidden", !show);
  if (!show) return;
  if (!points.length) {
    els.heatmapNote.textContent = "No GPS locations in these photos yet. Index the folder again so Picture Index can read where they were taken.";
    els.heatmapNote.classList.remove("hidden");
    els.heatmapCanvas.classList.add("hidden");
    state.hotSpots = [];
    return;
  }
  els.heatmapNote.classList.add("hidden");
  els.heatmapCanvas.classList.remove("hidden");
  const width = Math.max(els.heatmap.clientWidth, 320);
  const height = 300;
  const canvas = els.heatmapCanvas;
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(width * dpr);
  canvas.height = Math.round(height * dpr);
  canvas.style.width = `${width}px`;
  canvas.style.height = `${height}px`;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  const lats = points.map((photo) => photo.latitude);
  const lngs = points.map((photo) => photo.longitude);
  let minLat = Math.min(...lats);
  let maxLat = Math.max(...lats);
  let minLng = Math.min(...lngs);
  let maxLng = Math.max(...lngs);
  const padLat = Math.max((maxLat - minLat) * 0.18, 0.004);
  const padLng = Math.max((maxLng - minLng) * 0.18, 0.004);
  minLat -= padLat;
  maxLat += padLat;
  minLng -= padLng;
  maxLng += padLng;
  const project = (lat, lng) => ({
    x: ((lng - minLng) / (maxLng - minLng)) * (width - 28) + 14,
    y: ((maxLat - lat) / (maxLat - minLat)) * (height - 28) + 14,
  });
  const density = document.createElement("canvas");
  density.width = width;
  density.height = height;
  const dctx = density.getContext("2d");
  const blob = 36;
  for (const photo of points) {
    const { x, y } = project(photo.latitude, photo.longitude);
    const gradient = dctx.createRadialGradient(x, y, 0, x, y, blob);
    gradient.addColorStop(0, "rgba(0,0,0,0.55)");
    gradient.addColorStop(1, "rgba(0,0,0,0)");
    dctx.fillStyle = gradient;
    dctx.beginPath();
    dctx.arc(x, y, blob, 0, Math.PI * 2);
    dctx.fill();
  }
  const pixels = dctx.getImageData(0, 0, width, height);
  const colored = dctx.createImageData(width, height);
  let peak = 1;
  for (let i = 3; i < pixels.data.length; i += 4) peak = Math.max(peak, pixels.data[i]);
  for (let i = 0; i < pixels.data.length; i += 4) {
    const amount = pixels.data[i + 3] / peak;
    if (amount < 0.04) continue;
    const [r, g, b] = heatColor(Math.min(1, amount));
    colored.data[i] = r;
    colored.data[i + 1] = g;
    colored.data[i + 2] = b;
    colored.data[i + 3] = Math.round(40 + amount * 200);
  }
  dctx.putImageData(colored, 0, 0);
  ctx.drawImage(density, 0, 0);
  const radius = Number(els.radius.value) || 500;
  const midLat = ((minLat + maxLat) / 2) * (Math.PI / 180);
  const metersPerPixel = ((maxLng - minLng) * 111320 * Math.cos(midLat)) / (width - 28);
  state.hotSpots = located.map((group, index) => {
    const spot = project(group.center.latitude, group.center.longitude);
    const ring = metersPerPixel > 0 ? radius / metersPerPixel : 18;
    const active = state.activePlace === index;
    ctx.beginPath();
    ctx.arc(spot.x, spot.y, Math.max(ring, 10), 0, Math.PI * 2);
    ctx.strokeStyle = active ? "#3568a8" : "rgba(20, 30, 50, 0.45)";
    ctx.lineWidth = active ? 2.5 : 1;
    ctx.stroke();
    ctx.beginPath();
    ctx.arc(spot.x, spot.y, 11, 0, Math.PI * 2);
    ctx.fillStyle = active ? "#3568a8" : "#1c2430";
    ctx.fill();
    ctx.fillStyle = "#fff";
    ctx.font = "11px Segoe UI, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(String(group.photos.length), spot.x, spot.y);
    return { index, x: spot.x, y: spot.y, ring: Math.max(ring, 16) };
  });
}

function renderGrid() {
  const locationMode = els.groupBy.value === "location";
  const source = locationMode && state.mapPhotos.length ? state.mapPhotos : state.photos;
  const hasPhotos = source.length > 0;
  els.empty.classList.toggle("hidden", hasPhotos || (locationMode && state.total > 0));
  els.radiusField.classList.toggle("hidden", !locationMode);
  const groups = [];
  if (locationMode) {
    groups.push(...locationGroups(source, Number(els.radius.value) || 500));
    state.locationGroups = groups;
    renderHeatMap(groups);
  } else {
    els.heatmap.classList.add("hidden");
    for (const photo of state.photos) {
      const key = photo.taken_at ? photo.taken_at.slice(0, 10) : "No date";
      const last = groups[groups.length - 1];
      if (!last || last.key !== key) groups.push({ key, photos: [photo] });
      else last.photos.push(photo);
    }
  }
  els.grid.innerHTML = groups
    .map(
      (group, index) => `
      <section class="day${locationMode && state.activePlace === index && group.center ? " active" : ""}" id="place-${index}">
        <h2>${escapeHtml(locationMode ? placeLabel(group) : group.key === "No date" ? "No date" : dayLabel(group.key))} <span>${group.photos.length}</span></h2>
        <div class="day-grid">
          ${group.photos
            .map(
              (photo) => `
              <button type="button" class="card${photo.id === state.selectedId ? " selected" : ""}" data-id="${photo.id}">
                <img src="/api/photos/${photo.id}/thumb" alt="" />
                <div class="meta">
                  <div class="name">${escapeHtml(photo.filename)}</div>
                  <div class="date">${escapeHtml(formatWhen(photo.taken_at))}</div>
                </div>
              </button>`
            )
            .join("")}
        </div>
      </section>`
    )
    .join("");
  els.more.classList.toggle("hidden", locationMode || state.photos.length >= state.total || !hasPhotos);
}

els.heatmapCanvas.addEventListener("click", (event) => {
  const rect = els.heatmapCanvas.getBoundingClientRect();
  const x = event.clientX - rect.left;
  const y = event.clientY - rect.top;
  const hit = state.hotSpots
    .map((spot) => ({ ...spot, distance: Math.hypot(spot.x - x, spot.y - y) }))
    .filter((spot) => spot.distance <= Math.max(spot.ring, 22))
    .sort((a, b) => a.distance - b.distance)[0];
  if (!hit) return;
  state.activePlace = hit.index;
  renderGrid();
  document.getElementById(`place-${hit.index}`)?.scrollIntoView({ behavior: "smooth", block: "nearest" });
});

window.addEventListener("resize", () => {
  if (els.groupBy.value === "location" && state.locationGroups) renderHeatMap(state.locationGroups);
});

function detailRow(label, value) {
  if (!value) return "";
  return `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`;
}

function renderDetail(photo) {
  document.body.classList.toggle("has-photo", Boolean(photo));
  els.remove.classList.toggle("hidden", !photo);
  if (!photo) {
    els.detail.innerHTML = `<p class="muted">Select a photo to see what is in it and open the file.</p>`;
    return;
  }
  const pixels = photo.width && photo.height ? `${photo.width} × ${photo.height}` : "";
  const modified = photo.mtime ? formatWhen(new Date(photo.mtime * 1000).toISOString()) : "";
  const faces = photo.faces || [];
  const faceMarkup = faces.length
    ? `<div class="detail-faces">${faces
        .map(
          (face) => `
          <span class="named-face">
            <img src="/api/faces/${face.id}/thumb" alt="" />
            <span>${escapeHtml(face.label || "Unnamed")}</span>
            <button type="button" class="btn ghost danger face-remove" data-face="${face.id}">Remove</button>
          </span>`
        )
        .join("")}</div>`
    : photo.faces_done
      ? "No faces found"
      : "Not scanned for faces yet";
  const extra = (photo.details || []).map((row) => detailRow(row.label, row.value)).join("");
  els.detail.innerHTML = `
    <img src="/api/photos/${photo.id}/thumb" alt="" />
    <div class="name">${escapeHtml(photo.filename)}</div>
    <p class="muted">In this photo</p>
    <p class="scene">${escapeHtml(photo.objects || (photo.objects === "" ? "Nothing recognized around the subject." : "Not scanned yet. Index the folder again."))}</p>
    <p class="muted">From this scan</p>
    <dl>
      ${detailRow("Taken", formatWhen(photo.taken_at))}
      ${detailRow("Pixels", pixels)}
      ${detailRow("File size", formatBytes(photo.size))}
      ${detailRow("Modified", modified)}
      ${detailRow("Indexed", formatWhen(photo.indexed_at))}
      ${detailRow("Folder", photo.folder)}
      ${detailRow("Path", photo.path)}
      ${extra}
      <dt>Faces</dt><dd>${faceMarkup}</dd>
      ${detailRow("Scan error", photo.error || photo.detail_error)}
    </dl>
    <button type="button" class="btn primary" id="open-btn">Open file</button>
  `;
  document.getElementById("open-btn").addEventListener("click", () => openPhoto(photo.id));
}

function openPhoto(id) {
  api(`/api/photos/${id}/open`, { method: "POST" }).catch((err) => alert(err.message));
}

function removeFace(id) {
  const ok = confirm("Remove this face from the index? It will be cleared from every photo. The photos stay.");
  if (!ok) return;
  api(`/api/faces/${id}`, { method: "DELETE" })
    .then(() => {
      if (state.faceId === id) state.faceId = null;
      return loadFaces();
    })
    .then(() => search(true))
    .then(() => (state.selectedId ? api(`/api/photos/${state.selectedId}`) : null))
    .then((photo) => {
      if (photo && state.selectedId === photo.id) renderDetail(photo);
    })
    .catch((err) => alert(err.message));
}

document.getElementById("remove-face-btn").addEventListener("click", () => {
  if (state.faceId) removeFace(state.faceId);
});
els.detail.addEventListener("click", (event) => {
  const button = event.target.closest(".face-remove");
  if (!button) return;
  removeFace(Number(button.dataset.face));
});
els.remove.addEventListener("click", () => {
  const id = state.selectedId;
  if (!id) return;
  const ok = confirm("Remove this photo from the index? The file stays in the folder. Faces, objects, and location saved for it will be deleted.");
  if (!ok) return;
  els.remove.disabled = true;
  els.remove.textContent = "Removing…";
  api(`/api/photos/${id}`, { method: "DELETE" })
    .then(() => {
      state.selectedId = null;
      renderDetail(null);
      return loadFaces();
    })
    .then(() => search(true))
    .catch((err) => alert(err.message))
    .finally(() => {
      els.remove.disabled = false;
      els.remove.textContent = "Remove from index";
    });
});

let lastPhotoClick = { id: 0, time: 0 };

function markSelected(id) {
  state.selectedId = id;
  els.grid.querySelectorAll(".card").forEach((card) => {
    card.classList.toggle("selected", Number(card.dataset.id) === id);
  });
}

function selectPhoto(id) {
  markSelected(id);
  const known = state.photos.find((item) => item.id === id);
  renderDetail(known || null);
  api(`/api/photos/${id}`)
    .then((photo) => {
      if (state.selectedId === id) renderDetail(photo);
    })
    .catch(() => {});
}

function openOnSecondClick(id) {
  const now = performance.now();
  if (lastPhotoClick.id === id && now - lastPhotoClick.time < 450) {
    lastPhotoClick = { id: 0, time: 0 };
    openPhoto(id);
    return true;
  }
  lastPhotoClick = { id, time: now };
  return false;
}

function updatePickerNav() {
  els.pickerBack.disabled = pickerHistory.length === 0 && !pickerParent;
  els.pickerUp.disabled = !pickerParent;
}

async function browseTo(path, remember) {
  const leaving = els.pickerPath.value;
  const data = await api(`/api/fs?path=${encodeURIComponent(path || "")}`);
  const arrived = data.path || "";
  if (remember !== false && leaving && leaving !== arrived) pickerHistory.push(leaving);
  els.pickerPath.value = arrived;
  pickerParent = data.parent || "";
  updatePickerNav();
  els.pickerList.innerHTML = data.entries.length
    ? data.entries
        .map((entry) => `<div class="folder-item" data-path="${escapeHtml(entry.path)}">${escapeHtml(entry.name)}</div>`)
        .join("")
    : `<div class="folder-item">No subfolders</div>`;
}

function openPicker() {
  return new Promise((resolve) => {
    pickerResolve = resolve;
    pickerHistory = [];
    els.picker.classList.remove("hidden");
    browseTo(els.folder.value.trim(), false).catch((err) => {
      els.pickerList.innerHTML = `<div class="folder-item">${escapeHtml(err.message)}</div>`;
    });
  });
}

function closePicker(path) {
  els.picker.classList.add("hidden");
  const resolve = pickerResolve;
  pickerResolve = null;
  if (resolve) resolve(path || null);
}

async function chooseFolder() {
  const path = await openPicker();
  if (!path) return null;
  await api("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ folder: path }),
  });
  els.folder.value = path;
  return path;
}

async function startScan(selectedPath) {
  let path = (selectedPath || els.folder.value).trim();
  if (!path) {
    path = await chooseFolder();
    if (!path) return;
  }
  els.index.disabled = true;
  els.index.textContent = "Indexing…";
  state.scanGeneration += 1;
  const generation = state.scanGeneration;
  if (state.jobId) {
    await api(`/api/jobs/${state.jobId}/cancel`, { method: "POST" }).catch(() => {});
  }
  let job;
  for (let attempt = 0; attempt < 8; attempt += 1) {
    try {
      job = await api("/api/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      break;
    } catch (err) {
      if (attempt === 7 || !/already running/i.test(err.message)) throw err;
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
  }
  state.jobId = job.id;
  state.paused = false;
  els.pause.textContent = "Pause";
  showIndexing(job);
  await pollJob(job.id, generation);
}

async function pollJob(jobId, generation) {
  while (true) {
    if (generation !== state.scanGeneration) return;
    const job = await api(`/api/jobs/${jobId}`);
    if (generation !== state.scanGeneration) return;
    showIndexing(job);
    if (["done", "cancelled", "error"].includes(job.status)) {
      if (generation !== state.scanGeneration) return;
      showIndexing(null);
      state.jobId = null;
      await loadFolders();
      await loadFaces();
      await search(true);
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
}

els.index.addEventListener("click", () => startScan().catch((err) => {
  showIndexing(null);
  alert(err.message);
}));
els.browse.addEventListener("click", () =>
  chooseFolder()
    .then((path) => {
      if (!path) return null;
      state.faceId = null;
      return startScan(path);
    })
    .catch((err) => {
      showIndexing(null);
      alert(err.message);
    })
);
els.more.addEventListener("click", () => search(false).catch((err) => alert(err.message)));
els.pause.addEventListener("click", async () => {
  if (!state.jobId) return;
  state.paused = !state.paused;
  els.pause.textContent = state.paused ? "Resume" : "Pause";
  await api(`/api/jobs/${state.jobId}/${state.paused ? "pause" : "resume"}`, { method: "POST" });
});
els.cancel.addEventListener("click", () => {
  if (state.jobId) api(`/api/jobs/${state.jobId}/cancel`, { method: "POST" });
});
let faceDragged = false;

function faceIdFrom(event) {
  const card = event.target.closest("[data-face]");
  return card ? Number(card.dataset.face) : null;
}

els.faces.addEventListener("dragstart", (event) => {
  const id = faceIdFrom(event);
  if (!id || event.target.closest(".face-name")) {
    event.preventDefault();
    return;
  }
  faceDragged = true;
  event.dataTransfer.setData("text/plain", String(id));
  event.dataTransfer.effectAllowed = "move";
  event.target.closest(".face")?.classList.add("dragging");
});
els.faces.addEventListener("dragend", () => {
  els.faces.querySelectorAll(".dragging, .drop-target").forEach((node) => {
    node.classList.remove("dragging", "drop-target");
  });
});
els.faces.addEventListener("dragover", (event) => {
  const face = event.target.closest(".face");
  if (!face) return;
  event.preventDefault();
  event.dataTransfer.dropEffect = "move";
  els.faces.querySelectorAll(".drop-target").forEach((node) => node.classList.remove("drop-target"));
  face.classList.add("drop-target");
});
els.faces.addEventListener("drop", (event) => {
  const keepId = faceIdFrom(event);
  const dropId = Number(event.dataTransfer.getData("text/plain"));
  event.preventDefault();
  if (!keepId || !dropId || keepId === dropId) return;
  api("/api/faces/merge", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ keep_id: keepId, drop_id: dropId }),
  })
    .then(() => {
      if (state.faceId === dropId) state.faceId = keepId;
      return loadFaces();
    })
    .then(() => search(true))
    .catch((err) => alert(err.message));
});
els.faces.addEventListener("click", (event) => {
  if (faceDragged) {
    faceDragged = false;
    return;
  }
  const button = event.target.closest(".face");
  if (!button) return;
  const id = Number(button.dataset.face);
  state.faceId = state.faceId === id ? null : id;
  loadFaces().then(() => search(true)).catch((err) => alert(err.message));
});
els.faces.addEventListener("change", (event) => {
  const input = event.target.closest(".face-name");
  if (!input) return;
  api(`/api/faces/${input.dataset.face}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ label: input.value }),
  })
    .then(() => loadFaces())
    .catch((err) => alert(err.message));
});
els.faces.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && event.target.classList.contains("face-name")) event.target.blur();
});
els.mergeBtn.addEventListener("click", () => {
  if (!state.faceId || !els.mergeWith.value) return;
  const dropId = Number(els.mergeWith.value);
  api("/api/faces/merge", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ keep_id: state.faceId, drop_id: dropId }),
  })
    .then(() => loadFaces())
    .then(() => search(true))
    .catch((err) => alert(err.message));
});
els.grid.addEventListener("click", (event) => {
  const card = event.target.closest(".card");
  if (!card) return;
  const id = Number(card.dataset.id);
  if (!openOnSecondClick(id)) selectPhoto(id);
});
els.detail.addEventListener("click", (event) => {
  if (event.target.closest("img") && state.selectedId) openOnSecondClick(state.selectedId);
});
els.pickerList.addEventListener("click", (event) => {
  const item = event.target.closest(".folder-item");
  if (item?.dataset.path) browseTo(item.dataset.path);
});
els.pickerBack.addEventListener("click", () => {
  if (pickerHistory.length) {
    browseTo(pickerHistory.pop(), false).catch((err) => alert(err.message));
    return;
  }
  if (pickerParent) browseTo(pickerParent, false).catch((err) => alert(err.message));
});
els.pickerUp.addEventListener("click", () => browseTo(pickerParent));
els.pickerCancel.addEventListener("click", () => closePicker(null));
els.pickerChoose.addEventListener("click", () => closePicker(els.pickerPath.value.trim()));
els.pickerPath.addEventListener("keydown", (event) => {
  if (event.key === "Enter") browseTo(els.pickerPath.value.trim());
});
const splitter = document.getElementById("splitter");
const workspace = document.querySelector(".workspace");
const savedSide = Number(localStorage.getItem("picture-index-side"));
if (savedSide >= 240) document.documentElement.style.setProperty("--side-width", `${savedSide}px`);

splitter.addEventListener("pointerdown", (event) => {
  event.preventDefault();
  splitter.classList.add("dragging");
  document.body.classList.add("resizing");
  const drag = (move) => {
    const bounds = workspace.getBoundingClientRect();
    const width = Math.min(Math.max(bounds.right - move.clientX, 240), bounds.width - 280);
    document.documentElement.style.setProperty("--side-width", `${width}px`);
    return width;
  };
  const finish = (end) => {
    const width = drag(end);
    localStorage.setItem("picture-index-side", String(Math.round(width)));
    if (els.groupBy.value === "location" && state.locationGroups) renderHeatMap(state.locationGroups);
    splitter.classList.remove("dragging");
    document.body.classList.remove("resizing");
    window.removeEventListener("pointermove", drag);
    window.removeEventListener("pointerup", finish);
  };
  window.addEventListener("pointermove", drag);
  window.addEventListener("pointerup", finish);
});

els.theme.addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  localStorage.setItem("picture-index-theme", next);
});

const runSearch = debounce(() => search(true).catch((err) => alert(err.message)), 200);
els.search.addEventListener("input", runSearch);
els.folderFilter.addEventListener("change", runSearch);
function syncGroupSegment() {
  document.querySelectorAll("[data-group]").forEach((button) => {
    const on = button.dataset.group === els.groupBy.value;
    button.classList.toggle("is-on", on);
    button.setAttribute("aria-pressed", on ? "true" : "false");
  });
}
document.querySelectorAll("[data-group]").forEach((button) => {
  button.addEventListener("click", () => {
    if (els.groupBy.value === button.dataset.group) return;
    els.groupBy.value = button.dataset.group;
    syncGroupSegment();
    els.groupBy.dispatchEvent(new Event("change"));
  });
});
document.getElementById("detail-close").addEventListener("click", () => {
  state.selectedId = null;
  markSelected(null);
  renderDetail(null);
});
els.groupBy.addEventListener("change", () => search(true).catch((err) => alert(err.message)));
els.radius.addEventListener("change", () => {
  if (els.groupBy.value === "location") renderGrid();
});
els.personFilter.addEventListener("change", () => {
  state.faceId = els.personFilter.value ? Number(els.personFilter.value) : null;
  loadFaces().then(() => search(true)).catch((err) => alert(err.message));
});
els.takenFrom.addEventListener("change", runSearch);
els.takenTo.addEventListener("change", runSearch);

loadStatus()
  .then(() => loadFolders())
  .then(() => loadFaces())
  .then(() => search(true))
  .catch((err) => {
    els.empty.textContent = err.message;
  });
