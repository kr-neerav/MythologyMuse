const $ = (id) => document.getElementById(id);
let BUNDLE = null;

async function api(path, opts) {
  let r;
  try {
    r = await fetch(path, opts);
  } catch (e) {
    throw new Error("NETDOWN");
  }
  if (!r.ok) {
    let detail = "";
    try { detail = (await r.json()).error || ""; } catch (e) { /* html */ }
    throw new Error("HTTP " + r.status + (detail ? ": " + detail : ""));
  }
  return r.json();
}

async function refreshKey() {
  try {
    const k = await api("/api/key-status");
    const b = $("keybadge");
    b.textContent = k.configured ? "image key: ready" : "image key: missing";
    b.className = "pill " + (k.configured ? "pass" : "fail");
  } catch (e) { /* badge stays neutral */ }
}

async function refreshChapters() {
  const myth = $("myth").value.trim();
  refreshKey();
  const data = await api("/api/chapters?mythology=" + encodeURIComponent(myth));
  const sel = $("chapter");
  sel.innerHTML = "";
  for (const c of data.chapters) {
    const o = document.createElement("option");
    o.value = c; o.textContent = c;
    sel.appendChild(o);
  }
}

function pill(text, cls) {
  return `<span class="pill ${cls || ""}">${text}</span>`;
}

async function loadChapter() {
  const myth = $("myth").value.trim();
  const id = $("chapter").value;
  BUNDLE = await api("/api/chapter?mythology=" + encodeURIComponent(myth)
    + "&id=" + encodeURIComponent(id));
  render();
}

function render() {
  const b = BUNDLE;
  const rev = b.review || {};
  const readyCount = b.roster.filter((r) => r.sheet_state === "ready").length;
  const countr = `&nbsp;sheets picked ${readyCount}/${b.roster.length}`;
  $("meta").innerHTML =
    `<h3>${b.chapter}</h3>
     <div class="row">eval ${pill(b.eval_verdict || "none",
       b.eval_verdict === "PASS" ? "pass" : b.eval_verdict === "FAIL" ? "fail" : "")}
       ${b.eval_dry_run ? pill("dry-run") : pill("live")}
       &nbsp;board ${b.counts.board} · prompts ${b.counts.prompts} ·
       hindi ${b.counts.hindi} · roster ${b.counts.roster}</div>
     <div class="row">chapter review: ${pill(rev.chapter_decision || "unreviewed",
       rev.chapter_decision || "")}
       <button class="ghost" data-chap="approved">Approve chapter</button>
       <button class="ghost" data-chap="needs_redo">Request redo</button>${countr}</div>`;
  $("meta").querySelectorAll("[data-chap]").forEach((btn) => {
    btn.onclick = () => postReview(null, btn.dataset.chap, "");
  });

  wireBatchBar();

  const myth = $("myth").value.trim();
  const imgUrl = (f) => "/api/studio-image?mythology=" + encodeURIComponent(myth)
    + "&chapter=" + encodeURIComponent(b.chapter) + "&file=" + encodeURIComponent(f);
  $("slides").innerHTML = b.slides.map((s) => {
    const st = (rev.slides || {})[String(s.slide)] || {};
    const cast = (s.subjects || []).filter((x) => (x.kind || "") !== "scene");
    const place = (s.subjects || []).filter((x) => (x.kind || "") === "scene");
    const placeCard = place.map((x) => {
      const mock = ((b.roster.find((r) => r.flow_ref === x.flow_ref) || {}).mock_sheet) || "";
      const stat = `<span class="genstat" id="gs-${s.slide}"></span>`;
      let face, actions;
      if (x.sheet_state === "ready") {
        face = `<img class="zoomable" title="Hover to preview, click to zoom" src="${imgUrl(x.sheet_final)}" alt="${x.name}">`;
        actions = `<div class="chip ready">selected</div>`
          + `<button class="ghost" data-gen-scene-slide="${s.slide}">Regenerate</button>${stat}`;
      } else if (x.sheet_state === "review") {
        face = `<div class="cands">` + x.sheet_candidates.map((f, k) =>
          `<div><img class="zoomable" title="Hover to preview, click to zoom" src="${imgUrl(f)}" alt="${x.name} candidate ${k + 1}">`
          + `<button class="ghost" title="Finalize this look for ${x.name}" data-pick-scene-slide="${s.slide}" data-pick-file="${f}">Use ${k + 1}</button></div>`
        ).join("") + `</div>`;
        actions = `<div class="chip missing">pick one</div>`
          + `<button class="ghost" data-gen-scene-slide="${s.slide}">Regenerate</button>${stat}`;
      } else if (x.generatable === false) {
        face = mock;
        actions = `<div class="chip missing">not a place sheet</div>`;
      } else {
        face = mock;
        actions = `<div class="chip missing">missing</div>`
          + `<button class="ghost" data-gen-scene-slide="${s.slide}">Generate</button>${stat}`;
      }
      return `<div class="castcard place ${x.sheet_state}"><div class="nm">Place: ${x.name}</div>${face}${actions}</div>`;
    }).join("");
    const gatecast = place.concat(cast);
    const unpicked = gatecast.filter((x) => x.sheet_state !== "ready"
      && x.generatable !== false);
    const ungenerated = gatecast.filter((x) => x.sheet_state === "missing"
      && x.generatable !== false);
    const strip = cast.map((x, i) => {
      const mock = ((b.roster.find((r) => r.flow_ref === x.flow_ref) || {}).mock_sheet) || "";
      let face, actions;
      const stat = `<span class="genstat" id="gc-${s.slide}-${i}"></span>`;
      if (x.sheet_state === "ready") {
        face = `<img class="zoomable" title="Hover to preview, click to zoom" src="${imgUrl(x.sheet_final)}" alt="${x.name}">`;
        actions = `<div class="chip ready">selected</div>`
          + `<button class="ghost" data-gen-char-slide="${s.slide}" data-gen-char-idx="${i}">Regenerate</button>${stat}`;
      } else if (x.sheet_state === "review") {
        face = `<div class="cands">` + x.sheet_candidates.map((f, k) =>
          `<div><img class="zoomable" title="Hover to preview, click to zoom" src="${imgUrl(f)}" alt="${x.name} candidate ${k + 1}">`
          + `<button class="ghost" title="Finalize this look for ${x.name}" data-pick-slide="${s.slide}" data-pick-idx="${i}" data-pick-file="${f}">Use ${k + 1}</button></div>`
        ).join("") + `</div>`;
        actions = `<div class="chip missing">pick one</div>`
          + `<button class="ghost" data-gen-char-slide="${s.slide}" data-gen-char-idx="${i}">Regenerate</button>${stat}`;
      } else if (x.generatable === false) {
        face = mock;
        actions = `<div class="chip missing">not a character — no sheet</div>`;
      } else {
        face = mock;
        actions = `<div class="chip missing">missing</div>`
          + `<button class="ghost" data-gen-char-slide="${s.slide}" data-gen-char-idx="${i}">Generate</button>${stat}`;
      }
      return `<div class="castcard ${x.sheet_state}">${face}<div class="nm">${x.name}</div>${actions}</div>`;
    }).join("");
    const gate = unpicked.length
      ? `disabled title="Waiting for picks: ${unpicked.map((x) => x.name).join(", ")}"`
      : `title="Cast ready"`;
    const hero = s.panel_final
      ? `<img class="zoomable hero" title="Hover to preview, click to zoom" src="${imgUrl(s.panel_final)}" alt="slide ${s.slide} final panel">`
      : s.mock_panel;
    return `<div class="slide"><div>${hero}</div><div>
      <h4>${s.slide_label}</h4>
      <div class="txt">${s.on_slide_text}</div>
      ${s.location ? `<div class="txt"><b>Place:</b> ${s.location}</div>` : ""}
      <div class="txt"><b>Characters in this slide:</b></div>
      <div class="caststrip">${(placeCard + strip) || "—"}</div>
      ${s.panel_final ? `<div class="txt"><b>Panel selected:</b></div><div class="cands"><img class="zoomable" title="Hover to preview, click to zoom" src="${imgUrl(s.panel_final)}" alt="slide ${s.slide} final panel"></div><div class="chip ready">selected</div>` : (s.panel_candidates && s.panel_candidates.length) ? `<div class="txt"><b>Latest panel render (pick one to finalize):</b></div><div class="cands">` + s.panel_candidates.map((f, k) => `<div><img class="zoomable" title="Hover to preview, click to zoom" src="${imgUrl(f)}" alt="slide ${s.slide} panel ${k + 1}"><button class="ghost" title="Finalize this render for slide ${s.slide}" data-pick-panel="${s.slide}" data-pick-file="${f}">Use ${k + 1}</button></div>`).join("") + `</div>` : ""}
      <div class="txt">${s.size}</div>
      ${s.panel_history ? histHtml(s.panel_history) : ""}
      ${ungenerated.length ? `<div><button class="ghost" data-gen-missing="${s.slide}">`
        + `Generate ${ungenerated.length} missing sheet${ungenerated.length > 1 ? "s" : ""}`
        + ` (${ungenerated.map((x) => x.name).join(", ")})</button>
        <span class="genstat" id="gm-${s.slide}"></span></div>` : ""}
      <pre>${s.muse_prompt}</pre>
      <div class="txt"><b>Hindi:</b> ${s.hindi_text || "—"}</div>
      <div class="rev">${pill(st.decision || "unreviewed", st.decision || "")}
        <button class="ghost" data-s="${s.slide}" data-d="approved">Approve</button>
        <button class="ghost" data-s="${s.slide}" data-d="needs_redo">Redo</button>
        <button class="ghost" data-gen-panel="${s.slide}" ${gate}>Generate panel</button>
        <span class="genstat" id="gp-${s.slide}"></span>
        ${st.note ? "<span>" + st.note + "</span>" : ""}</div>
    </div></div>`;
  }).join("");
  document.querySelectorAll("#slides [data-s]").forEach((btn) => {
    btn.onclick = () => {
      const note = btn.dataset.d === "needs_redo"
        ? prompt("Redo note (maps to a CLI --redo-comic rerun later):", "") || ""
        : "";
      postReview(Number(btn.dataset.s), btn.dataset.d, note);
    };
  });
  document.querySelectorAll("[data-gen-panel]").forEach((btn) => {
    if (btn.disabled) return;
    const slide = Number(btn.dataset.genPanel);
    const s = BUNDLE.slides.find((x) => x.slide === slide) || {};
    const refs = (s.subjects || []).filter((x) => x.sheet_state === "ready"
      && x.generatable !== false).map((x) => x.name);
    btn.onclick = () => triggerGenerate(
      { kind: "panel", slide },
      "gp-" + slide,
      "Generate 2 panel candidates for slide " + slide + " with "
        + refs.length + " refs (" + (refs.join(", ") || "none") + ")? Live spend.",
      btn);
  });
  document.querySelectorAll("[data-gen-missing]").forEach((btn) => {
    btn.onclick = () => generateMissing(Number(btn.dataset.genMissing), btn);
  });
  document.querySelectorAll("[data-gen-scene-slide]").forEach((btn) => {
    const slide = Number(btn.dataset.genSceneSlide);
    const subj = (BUNDLE.slides.find((x) => x.slide === slide).subjects || [])
      .find((x) => (x.kind || "") === "scene");
    const regen = subj.sheet_state !== "missing";
    btn.onclick = () => triggerGenerate(
      { kind: "sheet", ref: subj.flow_ref },
      `gs-${slide}`,
      `${regen ? "Regenerate" : "Generate"} 2 place candidates for ${subj.name} (landscape)`
        + `${regen ? " (candidates refresh; current pick kept until you pick again)" : ""}? Live spend.`,
      btn);
  });
  document.querySelectorAll("[data-pick-scene-slide]").forEach((btn) => {
    const slide = Number(btn.dataset.pickSceneSlide);
    const subj = (BUNDLE.slides.find((x) => x.slide === slide).subjects || [])
      .find((x) => (x.kind || "") === "scene");
    btn.onclick = () => pickCandidate(subj, btn.dataset.pickFile,
      `gs-${slide}`, btn);
  });
  document.querySelectorAll("[data-gen-char-slide]").forEach((btn) => {
    const slide = Number(btn.dataset.genCharSlide);
    const idx = Number(btn.dataset.genCharIdx);
    const subj = (BUNDLE.slides.find((x) => x.slide === slide).subjects || [])
      .filter((x) => (x.kind || "") !== "scene")[idx];
    const regen = subj.sheet_state !== "missing";
    btn.onclick = () => triggerGenerate(
      { kind: "sheet", ref: subj.flow_ref },
      `gc-${slide}-${idx}`,
      `${regen ? "Regenerate" : "Generate"} 2 sheet candidates for ${subj.name}`
        + `${regen ? " (candidates refresh; current pick kept until you pick again)" : ""}? Live spend.`,
      btn);
  });
  document.querySelectorAll("[data-pick-panel]").forEach((btn) => {
    btn.onclick = () => pickPanel(Number(btn.dataset.pickPanel),
      btn.dataset.pickFile, btn);
  });
  document.querySelectorAll("[data-pick-slide]").forEach((btn) => {
    const slide = Number(btn.dataset.pickSlide);
    const idx = Number(btn.dataset.pickIdx);
    const subj = (BUNDLE.slides.find((x) => x.slide === slide).subjects || [])
      .filter((x) => (x.kind || "") !== "scene")[idx];
    btn.onclick = () => pickCandidate(subj, btn.dataset.pickFile,
      `gc-${slide}-${idx}`, btn);
  });
  renderSlidesTab(imgUrl);
}

/* Slides tab: one full-width final per slide, English text below.
   Reuses the chapter bundle already loaded by loadChapter, so the
   chapter picker above drives both tabs. Finals surface here once
   generated; otherwise the mock placeholder shows with a status. */
function renderSlidesTab(imgUrl) {
  const b = BUNDLE;
  const host = $("slidesReview");
  if (!host) return;
  const rev = b.review || {};
  host.innerHTML = b.slides.map((s) => {
    const st = (rev.slides || {})[String(s.slide)] || {};
    const visual = s.panel_final
      ? `<img class="zoomable readhero" title="Hover to preview, click to zoom" src="${imgUrl(s.panel_final)}" alt="slide ${s.slide} final">`
      : `<div class="readmock">${s.mock_panel}<div class="chip missing">final not generated yet</div></div>`;
    return `<article class="readslide"><div>${visual}</div>
      <h4>${s.slide_label}</h4>
      <p class="readenglish">${s.on_slide_text || "—"}</p>
      <div class="rev">${pill(st.decision || "unreviewed", st.decision || "")}
        <button class="ghost" data-rs="${s.slide}" data-d="approved">Approve</button>
        <button class="ghost" data-rs="${s.slide}" data-d="needs_redo">Redo</button>
        ${st.note ? "<span>" + st.note + "</span>" : ""}</div>
    </article>`;
  }).join("");
  host.querySelectorAll("[data-rs]").forEach((btn) => {
    btn.onclick = () => {
      const note = btn.dataset.d === "needs_redo"
        ? prompt("Redo note (maps to a CLI --redo-comic rerun later):", "") || ""
        : "";
      postReview(Number(btn.dataset.rs), btn.dataset.d, note);
    };
  });
}

function showTab(name) {
  const review = name !== "slides";
  $("tab-review").hidden = !review;
  $("tab-slides").hidden = review;
  $("tabbtn-review").className = "tab" + (review ? " active" : "");
  $("tabbtn-slides").className = "tab" + (review ? "" : " active");
}

async function pickPanel(slide, file, btn) {
  btn.disabled = true;
  try {
    await api("/api/select", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mythology: $("myth").value.trim(),
        chapter: BUNDLE.chapter, kind: "panel", slide, file }) });
  } catch (e) {
    alert(String(e.message) === "NETDOWN"
      ? "server is not running — keep the server.py terminal open, then reload"
      : "server refused: " + e.message);
    btn.disabled = false;
    return;
  }
  await loadChapter();
}

async function pickCandidate(subj, file, statId, btn) {
  const stat = document.getElementById(statId);
  btn.disabled = true;
  stat.textContent = "picking…";
  try {
    await api("/api/select", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mythology: $("myth").value.trim(),
        chapter: BUNDLE.chapter, ref: subj.flow_ref, file }) });
  } catch (e) {
    stat.textContent = String(e.message) === "NETDOWN"
      ? "server is not running — keep the server.py terminal open, then reload"
      : "server refused: " + e.message;
    btn.disabled = false;
    return;
  }
  await loadChapter();
}

async function generateMissing(slide, btn) {
  const s = BUNDLE.slides.find((x) => x.slide === slide);
  const missing = (s.subjects || []).filter((x) => x.sheet_state === "missing" && x.generatable !== false);
  if (!missing.length) return;
  if (!confirm("Generate " + missing.length + " missing sheets for slide "
      + slide + " (" + missing.map((x) => x.name).join(", ")
      + ")? Live spend, one after another.")) return;
  const extra = prompt("Optional style tweak applied to all (blank for none):",
    "") || "";
  btn.disabled = true;
  let ok = 0;
  for (const m of missing) {
    if (await generateOne({ kind: "sheet", ref: m.flow_ref },
        "gm-" + slide, extra, null)) ok++;
  }
  btn.disabled = false;
  alert("Sheets done: " + ok + "/" + missing.length
    + ". Reloading to unlock the panel button.");
  await loadChapter();
}

const FLYING = new Set();
async function triggerGenerate(target, statId, confirmText, btn) {
  if (FLYING.has(statId)) return;
  if (!confirm(confirmText)) return;
  const extra = prompt("Optional style tweak (blank for none):", "") || "";
  const ok = await generateOne(target, statId, extra, btn);
  if (ok && target.kind === "sheet") await loadChapter();
}

function generateOne(target, statId, extra, btn) {
  const myth = $("myth").value.trim();
  const stat = document.getElementById(statId);
  FLYING.add(statId);
  if (btn) btn.disabled = true;
  stat.textContent = "queued… (paid job — locked until it finishes)";
  return api("/api/generate", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mythology: myth, chapter: BUNDLE.chapter,
      target, extra_prompt: extra }) }).then((res) => new Promise((done) => {
    const poll = setInterval(async () => {
      let job;
      try {
        job = await api("/api/job?id=" + encodeURIComponent(res.job_id));
      } catch (e) {
        clearInterval(poll);
        stat.textContent = "lost contact with server — reload the page";
        FLYING.delete(statId);
        if (btn) btn.disabled = false;
        done(false);
        return;
      }
      stat.textContent = job.status + "… (paid job running)";
      if (job.status === "done" || job.status === "error") {
        clearInterval(poll);
        FLYING.delete(statId);
        if (btn) btn.disabled = false;
        if (job.status === "done") {
          if (target.kind === "panel") {
            // Renders persist on disk and resurface via the bundle (with
            // lineage), so reload: approve/reload can never lose them.
            done(true);
            try { await loadChapter(); }
            catch (e) { stat.textContent = "render kept — reload the page to see it"; }
            return;
          }
          const out = job.result;
          const cands = Array.isArray(out) ? out : out.candidates;
          const lin = Array.isArray(out) ? null : out.lineage;
          const names = (res.ref_names && res.ref_names.length)
            ? res.ref_names.join(", ") : res.refs_used + " file(s)";
          stat.textContent = "done (" + cands.length + ", refs: " + names + ")";
          showCandidates(stat, res.prefix, lin);
          done(true);
        } else {
          stat.textContent = "error: " + job.error;
          done(false);
        }
      }
    }, 3000);
  })).catch((e) => {
    stat.textContent = String(e.message) === "NETDOWN"
      ? "server is not running — keep the server.py terminal open, then reload"
      : "server refused: " + e.message + " — see the server terminal";
    FLYING.delete(statId);
    if (btn) btn.disabled = false;
    return false;
  });
}

function wireBatchBar() {
  $("genall").onclick = () => batchGenerate(
    BUNDLE.roster.map((r) => r.flow_ref), "all");
}

async function batchGenerate(refs, which) {
  if (!refs.length) return;
  if (!confirm("Generate " + refs.length + " sheets × 2 candidates (" + which
      + ")? Live spend, one after another.")) return;
  const extra = prompt("Optional style tweak applied to all (blank for none):",
    "") || "";
  $("genall").disabled = true;
  let ok = 0;
  for (const ref of refs) {
    $("batchstat").textContent = `(${ok + 1}/${refs.length}) ${ref}…`;
    if (await generateOne({ kind: "sheet", ref }, "batchstat", extra, null)) ok++;
  }
  $("genall").disabled = false;
  $("batchstat").textContent = "";
  alert("Batch finished: " + ok + "/" + refs.length + " sheets done. Reloading.");
  await loadChapter();
}

function showCandidates(stat, prefix, lineage) {
  const myth = $("myth").value.trim();
  const wrap = document.createElement("div");
  wrap.className = "cands";
  for (const i of [1, 2]) {
    const img = document.createElement("img");
    img.onerror = () => img.remove();
    img.className = "zoomable";
    img.title = "Hover to preview, click to zoom";
    img.src = "/api/studio-image?mythology=" + encodeURIComponent(myth)
      + "&chapter=" + encodeURIComponent(BUNDLE.chapter)
      + "&file=" + encodeURIComponent(prefix + "_" + i + ".jpg");
    img.alt = prefix + " candidate " + i;
    wrap.appendChild(img);
  }
  stat.appendChild(wrap);
  if (lineage) stat.appendChild(lineageLine(lineage));
}

/* Zoom: hover a character image for a large preview, click for a modal.
   Delegated: slides re-render via innerHTML, so per-image binding would die.
   Preview/modal reuse the same cached URL — no extra fetch, no spend. */
const HOVER_OK = typeof window !== "undefined" && window.matchMedia
  && window.matchMedia("(hover: hover) and (pointer: fine)").matches;
let hoverBox = null;
function hoverEl() {
  if (!hoverBox) {
    hoverBox = document.createElement("div");
    hoverBox.id = "hoverzoom";
    const img = document.createElement("img");
    img.alt = "";
    hoverBox.appendChild(img);
    document.body.appendChild(hoverBox);
  }
  return hoverBox;
}
function placeHover(x, y) {
  const box = hoverEl();
  const pad = 18;
  const r = box.getBoundingClientRect
    ? box.getBoundingClientRect() : { width: 440, height: 440 };
  let left = x + pad, top = y + pad;
  if (left + r.width > window.innerWidth - 8) left = x - r.width - pad;
  if (top + r.height > window.innerHeight - 8) top = y - r.height - pad;
  box.style.left = Math.max(8, left) + "px";
  box.style.top = Math.max(8, top) + "px";
}
function showHover(img, x, y) {
  if (!HOVER_OK) return;
  const box = hoverEl();
  box.firstChild.src = img.src;
  box.firstChild.alt = img.alt || "";
  box.style.display = "block";
  placeHover(x == null ? 0 : x, y == null ? 0 : y);
}
function hideHover() { if (hoverBox) hoverBox.style.display = "none"; }

let zoomBox = null;
function openZoom(src, alt) {
  closeZoom();
  hideHover();
  zoomBox = document.createElement("div");
  zoomBox.className = "zoombox";
  const bg = document.createElement("div");
  bg.className = "zoombox-bg";
  bg.onclick = closeZoom;
  const fig = document.createElement("figure");
  const img = document.createElement("img");
  img.src = src;
  img.alt = alt || "";
  const cap = document.createElement("figcaption");
  cap.textContent = alt || "";
  const x = document.createElement("button");
  x.className = "ghost zoombox-x";
  x.textContent = "Close";
  x.onclick = closeZoom;
  fig.appendChild(img);
  fig.appendChild(cap);
  fig.appendChild(x);
  zoomBox.appendChild(bg);
  zoomBox.appendChild(fig);
  document.body.appendChild(zoomBox);
  document.body.style.overflow = "hidden";
}
function closeZoom() {
  if (!zoomBox) return;
  zoomBox.remove();
  zoomBox = null;
  document.body.style.overflow = "";
}
function zoomTarget(e) {
  const t = e && e.target;
  return (t && t.closest) ? t.closest("img.zoomable") : null;
}
document.addEventListener("click", (e) => {
  const t = zoomTarget(e);
  if (t) openZoom(t.src, t.alt);
});
document.addEventListener("mouseover", (e) => {
  if (!zoomBox) {
    const t = zoomTarget(e);
    if (t) showHover(t, e.clientX, e.clientY);
  }
});
document.addEventListener("mouseout", (e) => {
  if (zoomTarget(e)) hideHover();
});
document.addEventListener("mousemove", (e) => {
  if (hoverBox && hoverBox.style.display === "block") {
    placeHover(e.clientX, e.clientY);
  }
});
document.addEventListener("keydown", (e) => {
  if (e && e.key === "Escape") closeZoom();
});
window.addEventListener("scroll", hideHover, true);

function anchoringText(lin) {
  const bits = [];
  if (lin.prev_anchor && lin.prev_anchor.ref) {
    bits.push("chained from " + lin.prev_anchor.ref + "'s picked sheet");
  }
  if (lin.file_attached && lin.file_attached.length) {
    bits.push("file-attached: " + lin.file_attached.join(", "));
    if (lin.file_override) {
      bits.push("stale-text override for " + lin.file_attached.join(", "));
    }
  }
  if (!bits.length) {
    bits.push((lin.refs && lin.refs.length)
      ? "named only (" + lin.refs.join(", ") + "), no anchor — regenerate sheets once for face-locking"
      : "no cast anchors");
  }
  if (lin.omitted_refs) bits.push("+" + lin.omitted_refs + " cast beyond anchor budget");
  if (lin.fallback) bits.push("FALLBACK: " + (lin.fallback_reason || "anchors rejected"));
  return bits.join(" · ");
}

function histHtml(lin) {
  const when = lin.at ? new Date(lin.at * 1000).toLocaleString() : "";
  const cls = (lin.fallback || !(lin.refs && lin.refs.length)) ? "hist warn" : "hist";
  return `<div class="${cls}">Last render ${when}: ${anchoringText(lin)}.</div>`;
}

function lineageLine(lin) {
  const div = document.createElement("div");
  div.className = "hist" + ((lin.fallback || !(lin.refs && lin.refs.length)) ? " warn" : "");
  div.textContent = "Rendered — " + anchoringText(lin) + ". ";
  const det = document.createElement("details");
  const sum = document.createElement("summary");
  sum.textContent = "effective prompt";
  const pre = document.createElement("pre");
  pre.textContent = lin.prompt || "";
  det.appendChild(sum);
  det.appendChild(pre);
  div.appendChild(det);
  return div;
}

async function postReview(slide, decision, note) {
  const myth = $("myth").value.trim();
  await api("/api/review", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mythology: myth, chapter: BUNDLE.chapter,
      slide, decision, note }) });
  await loadChapter();
}

$("load").onclick = loadChapter;
$("tabbtn-review").onclick = () => showTab("review");
$("tabbtn-slides").onclick = () => showTab("slides");
refreshChapters().then(() => loadChapter()).catch((e) => {
  $("meta").innerHTML = "<h3>Studio</h3><div class='row'>" + e.message + "</div>";
});
