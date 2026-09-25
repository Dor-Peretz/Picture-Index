const els = {
  folder: document.getElementById("folder"),
  browse: document.getElementById("browse-btn"),
  index: document.getElementById("index-btn"),
  theme: document.getElementById("theme-btn"),
  progress: document.getElementById("progress"),
  progressTitle: document.getElementById("progress-title"),
  progressCount: document.getElementById("progress-count"),
  pause: document.getElementById("pause-btn"),
  cancel: document.getElementById("cancel-btn"),
  bar: document.getElementById("bar-fill"),
  grid: document.getElementById("grid"),
  empty: document.getElementById("empty"),
  more: document.getElementById("more-btn"),
  search: document.getElementById("search"),
  faces: document.getElementById("faces"),
  faceMerge: document.getElementById("face-merge"),
  mergeWith: document.getElementById("merge-with"),
  mergeBtn: document.getElementById("merge-btn"),
  folderFilter: document.getElementById("folder-filter"),
  takenFrom: document.getElementById("taken-from"),
  takenTo: document.getElementById("taken-to"),
  detail: document.getElementById("detail"),
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
}

async function loadFolders() {
  const data = await api("/api/folders");
  const current = els.folderFilter.value;
  els.folderFilter.innerHTML = `<option value="">All folders</option>${data.folders
    .map((folder) => `<option value="${escapeHtml(folder)}">${escapeHtml(folder)}</option>`)
    .join("")}`;
  els.folderFilter.value = current;
}

function queryString() {
  const params = new URLSearchParams();
  if (els.search.value.trim()) params.set("q", els.search.value.trim());
  if (els.folderFilter.value) params.set("folder", els.folderFilter.value);
  if (els.takenFrom.value) params.set("taken_from", els.takenFrom.value);
  if (els.takenTo.value) params.set("taken_to", els.takenTo.value);
  if (state.faceId) params.set("face", String(state.faceId));
  params.set("limit", "80");
  params.set("offset", String(state.offset));
  return params.toString();
}

async function loadFaces() {
  const data = await api("/api/faces");
  if (!data.faces.length) {
    state.faceList = [];
    els.faces.innerHTML = `<span class="muted">Faces appear here after indexing.</span>`;
    els.faceMerge.classList.add("hidden");
    return;
  }
  state.faceList = data.faces;
  els.faces.innerHTML = data.faces
    .map(
      (face) => `
      <div class="face-card">
        <button type="button" class="face${face.id === state.faceId ? " selected" : ""}" data-face="${face.id}" title="${face.count} photos">
          <img src="/api/faces/${face.id}/thumb" alt="" />
        </button>
        <input class="face-name" data-face="${face.id}" value="${escapeHtml(face.label)}" placeholder="Name" />
      </div>`
    )
    .join("");
  const others = data.faces.filter((face) => face.id !== state.faceId);
  els.faceMerge.classList.toggle("hidden", !state.faceId || others.length === 0);
  els.mergeWith.innerHTML = others
    .map((face) => `<option value="${face.id}">${escapeHtml(face.label || "Unnamed")} (${face.count})</option>`)
    .join("");
}

async function search(reset) {
  if (reset) {
    state.offset = 0;
    state.photos = [];
  }
  const data = await api(`/api/photos?${queryString()}`);
  state.total = data.total;
  state.photos = reset ? data.items : state.photos.concat(data.items);
  state.offset = state.photos.length;
  renderGrid();
  els.status.textContent = `${data.total} photo${data.total === 1 ? "" : "s"}`;
  if (state.selectedId && !state.photos.some((photo) => photo.id === state.selectedId)) {
    state.selectedId = null;
    renderDetail(null);
  }
}

function renderGrid() {
  const hasPhotos = state.photos.length > 0;
  els.empty.classList.toggle("hidden", hasPhotos);
  els.grid.innerHTML = state.photos
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
    .join("");
  els.more.classList.toggle("hidden", state.photos.length >= state.total || !hasPhotos);
}

function detailRow(label, value) {
  if (!value) return "";
  return `<dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>`;
}

function renderDetail(photo) {
  if (!photo) {
    els.detail.innerHTML = `<p class="muted">Select a photo.</p>`;
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
    <button type="button" class="btn" id="open-btn">Open file</button>
  `;
  document.getElementById("open-btn").addEventListener("click", () => openPhoto(photo.id));
}

function openPhoto(id) {
  api(`/api/photos/${id}/open`, { method: "POST" }).catch((err) => alert(err.message));
}

function selectPhoto(id) {
  state.selectedId = id;
  renderGrid();
  const known = state.photos.find((item) => item.id === id);
  renderDetail(known || null);
  api(`/api/photos/${id}`)
    .then((photo) => {
      if (state.selectedId === id) renderDetail(photo);
    })
    .catch(() => {});
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
  await pollJob(job.id, generation);
}

async function pollJob(jobId, generation) {
  els.progress.classList.remove("hidden");
  while (true) {
    if (generation !== state.scanGeneration) return;
    const job = await api(`/api/jobs/${jobId}`);
    if (generation !== state.scanGeneration) return;
    const total = job.total || 0;
    const done = job.done || 0;
    els.bar.style.width = `${total ? Math.round((done / total) * 100) : 0}%`;
    els.progressTitle.textContent = job.stage || "Indexing";
    els.progressCount.textContent = total ? `${done} / ${total}` : "";
    if (["done", "cancelled", "error"].includes(job.status)) {
      if (generation !== state.scanGeneration) return;
      els.progress.classList.add("hidden");
      await loadFolders();
      await loadFaces();
      await search(true);
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
}

els.index.addEventListener("click", () => startScan().catch((err) => alert(err.message)));
els.browse.addEventListener("click", () =>
  chooseFolder()
    .then((path) => {
      if (!path) return null;
      state.faceId = null;
      return startScan(path);
    })
    .catch((err) => alert(err.message))
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
els.faces.addEventListener("click", (event) => {
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
  if (card) selectPhoto(Number(card.dataset.id));
});
els.grid.addEventListener("dblclick", (event) => {
  const card = event.target.closest(".card");
  if (card) openPhoto(Number(card.dataset.id));
});
els.detail.addEventListener("dblclick", (event) => {
  if (event.target.closest("img") && state.selectedId) openPhoto(state.selectedId);
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
els.takenFrom.addEventListener("change", runSearch);
els.takenTo.addEventListener("change", runSearch);

loadStatus()
  .then(() => loadFolders())
  .then(() => loadFaces())
  .then(() => search(true))
  .catch((err) => {
    els.empty.textContent = err.message;
  });
