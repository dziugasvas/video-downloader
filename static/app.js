// Video Downloader front end. Plain JavaScript, no build step.
// The API location comes from <body data-api="...">, so this file can be
// reused in another app (e.g. data-api="/api/downloader").
(() => {
  "use strict";

  const API = ((document.querySelector("[data-api]") || document.body).dataset.api || "api").replace(/\/$/, "");
  const $ = (id) => document.getElementById(id);
  const ACTIVE = ["queued", "starting", "downloading", "processing"];

  const FORMAT_HINTS = {
    mp4: "Plays everywhere: iPhone, Samsung and other Android phones, Mac, Windows and TVs.",
    mkv: "Original quality, no conversion. Best for computers and VLC. Phones may not play it.",
    mp3: "Audio only. Plays on anything.",
    m4a: "Audio only, smaller than MP3 at the same quality. Great for podcasts.",
  };
  const AUDIO_ONLY = ["mp3", "m4a"];

  const store = {
    get(key, fallback) { try { return localStorage.getItem(key) ?? fallback; } catch { return fallback; } },
    set(key, value) { try { localStorage.setItem(key, value); } catch { /* ignore */ } },
  };

  let format = store.get("vd.format", "mp4");
  let quality = store.get("vd.quality", "1080");
  let defaultFolder = "~/Downloads/Videos";
  let pollTimer = null;

  // ---------- API helper ----------
  async function api(path, options = {}) {
    const res = await fetch(`${API}${path}`, {
      method: options.method || "GET",
      headers: options.body ? { "Content-Type": "application/json" } : {},
      body: options.body ? JSON.stringify(options.body) : undefined,
    });
    let data = null;
    try { data = await res.json(); } catch { /* empty */ }
    if (!res.ok) throw new Error((data && data.detail) || `Request failed (${res.status})`);
    return data;
  }

  // ---------- Formatting ----------
  function bytes(n) {
    if (n == null || !isFinite(n)) return "";
    const units = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    while (n >= 1000 && i < units.length - 1) { n /= 1000; i++; }
    return `${n.toFixed(n < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
  }
  function duration(sec) {
    if (sec == null) return "";
    sec = Math.max(0, Math.round(sec));
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
  }
  function clock(ts) {
    return new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  function el(tag, attrs = {}, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") node.className = v;
      else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
      else if (v != null) node.setAttribute(k, v);
    }
    for (const c of children) if (c != null) node.append(c);
    return node;
  }
  const ICONS = {
    x: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>',
    finder: '<svg viewBox="0 0 24 24"><path d="M3.5 7.5a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z" stroke-linejoin="round"/></svg>',
    video: '<svg viewBox="0 0 24 24"><rect x="3" y="6" width="13" height="12" rx="2.5"/><path d="M16 10.5l5-3v9l-5-3z"/></svg>',
    audio: '<svg viewBox="0 0 24 24"><path d="M9 18V6l11-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/></svg>',
  };
  function iconButton(icon, title, onclick) {
    const b = el("button", { class: "vd-icon-btn", type: "button", title, "aria-label": title, onclick });
    b.innerHTML = ICONS[icon];
    return b;
  }

  // ---------- Toast ----------
  let toastTimer;
  function toast(message, bad = false) {
    const t = $("vd-toast");
    t.textContent = message;
    t.classList.toggle("vd-bad", bad);
    t.classList.add("vd-show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => t.classList.remove("vd-show"), bad ? 6000 : 3000);
  }

  // ---------- Format + quality pickers ----------
  function markSelected(groupId, value) {
    for (const b of $(groupId).querySelectorAll("button")) {
      b.setAttribute("aria-checked", String(b.dataset.v === value));
    }
  }
  function updateHint() {
    let hint = FORMAT_HINTS[format];
    if (format === "mp4" && ["1440", "2160", "best"].includes(quality)) {
      hint += " Above 1080p YouTube only offers AV1, which plays on most devices from the last few years. Pick 1080p for older phones and TVs.";
    }
    $("vd-hint").textContent = hint;
  }
  function setFormat(v) {
    if (!FORMAT_HINTS[v]) v = "mp4";
    format = v;
    store.set("vd.format", v);
    markSelected("vd-format", v);
    $("vd-quality-row").hidden = AUDIO_ONLY.includes(v);
    updateHint();
  }
  function setQuality(v) {
    if (!$("vd-quality").querySelector(`button[data-v="${v}"]`)) v = "1080";
    quality = v;
    store.set("vd.quality", v);
    markSelected("vd-quality", v);
    updateHint();
  }
  $("vd-format").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-v]");
    if (b) setFormat(b.dataset.v);
  });
  $("vd-quality").addEventListener("click", (e) => {
    const b = e.target.closest("button[data-v]");
    if (b) setQuality(b.dataset.v);
  });

  // ---------- Folder ----------
  const folderInput = $("vd-folder");
  function folder() { return folderInput.value.trim() || defaultFolder; }
  folderInput.addEventListener("change", () => store.set("vd.folder", folderInput.value.trim()));
  $("vd-choose").addEventListener("click", async () => {
    try {
      const { path } = await api("/choose-folder", { method: "POST", body: { path: folder() } });
      if (path) { folderInput.value = path; store.set("vd.folder", path); }
    } catch (err) { toast(err.message, true); }
  });
  $("vd-open").addEventListener("click", async () => {
    try { await api("/open-folder", { method: "POST", body: { path: folder() } }); }
    catch (err) { toast(err.message, true); }
  });

  // ---------- Start downloads ----------
  async function startDownload() {
    const links = $("vd-links").value.trim();
    if (!links) { $("vd-links").focus(); return; }
    const btn = $("vd-download");
    btn.disabled = true;
    try {
      const res = await api("/downloads", { method: "POST", body: { urls: links, format, quality, folder: folder() } });
      $("vd-links").value = "";
      const n = res.jobs.length;
      let msg = `Added ${n} download${n === 1 ? "" : "s"}.`;
      if (res.skipped.length) msg += ` Skipped ${res.skipped.length} item(s) that weren't links.`;
      toast(msg, res.skipped.length > 0);
      refresh();
    } catch (err) {
      toast(err.message, true);
    } finally {
      btn.disabled = false;
    }
  }
  $("vd-download").addEventListener("click", startDownload);
  $("vd-links").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) { e.preventDefault(); startDownload(); }
  });

  // ---------- Rendering jobs ----------
  const jobNodes = new Map();

  function jobMeta(job) {
    const parts = [];
    const item = job.item_count ? `Video ${job.item_index} of ${job.item_count}` : "";
    switch (job.status) {
      case "queued": return { text: `Waiting · ${job.label}` };
      case "starting": return { text: `Getting video info… · ${job.label}` };
      case "processing": return { text: [item, "Finishing up…"].filter(Boolean).join(" · ") };
      case "downloading":
        if (item) parts.push(item);
        parts.push(`${Math.floor(job.percent)}%`, job.label);
        if (job.total_bytes) parts.push(`${bytes(job.downloaded_bytes)} of ${bytes(job.total_bytes)}`);
        if (job.speed) parts.push(`${bytes(job.speed)}/s`);
        if (job.eta != null) parts.push(`${duration(job.eta)} left`);
        return { text: parts.join(" · ") };
      case "done": {
        const n = job.files.length;
        if (job.error) return { text: `Done (${n} file${n === 1 ? "" : "s"}), with problems: ${job.error}`, cls: "vd-err" };
        return { text: n > 1 ? `Done · ${n} files` : "Done", cls: "vd-ok" };
      }
      case "cancelled": return { text: "Cancelled" };
      case "error": return { text: job.error || "Download failed", cls: "vd-err" };
      default: return { text: job.status };
    }
  }

  function buildJob(job) {
    const title = el("div", { class: "vd-title" });
    const meta = el("div", { class: "vd-meta" });
    const actions = el("div", { class: "vd-actions" });
    const fill = el("div");
    const node = el("li", { class: "vd-job" },
      el("div", { class: "vd-job-top" }, el("div", { class: "vd-job-main" }, title, meta), actions),
      el("div", { class: "vd-bar" }, fill),
    );
    return { node, title, meta, actions, fill, actionsKey: "" };
  }

  function updateJob(ref, job) {
    ref.node.dataset.status = job.status;
    const hasTitle = Boolean(job.title);
    ref.title.textContent = hasTitle ? job.title : job.url;
    ref.title.classList.toggle("vd-pending", !hasTitle);
    ref.title.title = job.url;
    const { text, cls } = jobMeta(job);
    ref.meta.textContent = text;
    ref.meta.className = "vd-meta" + (cls ? " " + cls : "");
    ref.fill.style.width = `${["queued", "starting"].includes(job.status) ? 100 : job.status === "processing" ? Math.max(job.percent, 100) : job.percent}%`;

    // Rebuild buttons only when the status changes (keeps clicks reliable).
    const key = `${job.status}:${job.files.length > 0}`;
    if (key !== ref.actionsKey) {
      ref.actionsKey = key;
      ref.actions.replaceChildren();
      if (ACTIVE.includes(job.status)) {
        ref.actions.append(iconButton("x", "Cancel", () => cancelJob(job.id)));
      } else {
        if (job.files.length) {
          ref.actions.append(iconButton("finder", "Show in Finder", () => reveal(job.files[job.files.length - 1])));
        }
        ref.actions.append(iconButton("x", "Remove from list", () => removeJob(job.id)));
      }
    }
  }

  function renderJobs(jobs) {
    const list = $("vd-jobs");
    const seen = new Set();
    jobs.forEach((job, i) => {
      seen.add(job.id);
      let ref = jobNodes.get(job.id);
      if (!ref) { ref = buildJob(job); jobNodes.set(job.id, ref); }
      updateJob(ref, job);
      if (list.children[i] !== ref.node) list.insertBefore(ref.node, list.children[i] || null);
    });
    for (const [id, ref] of jobNodes) {
      if (!seen.has(id)) { ref.node.remove(); jobNodes.delete(id); }
    }
    $("vd-jobs-empty").hidden = jobs.length > 0;
    $("vd-clear-jobs").hidden = !jobs.some((j) => !ACTIVE.includes(j.status));
  }

  let historyKey = "";
  function renderHistory(items) {
    const key = items.map((h) => h.path + h.finished).join("|");
    if (key === historyKey) return;
    historyKey = key;
    const list = $("vd-history");
    list.replaceChildren(...items.map((h) => {
      const kind = el("span", { class: "vd-kind" });
      kind.innerHTML = h.audio ? ICONS.audio : ICONS.video;
      const name = h.path.split("/").pop();
      return el("li", {},
        kind,
        el("div", { class: "vd-job-main" },
          el("div", { class: "vd-title", title: h.path }, h.title || name),
          el("div", { class: "vd-meta" }, [h.label, bytes(h.size), clock(h.finished)].filter(Boolean).join(" · ")),
        ),
        el("div", { class: "vd-actions" }, iconButton("finder", "Show in Finder", () => reveal(h.path))),
      );
    }));
    $("vd-history-empty").hidden = items.length > 0;
    $("vd-clear-history").hidden = items.length === 0;
  }

  // ---------- Actions ----------
  async function cancelJob(id) {
    try { await api(`/downloads/${id}/cancel`, { method: "POST" }); refresh(); }
    catch (err) { toast(err.message, true); }
  }
  async function removeJob(id) {
    try { await api(`/downloads/${id}`, { method: "DELETE" }); refresh(); }
    catch (err) { toast(err.message, true); }
  }
  async function reveal(path) {
    try { await api("/reveal", { method: "POST", body: { path } }); }
    catch (err) { toast(err.message, true); }
  }
  $("vd-clear-jobs").addEventListener("click", async () => { await api("/downloads/clear", { method: "POST" }); refresh(); });
  $("vd-clear-history").addEventListener("click", async () => { await api("/history/clear", { method: "POST" }); refresh(); });

  $("vd-update").addEventListener("click", async () => {
    const btn = $("vd-update");
    btn.disabled = true;
    btn.textContent = "Updating…";
    try {
      const { version } = await api("/update-ytdlp", { method: "POST" });
      $("vd-version").textContent = `yt-dlp ${version}`;
      toast(`yt-dlp is up to date (${version}).`);
    } catch (err) {
      toast(err.message, true);
    } finally {
      btn.disabled = false;
      btn.textContent = "Update yt-dlp";
    }
  });

  // ---------- Polling ----------
  async function refresh() {
    clearTimeout(pollTimer);
    let busy = false;
    try {
      const data = await api("/downloads");
      renderJobs(data.jobs);
      renderHistory(data.history);
      busy = data.jobs.some((j) => ACTIVE.includes(j.status));
    } catch {
      /* server restarting; try again shortly */
    }
    pollTimer = setTimeout(refresh, busy ? 700 : 2500);
  }

  async function loadStatus() {
    try {
      const s = await api("/status");
      defaultFolder = s.default_folder;
      folderInput.placeholder = defaultFolder;
      if (!folderInput.value) folderInput.value = store.get("vd.folder", "") || defaultFolder;
      $("vd-version").textContent = s.yt_dlp ? `yt-dlp ${s.yt_dlp}` : "yt-dlp not found";
      const warnings = $("vd-warnings");
      warnings.replaceChildren();
      const warn = (html) => { const w = el("span", { class: "vd-warning" }); w.innerHTML = html; warnings.append(w); };
      if (!s.ffmpeg) warn("ffmpeg missing: run <code>brew install ffmpeg</code>");
      if (!s.deno) warn("Deno missing (needed for YouTube): run <code>brew install deno</code>");
      if (!s.mac) $("vd-choose").hidden = true;
    } catch (err) {
      toast(err.message, true);
    }
  }

  setFormat(format);
  setQuality(quality);
  folderInput.value = store.get("vd.folder", "");
  loadStatus();
  refresh();
})();
