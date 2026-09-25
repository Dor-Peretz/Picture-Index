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
  folderFilter: document.getElementById("folder-filter"),
  takenFrom: document.getElementById("taken-from"),
  takenTo: document.getElementById("taken-to"),
  detail: document.getElementById("detail"),
  status: document.getElementById("status-count"),
  picker: document.getElementById("picker"),
  pickerPath: document.getElementById("picker-path"),
  pickerList: document.getElementById("picker-list"),
  pickerUp: document.getElementById("picker-up"),
  pickerCancel: document.getElementById("picker-cancel"),
  pickerChoose: document.getElementById("picker-choose"),
};

const state = {
  photos: [],
  total: 0,
  selectedId: null,
  jobId: null,
  paused: false,
  offset: 0,
};

let pickerParent = "";
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
  params.set("limit", "80");
  params.set("offset", String(state.offset));
  return params.toString();
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
    renderDetail();
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

function renderDetail() {
  const photo = state.photos.find((item) => item.id === state.selectedId);
  if (!photo) {
    els.detail.innerHTML = `<p class="muted">Select a photo.</p>`;
    return;
  }
  const size = photo.width && photo.height ? `${photo.width} × ${photo.height}` : "";
  els.detail.innerHTML = `
    <img src="/api/photos/${photo.id}/thumb" alt="" />
    <div class="name">${escapeHtml(photo.filename)}</div>
    <dl>
      <dt>Taken</dt><dd>${escapeHtml(formatWhen(photo.taken_at))}</dd>
      <dt>Size</dt><dd>${escapeHtml([size, formatBytes(photo.size)].filter(Boolean).join(" · "))}</dd>
      <dt>Folder</dt><dd>${escapeHtml(photo.folder)}</dd>
      ${photo.error ? `<dt>Error</dt><dd>${escapeHtml(photo.error)}</dd>` : ""}
    </dl>
    <button type="button" class="btn" id="open-btn">Open file</button>
  `;
  document.getElementById("open-btn").addEventListener("click", () => {
    api(`/api/photos/${photo.id}/open`, { method: "POST" }).catch((err) => alert(err.message));
  });
}

function selectPhoto(id) {
  state.selectedId = id;
  renderGrid();
  renderDetail();
}

async function browseTo(path) {
  const data = await api(`/api/fs?path=${encodeURIComponent(path || "")}`);
  els.pickerPath.value = data.path || "";
  pickerParent = data.parent || "";
  els.pickerList.innerHTML = data.entries.length
    ? data.entries
        .map((entry) => `<div class="folder-item" data-path="${escapeHtml(entry.path)}">${escapeHtml(entry.name)}</div>`)
        .join("")
    : `<div class="folder-item">No subfolders</div>`;
}

function openPicker() {
  return new Promise((resolve) => {
    pickerResolve = resolve;
    els.picker.classList.remove("hidden");
    browseTo(els.folder.value.trim()).catch((err) => {
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

async function startScan() {
  let path = els.folder.value.trim();
  if (!path) {
    path = await chooseFolder();
    if (!path) return;
  }
  const job = await api("/api/scan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  state.jobId = job.id;
  state.paused = false;
  els.pause.textContent = "Pause";
  await pollJob(job.id);
}

async function pollJob(jobId) {
  els.progress.classList.remove("hidden");
  while (true) {
    const job = await api(`/api/jobs/${jobId}`);
    const total = job.total || 0;
    const done = job.done || 0;
    els.bar.style.width = `${total ? Math.round((done / total) * 100) : 0}%`;
    els.progressTitle.textContent = job.stage || "Indexing";
    els.progressCount.textContent = total ? `${done} / ${total}` : "";
    if (["done", "cancelled", "error"].includes(job.status)) {
      els.progress.classList.add("hidden");
      await loadFolders();
      await search(true);
      return;
    }
    await new Promise((resolve) => setTimeout(resolve, 400));
  }
}

els.index.addEventListener("click", () => startScan().catch((err) => alert(err.message)));
els.browse.addEventListener("click", () => chooseFolder().catch((err) => alert(err.message)));
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
els.grid.addEventListener("click", (event) => {
  const card = event.target.closest(".card");
  if (card) selectPhoto(Number(card.dataset.id));
});
els.pickerList.addEventListener("click", (event) => {
  const item = event.target.closest(".folder-item");
  if (item?.dataset.path) browseTo(item.dataset.path);
});
els.pickerUp.addEventListener("click", () => browseTo(pickerParent));
els.pickerCancel.addEventListener("click", () => closePicker(null));
els.pickerChoose.addEventListener("click", () => closePicker(els.pickerPath.value.trim()));
els.pickerPath.addEventListener("keydown", (event) => {
  if (event.key === "Enter") browseTo(els.pickerPath.value.trim());
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
  .then(() => search(true))
  .catch((err) => {
    els.empty.textContent = err.message;
  });
