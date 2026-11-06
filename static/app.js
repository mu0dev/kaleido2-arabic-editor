"use strict";

const $ = (id) => document.getElementById(id);
const number = new Intl.NumberFormat();
const state = {
  tab: "dialogue",
  status: null,
  names: new Map(),
  dialogue: { items: [], total: 0, offset: 0, limit: 50, q: "", filter: "all", selected: null, draft: "", drafts: new Map(), request: 0 },
  strings: { items: [], filtered: [], selected: null, draft: "", drafts: new Map(), loaded: false },
  images: { items: [], total: 0, offset: 0, limit: 30, q: "", selected: null, request: 0, base: null, objectURL: null, pendingFile: null, dragging: null },
  videos: { items: [], selected: null, objectURL: null, pendingFile: null, loaded: false },
  toastTimer: null,
};

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function asItems(data) { return Array.isArray(data) ? data : (Array.isArray(data?.items) ? data.items : []); }
function countBlock(block) {
  const completed = Number(block?.translated ?? block?.modified ?? 0);
  return { total: Number(block?.total || 0), translated: completed, modified: completed };
}
function displayCount(value) { return number.format(Number(value || 0)); }
function imageURL(path) { return `/api/image?${new URLSearchParams({ path }).toString()}`; }
function videoURL(name) { return `/api/video?${new URLSearchParams({ name }).toString()}`; }

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const raw = await response.text();
  let body;
  try { body = raw ? JSON.parse(raw) : {}; } catch { body = { message: raw }; }
  if (!response.ok) throw new Error(body.error || body.message || `${response.status} ${response.statusText}`);
  return body;
}

function postJSON(path, data) {
  return api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data) });
}

function toast(message, isError = false) {
  const target = $("toast");
  target.textContent = message;
  target.classList.toggle("error", isError);
  target.classList.add("show");
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => target.classList.remove("show"), 3600);
}

function showError(error, context = "Could not complete the action") {
  const message = `${context}: ${error instanceof Error ? error.message : String(error)}`;
  toast(message, true);
  console.error(message, error);
}

function busy(button, value, label) {
  button.disabled = value;
  if (value) {
    button.dataset.oldLabel = button.textContent;
    button.textContent = label || "Working…";
  } else if (button.dataset.oldLabel) {
    button.textContent = button.dataset.oldLabel;
    delete button.dataset.oldLabel;
  }
}

function switchTab(tab) {
  state.tab = tab;
  const titles = { dialogue: "Dialogue", strings: "UI strings", images: "Images", videos: "Videos", export: "Export" };
  $("page-title").textContent = titles[tab];
  document.querySelectorAll(".nav-item").forEach((button) => {
    const active = button.dataset.tab === tab;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page"); else button.removeAttribute("aria-current");
  });
  document.querySelectorAll(".view").forEach((view) => {
    const active = view.id === `view-${tab}`;
    view.hidden = !active;
    view.classList.toggle("active", active);
  });
  if (tab === "strings" && !state.strings.loaded) loadStrings();
  if (tab === "images") loadImages();
  if (tab === "videos" && !state.videos.loaded) loadVideos();
  if (tab === "export") refreshStatus();
}

function renderCoverage(status) {
  const dialogue = countBlock(status.dialogue);
  const strings = countBlock(status.strings);
  const names = countBlock(status.names);
  const images = countBlock(status.images);
  const videos = countBlock(status.videos);
  $("nav-dialogue-count").textContent = displayCount(dialogue.translated);
  $("nav-strings-count").textContent = displayCount(strings.translated);
  $("nav-images-count").textContent = displayCount(images.modified);
  $("nav-videos-count").textContent = displayCount(videos.modified || state.videos.items.filter(item => item.modified).length);
  const pct = dialogue.total ? Math.round(dialogue.translated / dialogue.total * 100) : 0;
  $("top-progress").textContent = `${displayCount(dialogue.translated)} / ${displayCount(dialogue.total)} lines translated · ${pct}%`;

  const metrics = [
    { label: "Dialogue", done: dialogue.translated, total: dialogue.total, suffix: "lines" },
    { label: "UI strings", done: strings.translated, total: strings.total, suffix: "strings" },
    { label: "Speaker names", done: names.translated, total: names.total, suffix: "names" },
    { label: "Images", done: images.modified, total: images.total, suffix: "replaced" },
    { label: "Videos", done: videos.modified, total: videos.total || 2, suffix: "replaced" },
  ];
  const grid = $("coverage-grid");
  grid.replaceChildren();
  for (const metric of metrics) {
    const card = node("div", "metric");
    card.append(node("span", "metric-label", metric.label));
    card.append(node("strong", "metric-number", `${displayCount(metric.done)} / ${displayCount(metric.total)}`));
    const detail = node("span", "metric-detail", metric.suffix);
    card.append(detail);
    const track = node("div", "metric-track");
    const fill = node("span", "metric-fill");
    fill.style.width = `${metric.total ? Math.min(100, Math.round(metric.done / metric.total * 100)) : 0}%`;
    track.append(fill);
    card.append(track);
    grid.append(card);
  }
}

async function refreshStatus() {
  try {
    const status = await api("/api/status");
    state.status = status;
    renderCoverage(status);
    $("connection-state").textContent = status.ready === false ? "Project setup needed" : "Local workspace ready";
    document.querySelector(".live-dot").className = "live-dot connected";
  } catch (error) {
    $("connection-state").textContent = "Connection unavailable";
    document.querySelector(".live-dot").className = "live-dot error";
    showError(error, "Status unavailable");
  }
}

async function loadNames() {
  try {
    const data = await api("/api/names");
    state.names = new Map(asItems(data).map(item => [String(item.source), String(item.translation || "")]));
    updatePreviewSpeaker();
  } catch (error) { showError(error, "Speaker names unavailable"); }
}

function cleanedPreview(text) {
  return String(text || "")
    .replace(/@r/g, "\n")
    .replace(/@[vwoazcsxu][^.@]*\./g, "")
    .replace(/@[k>\[\]{}|yet\-b<]/g, "")
    .trim();
}

function setPreview(element, value, placeholder) {
  const cleaned = cleanedPreview(value);
  element.textContent = cleaned || placeholder;
  element.classList.toggle("placeholder", !cleaned);
}

function statusPill(element, done, doneLabel = "Translated", pendingLabel = "Untranslated") {
  element.textContent = done ? doneLabel : pendingLabel;
  element.classList.toggle("done", Boolean(done));
}

function dialogueURL() {
  const d = state.dialogue;
  return `/api/dialogue?${new URLSearchParams({ q: d.q, offset: String(d.offset), limit: String(d.limit), filter: d.filter }).toString()}`;
}

async function loadDialogue() {
  const d = state.dialogue;
  const request = ++d.request;
  $("dialogue-list").replaceChildren(node("p", "list-message", "Loading script…"));
  try {
    const result = await api(dialogueURL());
    if (request !== d.request) return;
    d.items = asItems(result);
    d.total = Number(result.total ?? d.items.length);
    d.offset = Number(result.offset ?? d.offset);
    renderDialogueList();
    const selected = d.items.find(item => String(item.id) === String(d.selected?.id)) || d.items[0];
    selectDialogue(selected || null);
  } catch (error) {
    if (request !== d.request) return;
    $("dialogue-list").replaceChildren(node("p", "list-message", "Unable to load dialogue."));
    showError(error, "Dialogue unavailable");
  }
}

function renderDialogueList() {
  const d = state.dialogue;
  const list = $("dialogue-list");
  list.replaceChildren();
  const fragment = document.createDocumentFragment();
  for (const item of d.items) {
    const button = node("button", "entry-row");
    button.type = "button";
    button.dataset.id = String(item.id);
    if (String(item.id) === String(d.selected?.id)) button.classList.add("selected");
    button.append(node("span", "entry-id", String(item.id)));
    const main = node("span", "entry-main");
    main.append(node("span", "entry-speaker", item.speaker || "Narration"));
    main.append(node("span", "entry-snippet", String(item.translation || item.source || "").replace(/@r/g, " · ")));
    button.append(main);
    button.append(node("span", `entry-dot${item.translation ? " done" : ""}`));
    button.addEventListener("click", () => selectDialogue(item));
    fragment.append(button);
  }
  list.append(fragment);
  if (!d.items.length) list.append(node("p", "list-message", "No lines match this search."));
  $("dialogue-result-count").textContent = `${displayCount(d.total)} entries`;
  const start = d.total ? d.offset + 1 : 0;
  $("dialogue-page-label").textContent = `${displayCount(start)}–${displayCount(Math.min(d.offset + d.items.length, d.total))} of ${displayCount(d.total)}`;
  $("dialogue-prev").disabled = d.offset <= 0;
  $("dialogue-next").disabled = d.offset + d.limit >= d.total;
}

function selectDialogue(item) {
  const d = state.dialogue;
  d.selected = item;
  $("dialogue-empty").hidden = Boolean(item);
  $("dialogue-editor").hidden = !item;
  if (!item) return;
  d.draft = d.drafts.has(String(item.id)) ? d.drafts.get(String(item.id)) : String(item.translation || "");
  $("dialogue-id").textContent = String(item.id);
  $("dialogue-voice").textContent = item.voice || item.section || "";
  $("dialogue-source").textContent = String(item.source || "").replace(/@r/g, "\n");
  $("dialogue-translation").value = d.draft;
  $("speaker-source").textContent = item.speaker || "Narration";
  $("speaker-translation").value = item.speaker ? (state.names.get(String(item.speaker)) || "") : "";
  $("speaker-translation").disabled = !item.speaker;
  $("save-speaker").disabled = !item.speaker;
  $("dialogue-save-state").textContent = "";
  updateDialoguePreview();
  renderDialogueList();
}

function updatePreviewSpeaker() {
  const item = state.dialogue.selected;
  if (!item) return;
  const mapped = $("speaker-translation").value.trim() || state.names.get(String(item.speaker)) || item.speaker || "";
  $("preview-speaker").textContent = mapped;
}

function updateDialoguePreview() {
  const d = state.dialogue;
  if (!d.selected) return;
  d.draft = $("dialogue-translation").value;
  if (d.draft === String(d.selected.translation || "")) d.drafts.delete(String(d.selected.id));
  else d.drafts.set(String(d.selected.id), d.draft);
  setPreview($("dialogue-preview"), d.draft, "Your translation appears here as you type.");
  updatePreviewSpeaker();
  $("dialogue-chars").textContent = `${displayCount(d.draft.length)} characters`;
  $("save-dialogue").disabled = d.draft === String(d.selected.translation || "");
  if (!$("save-dialogue").disabled) $("dialogue-save-state").textContent = "Unsaved changes";
  statusPill($("dialogue-state"), d.draft.trim().length > 0);
}

async function saveDialogue() {
  const d = state.dialogue;
  if (!d.selected) return;
  const button = $("save-dialogue");
  const item = d.selected;
  const id = String(item.id);
  const saving = d.draft;
  busy(button, true, "Saving…");
  try {
    await postJSON(`/api/dialogue/${encodeURIComponent(id)}`, { translation: saving });
    item.translation = saving;
    if (d.drafts.get(id) === saving) d.drafts.delete(id);
    if (d.selected === item) $("dialogue-save-state").textContent = "Saved";
    renderDialogueList();
    toast("Dialogue saved");
    refreshStatus();
  } catch (error) { showError(error, "Could not save dialogue"); }
  finally { busy(button, false); updateDialoguePreview(); }
}

async function saveSpeaker() {
  const item = state.dialogue.selected;
  if (!item?.speaker) return;
  const value = $("speaker-translation").value.trim();
  const button = $("save-speaker");
  busy(button, true, "Saving…");
  try {
    await postJSON(`/api/names/${encodeURIComponent(String(item.speaker))}`, { translation: value });
    state.names.set(String(item.speaker), value);
    updatePreviewSpeaker();
    toast("Speaker name saved for every line");
    refreshStatus();
  } catch (error) { showError(error, "Could not save speaker name"); }
  finally { busy(button, false); }
}

async function loadStrings() {
  $("strings-list").replaceChildren(node("p", "list-message", "Loading interface strings…"));
  try {
    const result = await api("/api/strings");
    state.strings.items = asItems(result);
    state.strings.loaded = true;
    renderStringsList();
    selectString(state.strings.items[0] || null);
  } catch (error) { showError(error, "UI strings unavailable"); }
}

function renderStringsList() {
  const s = state.strings;
  const query = $("strings-search").value.trim().toLocaleLowerCase();
  const filter = $("strings-filter").value;
  s.filtered = s.items.filter(item => {
    const done = Boolean(item.translation);
    if (filter === "translated" && !done || filter === "untranslated" && done) return false;
    return !query || [item.id, item.source, item.translation, item.kind, item.context].some(value => String(value || "").toLocaleLowerCase().includes(query));
  });
  $("strings-result-count").textContent = `${displayCount(s.filtered.length)} entries`;
  const list = $("strings-list");
  list.replaceChildren();
  const fragment = document.createDocumentFragment();
  for (const item of s.filtered) {
    const button = node("button", "entry-row");
    button.type = "button";
    if (String(item.id) === String(s.selected?.id)) button.classList.add("selected");
    button.append(node("span", "entry-id", String(item.kind || "UI").slice(0, 8)));
    const main = node("span", "entry-main");
    main.append(node("span", "entry-speaker", String(item.context || item.id || "Interface")));
    main.append(node("span", "entry-snippet", String(item.translation || item.source || "")));
    button.append(main, node("span", `entry-dot${item.translation ? " done" : ""}`));
    button.addEventListener("click", () => selectString(item));
    fragment.append(button);
  }
  list.append(fragment);
  if (!s.filtered.length) list.append(node("p", "list-message", "No strings match this search."));
}

function selectString(item) {
  const s = state.strings;
  s.selected = item;
  $("strings-empty").hidden = Boolean(item);
  $("strings-editor").hidden = !item;
  if (!item) return;
  s.draft = s.drafts.has(String(item.id)) ? s.drafts.get(String(item.id)) : String(item.translation || "");
  $("string-section").textContent = item.kind || "Interface text";
  $("string-id").textContent = String(item.id);
  $("string-source").textContent = String(item.source || "").replace(/@r/g, "\n");
  $("string-translation").value = s.draft;
  $("string-translation").readOnly = item.editable === false;
  $("string-save-state").textContent = item.editable === false ? "This source is view only." : "";
  updateStringPreview();
  renderStringsList();
}

function updateStringPreview() {
  const s = state.strings;
  if (!s.selected) return;
  s.draft = $("string-translation").value;
  if (s.draft === String(s.selected.translation || "")) s.drafts.delete(String(s.selected.id));
  else s.drafts.set(String(s.selected.id), s.draft);
  setPreview($("string-preview"), s.draft, "Your translation appears here as you type.");
  $("string-chars").textContent = `${displayCount(s.draft.length)} characters`;
  $("save-string").disabled = s.selected.editable === false || s.draft === String(s.selected.translation || "");
  if (!$("save-string").disabled) $("string-save-state").textContent = "Unsaved changes";
  statusPill($("string-state"), s.draft.trim().length > 0);
}

async function saveString() {
  const s = state.strings;
  if (!s.selected || s.selected.editable === false) return;
  const button = $("save-string");
  const item = s.selected;
  const id = String(item.id);
  const saving = s.draft;
  busy(button, true, "Saving…");
  try {
    await postJSON(`/api/strings/${encodeURIComponent(id)}`, { translation: saving });
    item.translation = saving;
    if (s.drafts.get(id) === saving) s.drafts.delete(id);
    if (s.selected === item) $("string-save-state").textContent = "Saved";
    renderStringsList();
    toast("Interface string saved");
    refreshStatus();
  } catch (error) { showError(error, "Could not save string"); }
  finally { busy(button, false); updateStringPreview(); }
}

function imagesURL() {
  const i = state.images;
  return `/api/images?${new URLSearchParams({ offset: String(i.offset), limit: String(i.limit), q: i.q }).toString()}`;
}

async function loadImages() {
  const i = state.images;
  const request = ++i.request;
  $("images-grid").replaceChildren(node("p", "list-message", "Loading images…"));
  try {
    const result = await api(imagesURL());
    if (request !== i.request) return;
    i.items = asItems(result);
    i.total = Number(result.total ?? i.items.length);
    renderImages();
    const selected = i.items.find(item => item.path === i.selected?.path) || i.items[0];
    selectImage(selected || null);
  } catch (error) {
    if (request !== i.request) return;
    $("images-grid").replaceChildren(node("p", "list-message", "Images unavailable. Extract game images to begin."));
    showError(error, "Images unavailable");
  }
}

function renderImages() {
  const i = state.images;
  const grid = $("images-grid");
  grid.replaceChildren();
  const fragment = document.createDocumentFragment();
  for (const item of i.items) {
    const button = node("button", "image-tile");
    button.type = "button";
    button.title = item.path;
    if (item.path === i.selected?.path) button.classList.add("selected");
    const imageWrap = node("span", "image-tile-img");
    const image = node("img");
    image.loading = "lazy";
    image.alt = "";
    image.src = imageURL(item.path);
    imageWrap.append(image);
    button.append(imageWrap);
    button.append(node("span", "image-tile-name", item.path.split("/").at(-1)));
    button.append(node("span", `image-tile-meta${item.modified ? " modified" : ""}`, item.modified ? "Replacement saved" : `${item.width} × ${item.height}`));
    button.addEventListener("click", () => selectImage(item));
    fragment.append(button);
  }
  grid.append(fragment);
  if (!i.items.length) grid.append(node("p", "list-message", "No images match this search. Extract all game images if the library is empty."));
  $("images-result-count").textContent = `${displayCount(i.total)} images`;
  const start = i.total ? i.offset + 1 : 0;
  $("images-page-label").textContent = `${displayCount(start)}–${displayCount(Math.min(i.offset + i.items.length, i.total))} of ${displayCount(i.total)}`;
  $("images-prev").disabled = i.offset <= 0;
  $("images-next").disabled = i.offset + i.limit >= i.total;
}

function loadBrowserImage(url) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("Could not open PNG preview"));
    image.src = url;
  });
}

function resetImageControls(width, height) {
  $("overlay-text").value = "";
  $("overlay-x").value = Math.round(width * .82);
  $("overlay-y").value = Math.round(height * .48);
  $("overlay-size").value = Math.max(12, Math.min(70, Math.round(Math.min(width, height) * .07)));
  $("overlay-color").value = "#ffffff";
  $("overlay-bold").checked = true;
  $("cover-enabled").checked = false;
  $("cover-x").value = Math.round(width * .1);
  $("cover-y").value = Math.round(height * .4);
  $("cover-width").value = Math.round(width * .8);
  $("cover-height").value = Math.round(height * .18);
  $("cover-color").value = "#203027";
}

async function selectImage(item) {
  const i = state.images;
  i.selected = item;
  i.base = null;
  i.pendingFile = null;
  i.dragging = null;
  if (i.objectURL) URL.revokeObjectURL(i.objectURL);
  i.objectURL = null;
  $("image-file").value = "";
  $("images-empty").hidden = Boolean(item);
  $("images-editor").hidden = !item;
  if (!item) return;
  $("image-name").textContent = item.path.split("/").at(-1);
  $("image-path").textContent = item.rom_path || item.path;
  $("image-size").textContent = `${displayCount(item.width)} × ${displayCount(item.height)} pixels · PNG`;
  $("image-download").href = imageURL(item.path);
  $("image-download").download = item.path.split("/").at(-1);
  $("image-upload-state").textContent = "";
  statusPill($("image-state"), item.modified, "Replacement saved", "Original");
  resetImageControls(Number(item.width), Number(item.height));
  const requestItem = item;
  try {
    const image = await loadBrowserImage(`${imageURL(item.path)}&v=${Date.now()}`);
    if (i.selected !== requestItem) return;
    i.base = image;
    const canvas = $("image-canvas");
    canvas.width = Number(item.width) || image.naturalWidth;
    canvas.height = Number(item.height) || image.naturalHeight;
    drawImageCanvas();
  } catch (error) { showError(error, "Image preview unavailable"); }
  renderImages();
}

function imageHasChanges() {
  return Boolean(state.images.pendingFile || $("overlay-text").value.trim() || $("cover-enabled").checked);
}

function drawImageCanvas() {
  const i = state.images;
  const canvas = $("image-canvas");
  if (!i.base || !i.selected || !canvas.width || !canvas.height) return;
  const context = canvas.getContext("2d");
  context.clearRect(0, 0, canvas.width, canvas.height);
  context.drawImage(i.base, 0, 0, canvas.width, canvas.height);
  if ($("cover-enabled").checked) {
    context.fillStyle = $("cover-color").value;
    context.fillRect(Number($("cover-x").value) || 0, Number($("cover-y").value) || 0,
      Number($("cover-width").value) || 0, Number($("cover-height").value) || 0);
  }
  const text = $("overlay-text").value;
  if (text.trim()) {
    const size = Math.max(6, Number($("overlay-size").value) || 24);
    context.direction = "rtl";
    context.textAlign = "right";
    context.textBaseline = "top";
    context.fillStyle = $("overlay-color").value;
    context.font = `${$("overlay-bold").checked ? "700" : "400"} ${size}px "Noto Sans Arabic", Tahoma, sans-serif`;
    const x = Number($("overlay-x").value) || 0;
    const y = Number($("overlay-y").value) || 0;
    text.split(/\r?\n/).forEach((line, index) => context.fillText(line, x, y + index * size * 1.4));
  }
  $("upload-image").disabled = !imageHasChanges();
  $("image-upload-state").textContent = imageHasChanges() ? "Preview only · save to keep this image" : "";
}

function canvasPoint(event) {
  const canvas = $("image-canvas");
  const rect = canvas.getBoundingClientRect();
  return {
    x: Math.round((event.clientX - rect.left) * canvas.width / rect.width),
    y: Math.round((event.clientY - rect.top) * canvas.height / rect.height),
  };
}

function onCanvasPointerDown(event) {
  if (!state.images.base) return;
  const point = canvasPoint(event);
  if ($("cover-enabled").checked) {
    state.images.dragging = point;
    $("image-canvas").setPointerCapture(event.pointerId);
    $("cover-x").value = point.x;
    $("cover-y").value = point.y;
    $("cover-width").value = 0;
    $("cover-height").value = 0;
  } else {
    $("overlay-x").value = point.x;
    $("overlay-y").value = point.y;
  }
  drawImageCanvas();
}

function onCanvasPointerMove(event) {
  const start = state.images.dragging;
  if (!start) return;
  const point = canvasPoint(event);
  $("cover-x").value = Math.min(start.x, point.x);
  $("cover-y").value = Math.min(start.y, point.y);
  $("cover-width").value = Math.abs(point.x - start.x);
  $("cover-height").value = Math.abs(point.y - start.y);
  drawImageCanvas();
}

function onCanvasPointerUp() { state.images.dragging = null; }

async function chooseImageFile(file) {
  const i = state.images;
  if (!file || !i.selected) return;
  if (file.type !== "image/png" && !file.name.toLowerCase().endsWith(".png")) {
    toast("Choose a PNG file", true); return;
  }
  const url = URL.createObjectURL(file);
  try {
    const image = await loadBrowserImage(url);
    if (image.naturalWidth !== Number(i.selected.width) || image.naturalHeight !== Number(i.selected.height)) {
      throw new Error(`Expected ${i.selected.width} × ${i.selected.height} pixels; this PNG is ${image.naturalWidth} × ${image.naturalHeight}`);
    }
    if (i.objectURL) URL.revokeObjectURL(i.objectURL);
    i.objectURL = url;
    i.base = image;
    i.pendingFile = file;
    drawImageCanvas();
    $("image-upload-state").textContent = `Previewing ${file.name} · save to keep it`;
  } catch (error) {
    URL.revokeObjectURL(url);
    showError(error, "Replacement PNG rejected");
  }
}

async function saveImage() {
  const i = state.images;
  if (!i.selected || !i.base || !imageHasChanges()) return;
  const button = $("upload-image");
  busy(button, true, "Saving…");
  try {
    const blob = await new Promise((resolve, reject) => $("image-canvas").toBlob(value => value ? resolve(value) : reject(new Error("Could not render PNG")), "image/png"));
    const form = new FormData();
    form.append("path", i.selected.path);
    form.append("file", blob, i.selected.path.split("/").at(-1));
    await api("/api/images/upload", { method: "POST", body: form });
    i.selected.modified = true;
    i.pendingFile = null;
    if (i.objectURL) URL.revokeObjectURL(i.objectURL);
    i.objectURL = URL.createObjectURL(blob);
    i.base = await loadBrowserImage(i.objectURL);
    resetImageControls(Number(i.selected.width), Number(i.selected.height));
    drawImageCanvas();
    $("image-download").href = `${imageURL(i.selected.path)}&v=${Date.now()}`;
    statusPill($("image-state"), true, "Replacement saved", "Original");
    $("image-upload-state").textContent = "Saved";
    renderImages();
    refreshStatus();
    toast("Image replacement saved");
  } catch (error) { showError(error, "Could not save image"); }
  finally { busy(button, false); $("upload-image").disabled = !imageHasChanges(); }
}

async function extractImages() {
  const button = $("extract-images");
  busy(button, true, "Extracting…");
  try {
    const result = await postJSON("/api/images/extract", { all: true });
    state.images.offset = 0;
    await loadImages();
    refreshStatus();
    toast(result.message || "Game images extracted");
  } catch (error) { showError(error, "Could not extract images"); }
  finally { busy(button, false); }
}

async function loadVideos() {
  try {
    const result = await api("/api/videos");
    state.videos.items = asItems(result);
    state.videos.loaded = true;
    renderVideos();
    selectVideo(state.videos.items[0] || null);
  } catch (error) { showError(error, "Videos unavailable"); }
}

function renderVideos() {
  const v = state.videos;
  const grid = $("video-grid");
  grid.replaceChildren();
  for (const item of v.items) {
    const button = node("button", "video-tile");
    button.type = "button";
    if (item.name === v.selected?.name) button.classList.add("selected");
    const left = node("div");
    left.append(node("strong", "", item.name === "op2" ? "Opening · OP" : item.name === "ed" ? "Ending · ED" : item.name));
    left.append(node("span", "", item.path || `${item.name}.mp4`));
    button.append(left, node("span", "", item.modified ? "Replacement saved" : "Original"));
    button.addEventListener("click", () => selectVideo(item));
    grid.append(button);
  }
  if (!v.items.length) grid.append(node("p", "list-message", "No video entries available."));
}

function selectVideo(item) {
  const v = state.videos;
  if (v.objectURL) URL.revokeObjectURL(v.objectURL);
  v.objectURL = null;
  v.pendingFile = null;
  v.selected = item;
  $("video-file").value = "";
  $("video-editor").hidden = !item;
  $("upload-video").disabled = true;
  $("video-upload-state").textContent = "";
  if (!item) return;
  $("video-name").textContent = item.name === "op2" ? "Opening · OP" : item.name === "ed" ? "Ending · ED" : item.name;
  $("video-path").textContent = item.path || `${item.name}.mp4`;
  statusPill($("video-state"), item.modified, "Replacement saved", "Original");
  $("video-preview").src = `${videoURL(item.name)}&v=${Date.now()}`;
  renderVideos();
}

function chooseVideoFile(file) {
  const v = state.videos;
  if (!file || !v.selected) return;
  if (file.type !== "video/mp4" && !file.name.toLowerCase().endsWith(".mp4")) {
    toast("Choose an MP4 file", true); return;
  }
  if (v.objectURL) URL.revokeObjectURL(v.objectURL);
  v.objectURL = URL.createObjectURL(file);
  v.pendingFile = file;
  $("video-preview").src = v.objectURL;
  $("upload-video").disabled = false;
  $("video-upload-state").textContent = `Previewing ${file.name} · save to keep it`;
}

async function saveVideo() {
  const v = state.videos;
  if (!v.selected || !v.pendingFile) return;
  const button = $("upload-video");
  busy(button, true, "Saving…");
  try {
    const form = new FormData();
    form.append("name", v.selected.name);
    form.append("file", v.pendingFile, v.pendingFile.name);
    await api("/api/videos/upload", { method: "POST", body: form });
    v.selected.modified = true;
    v.pendingFile = null;
    $("video-preview").src = `${videoURL(v.selected.name)}&v=${Date.now()}`;
    statusPill($("video-state"), true, "Replacement saved", "Original");
    $("video-upload-state").textContent = "Saved";
    renderVideos();
    refreshStatus();
    toast("Video replacement saved");
  } catch (error) { showError(error, "Could not save video"); }
  finally { busy(button, false); $("upload-video").disabled = !v.pendingFile; }
}

function logAction(message) {
  const log = $("activity-log");
  const line = `[${new Date().toLocaleTimeString()}] ${message}`;
  log.textContent = log.textContent === "No actions yet." ? line : `${line}\n${log.textContent}`;
}

async function exportPatch() {
  const button = $("build-patch");
  busy(button, true, "Building…");
  logAction("Building patch…");
  try {
    const result = await postJSON("/api/export", {});
    logAction(result.message || `Build complete${result.path ? `: ${result.path}` : ""}`);
    toast("Patch built");
    refreshStatus();
  } catch (error) { logAction(`Build failed: ${error.message}`); showError(error, "Build failed"); }
  finally { busy(button, false); }
}

async function installPatch() {
  const button = $("install-patch");
  busy(button, true, "Installing…");
  logAction("Installing patch into Suyu…");
  try {
    const result = await postJSON("/api/install", {});
    logAction(result.message || `Installed${result.path ? `: ${result.path}` : ""}`);
    if (result.restart_required) logAction("Restart the game in Suyu to load the new patch.");
    toast(result.restart_required ? "Patch installed · restart the game in Suyu" : "Patch installed to Suyu");
    refreshStatus();
  } catch (error) { logAction(`Install failed: ${error.message}`); showError(error, "Install failed"); }
  finally { busy(button, false); }
}

function debounce(fn, delay = 220) {
  let timer;
  return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), delay); };
}

function bindEvents() {
  document.querySelectorAll(".nav-item").forEach(button => button.addEventListener("click", () => switchTab(button.dataset.tab)));
  $("dialogue-search").addEventListener("input", debounce(() => { state.dialogue.q = $("dialogue-search").value.trim(); state.dialogue.offset = 0; loadDialogue(); }));
  $("dialogue-filter").addEventListener("change", () => { state.dialogue.filter = $("dialogue-filter").value; state.dialogue.offset = 0; loadDialogue(); });
  $("dialogue-prev").addEventListener("click", () => { state.dialogue.offset = Math.max(0, state.dialogue.offset - state.dialogue.limit); loadDialogue(); });
  $("dialogue-next").addEventListener("click", () => { state.dialogue.offset += state.dialogue.limit; loadDialogue(); });
  $("dialogue-translation").addEventListener("input", updateDialoguePreview);
  $("speaker-translation").addEventListener("input", updatePreviewSpeaker);
  $("save-dialogue").addEventListener("click", saveDialogue);
  $("save-speaker").addEventListener("click", saveSpeaker);

  $("strings-search").addEventListener("input", debounce(renderStringsList));
  $("strings-filter").addEventListener("change", renderStringsList);
  $("string-translation").addEventListener("input", updateStringPreview);
  $("save-string").addEventListener("click", saveString);

  $("images-search").addEventListener("input", debounce(() => { state.images.q = $("images-search").value.trim(); state.images.offset = 0; loadImages(); }));
  $("images-prev").addEventListener("click", () => { state.images.offset = Math.max(0, state.images.offset - state.images.limit); loadImages(); });
  $("images-next").addEventListener("click", () => { state.images.offset += state.images.limit; loadImages(); });
  $("extract-images").addEventListener("click", extractImages);
  $("choose-image").addEventListener("click", () => $("image-file").click());
  $("image-file").addEventListener("change", () => chooseImageFile($("image-file").files[0]));
  $("upload-image").addEventListener("click", saveImage);
  document.querySelectorAll(".canvas-tools input, .canvas-tools textarea").forEach(input => input.addEventListener("input", drawImageCanvas));
  $("image-canvas").addEventListener("pointerdown", onCanvasPointerDown);
  $("image-canvas").addEventListener("pointermove", onCanvasPointerMove);
  $("image-canvas").addEventListener("pointerup", onCanvasPointerUp);
  $("image-canvas").addEventListener("pointercancel", onCanvasPointerUp);
  $("reset-overlay").addEventListener("click", () => { const selected = state.images.selected; if (!selected) return; resetImageControls(Number(selected.width), Number(selected.height)); drawImageCanvas(); });

  $("choose-video").addEventListener("click", () => $("video-file").click());
  $("video-file").addEventListener("change", () => chooseVideoFile($("video-file").files[0]));
  $("upload-video").addEventListener("click", saveVideo);
  $("build-patch").addEventListener("click", exportPatch);
  $("install-patch").addEventListener("click", installPatch);
  $("clear-log").addEventListener("click", () => { $("activity-log").textContent = "No actions yet."; });
  document.addEventListener("keydown", event => {
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "s") {
      event.preventDefault();
      if (state.tab === "dialogue" && !$("save-dialogue").disabled) saveDialogue();
      if (state.tab === "strings" && !$("save-string").disabled) saveString();
      if (state.tab === "images" && !$("upload-image").disabled) saveImage();
      if (state.tab === "videos" && !$("upload-video").disabled) saveVideo();
    }
    if (event.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName || "")) {
      event.preventDefault();
      const target = { dialogue: "dialogue-search", strings: "strings-search", images: "images-search" }[state.tab];
      if (target) $(target).focus();
    }
  });
}

async function init() {
  bindEvents();
  await Promise.all([refreshStatus(), loadNames(), loadDialogue()]);
  if (document.fonts?.ready) document.fonts.ready.then(drawImageCanvas);
}

init();
