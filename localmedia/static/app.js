"use strict";
// ============================================================ utilidades
const $ = (s, el = document) => el.querySelector(s);
const main = $("#main");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const enc = encodeURIComponent;
const fmt = (s) => { s = Math.max(0, Math.floor(s || 0)); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = String(s % 60).padStart(2, "0"); return h ? `${h}:${String(m).padStart(2, "0")}:${x}` : `${m}:${x}`; };
const art = (tid) => tid ? `/api/art/${tid}` : "/static/cover.svg";
const ago = (s) => {
  if (!s) return t("nunca");
  const d = (Date.now() / 1000 - s);
  if (d < 60) return t("ahora");
  if (d < 3600) return t("hace {n} min", { n: Math.floor(d / 60) });
  if (d < 86400) return t("hace {n} h", { n: Math.floor(d / 3600) });
  return new Date(s * 1000).toLocaleString(LANG);
};

async function api(path, opts = {}) {
  const o = { headers: {}, ...opts };
  if (o.body && typeof o.body !== "string") { o.body = JSON.stringify(o.body); o.headers["Content-Type"] = "application/json"; }
  const r = await fetch(path, o);
  if (r.status === 401) { showLogin(); throw new Error("auth"); }
  if (!r.ok) throw new Error(`${r.status} ${path}`);
  const ct = r.headers.get("content-type") || "";
  return ct.includes("json") ? r.json() : r.text();
}

function toast(msg, ms = 2600) {
  const el = $("#toast"); el.textContent = msg; el.classList.remove("hidden");
  clearTimeout(toast._t); toast._t = setTimeout(() => el.classList.add("hidden"), ms);
}
function modal(html) { $("#modalBody").innerHTML = html; $("#modal").classList.remove("hidden"); return $("#modalBody"); }
function closeModal() { $("#modal").classList.add("hidden"); $("#modalBody").innerHTML = ""; }
$("#modalX").onclick = closeModal;
$("#modal").onclick = (e) => { if (e.target.id === "modal") closeModal(); };

// favoritas (ids)
let favs = new Set();
async function loadFavs() { try { favs = new Set(await api("/api/favorite-ids")); } catch (e) { } }

// ============================================================ reproductor web
const audio = $("#audio");
const P = { queue: [], idx: -1, shuffle: false, loop: false, order: [] };
function pOrder() { P.order = P.queue.map((_, i) => i); if (P.shuffle) { const cur = P.order.splice(P.idx >= 0 ? P.idx : 0, 1); for (let i = P.order.length - 1; i > 0; i--) { const j = Math.floor(Math.random() * (i + 1));[P.order[i], P.order[j]] = [P.order[j], P.order[i]]; } P.order.unshift(...cur); } }
function playList(tracks, start = 0, shuffle = false) {
  if (!tracks.length) return;
  if (OUT) return playOnEcho(tracks, start, shuffle);   // "Reproducir en: Echo …"
  P.queue = tracks.slice(); P.shuffle = shuffle; P.idx = shuffle ? Math.floor(Math.random() * tracks.length) : start;
  if (shuffle && start) P.idx = start;
  pOrder(); playIdx(P.idx); updateBtns();
}
function enqueue(tracks) { if (OUT) return playOnEcho(tracks, 0, false); if (!P.queue.length) return playList(tracks); P.queue.push(...tracks); P.order.push(...tracks.map((_, i) => P.queue.length - tracks.length + i)); toast(t("Añadidas {n} a la cola", { n: tracks.length })); }
function playIdx(i) {
  const tr = P.queue[i]; if (!tr) return;
  P.idx = i; audio.src = `/api/stream/${tr.id}`; audio.play().catch(() => { });
  $("#npTitle").textContent = tr.title; $("#npSub").textContent = [tr.artist, tr.album].filter(Boolean).join(" — ");
  $("#npArt").src = art(tr.id); document.title = `${tr.title} · Local Media for Alexa`;
  if ("mediaSession" in navigator) navigator.mediaSession.metadata = new MediaMetadata({ title: tr.title, artist: tr.artist, album: tr.album, artwork: [{ src: art(tr.id) }] });
  document.querySelectorAll("tr[data-tid]").forEach((row) => row.classList.toggle("playing", +row.dataset.tid === tr.id));
}
function step(d) {
  if (!P.queue.length) return;
  let k = P.order.indexOf(P.idx) + d;
  if (k >= P.order.length) { if (!P.loop) return; k = 0; }
  if (k < 0) k = P.loop ? P.order.length - 1 : 0;
  playIdx(P.order[k]);
}
audio.addEventListener("ended", () => step(1));
audio.addEventListener("timeupdate", () => { $("#pCur").textContent = fmt(audio.currentTime); const d = audio.duration || P.queue[P.idx]?.duration || 0; $("#pDur").textContent = fmt(d); if (d && !seeking) $("#pSeek").value = (audio.currentTime / d) * 1000; });
audio.addEventListener("play", () => $("#pPlay").textContent = "⏸");
audio.addEventListener("pause", () => $("#pPlay").textContent = "▶");
let seeking = false;
$("#pSeek").addEventListener("input", () => seeking = true);
$("#pSeek").addEventListener("change", (e) => { const d = audio.duration || 0; if (d && isFinite(d)) audio.currentTime = (e.target.value / 1000) * d; seeking = false; });
// con un Echo elegido, los botones del reproductor no pueden mandar ordenes al Echo
// (Amazon solo deja controlarlo con la voz): se explica en vez de no hacer nada
const echoOnly = (fn) => () => OUT ? toast(t("Controla {name} con la voz: «Alexa, pausa», «Alexa, siguiente», «Alexa, aleatorio»…", { name: OUT.name }), 5000) : fn();
$("#pPlay").onclick = echoOnly(() => { if (!audio.src) return; audio.paused ? audio.play() : audio.pause(); });
$("#pNext").onclick = echoOnly(() => step(1));
$("#pPrev").onclick = echoOnly(() => audio.currentTime > 4 ? (audio.currentTime = 0) : step(-1));
$("#pShuffle").onclick = echoOnly(() => { P.shuffle = !P.shuffle; pOrder(); updateBtns(); });
$("#pLoop").onclick = echoOnly(() => { P.loop = !P.loop; updateBtns(); });
$("#pVol").oninput = (e) => audio.volume = e.target.value / 100;
$("#pQueue").onclick = () => OUT ? echoQueue() : showQueue();

// ============================================================ "Reproducir en:" (navegador o Echo)
let OUT = null;   // {id, name} del Echo elegido o null = este navegador
try { OUT = JSON.parse(localStorage.getItem("lm-out") || "null"); } catch (e) { OUT = null; }
const devName = (d) => d.name || `Echo …${d.id.slice(-6)}`;
function setOut(o) {
  OUT = o;
  try { o ? localStorage.setItem("lm-out", JSON.stringify(o)) : localStorage.removeItem("lm-out"); } catch (e) { }
  $("#pOutIc").textContent = o ? "🔊" : "💻";
  $("#pOutLb").textContent = o ? o.name : t("Este navegador");
  $("#pOut").classList.toggle("on", !!o);
  $("#pOut").title = o ? t("Suena en {name} · pulsa para cambiar", { name: o.name }) : t("Elegir dónde suena");
  document.body.classList.toggle("out-echo", !!o);
  clearTimeout(setOut._t);
  if (o) { if (!audio.paused) audio.pause(); pollEcho(); }
  else if (P.queue[P.idx]) playIdxInfo(P.queue[P.idx]);
  else { $("#npTitle").textContent = t("Nada sonando"); $("#npSub").textContent = ""; $("#npArt").src = "/static/cover.svg"; }
}
function playIdxInfo(tr) {
  $("#npTitle").textContent = tr.title; $("#npSub").textContent = [tr.artist, tr.album].filter(Boolean).join(" — "); $("#npArt").src = art(tr.id);
}
async function playOnEcho(tracks, start = 0, shuffle = false) {
  const ids = tracks.map((x) => x.id);
  const first = tracks[start] || tracks[0];
  // descripcion que dira Alexa ("Reproduciendo la cola que preparaste: …"): la voz va en
  // el idioma de la skill, asi que se deja en español
  const desc = tracks.length === 1 ? first.title
    : shuffle ? `${tracks.length} canciones en aleatorio` : `${first.title} y ${tracks.length - 1} más`;
  try {
    await api(`/api/devices/${enc(OUT.id)}/queue`, { method: "POST", body: { track_ids: ids, desc, shuffle, first: shuffle ? null : start } });
  } catch (e) { return toast(t("No se pudo preparar la cola en el Echo")); }
  toast(t("Listo en {name}. Dile: «Alexa, abre mi colección»", { name: OUT.name }), 6000);
  pollEcho();
}
async function pollEcho() {
  clearTimeout(setOut._t);
  if (!OUT) return;
  try {
    const d = (await api("/api/devices")).find((x) => x.id === OUT.id);
    if (d && devName(d) !== OUT.name) setOut({ id: d.id, name: devName(d) });   // lo renombraste
    if (d && d.current) {
      $("#npTitle").textContent = d.current.title;
      $("#npArt").src = art(d.current.id);
      $("#npSub").textContent = d.playing ? t("🔊 Sonando en {name}", { name: OUT.name })
        : d.pending ? t("Preparado en {name} · di «Alexa, abre mi colección»", { name: OUT.name }) : t("En pausa en {name}", { name: OUT.name });
    } else {
      $("#npTitle").textContent = t("Nada sonando"); $("#npArt").src = "/static/cover.svg";
      $("#npSub").textContent = `🔊 ${OUT.name}`;
    }
  } catch (e) { }
  setOut._t = setTimeout(pollEcho, 5000);
}
async function echoQueue() {
  const d = await api(`/api/devices/${enc(OUT.id)}/queue`);
  if (!d.tracks.length) return toast(t("La cola de {name} está vacía", { name: OUT.name }));
  const box = modal(`<h2 style="margin-top:0">${esc(t("Cola de {name}", { name: OUT.name }))}</h2>${trackTable(d.tracks)}`);
  box.querySelectorAll("tr[data-i]")[d.pos]?.classList.add("playing");
}
$("#pOut").onclick = async () => {
  let devs = [];
  try { devs = await api("/api/devices"); } catch (e) { }
  const row = (id, ic, name, sub, sel) => `<div class="item out-opt${sel ? " sel" : ""}" data-out="${esc(id)}"><div style="font-size:24px">${ic}</div><div class="grow"><div class="t">${esc(name)}</div><div class="s">${esc(sub)}</div></div>${sel ? '<span class="ok" style="font-size:20px">✔</span>' : ""}</div>`;
  const b = modal(`<h2 style="margin-top:0">${t("Reproducir en…")}</h2>
    <div class="list">${row("", "💻", t("Este navegador"), t("Suena en este ordenador o móvil"), !OUT)}
    ${devs.map((d) => row(d.id, "🔊", devName(d), d.playing ? t("Sonando ahora") : t("Visto {when}", { when: ago(d.last_seen) }), OUT && OUT.id === d.id)).join("")}</div>
    ${devs.length ? "" : `<p class="muted">${t("Aún no conozco ningún Echo. Habla una vez con la skill desde cada uno (“Alexa, abre mi colección”) y aparecerá aquí.")}</p>`}
    <p class="hint">${t('Con un Echo elegido, al pulsar una canción, un álbum o una lista se prepara en ese Echo y basta con decirle <b>“Alexa, abre mi colección”</b>: Amazon no deja que una skill empiece a sonar sin que se lo pidas. Ponles nombre a tus Echo en <a href="#/alexa" onclick="closeModal()">🔊 Alexa</a>.')}</p>`);
  b.querySelectorAll("[data-out]").forEach((el) => el.onclick = async () => {
    const id = el.dataset.out;
    if (!id) { setOut(null); closeModal(); return toast(t("Suena en este navegador")); }
    const d = devs.find((x) => x.id === id);
    const carry = P.queue.length && !audio.paused;
    const queue = P.queue, idx = P.idx;
    setOut({ id, name: devName(d) });
    closeModal();
    if (carry) playOnEcho(queue, idx, false);   // lo que sonaba en el navegador pasa al Echo
    else toast(t("Ahora se reproduce en {name}", { name: OUT.name }));
  });
};
setOut(OUT);
function updateBtns() { $("#pShuffle").classList.toggle("on", P.shuffle); $("#pLoop").classList.toggle("on", P.loop); }
if ("mediaSession" in navigator) { navigator.mediaSession.setActionHandler("nexttrack", () => step(1)); navigator.mediaSession.setActionHandler("previoustrack", () => step(-1)); }
function showQueue() {
  if (!P.queue.length) return toast(t("La cola está vacía"));
  const rows = P.order.map((i) => { const tr = P.queue[i]; return `<div class="item" data-i="${i}"><img src="${art(tr.id)}" loading="lazy" alt=""><div class="grow"><div class="t" style="${i === P.idx ? "color:var(--accent)" : ""}">${esc(tr.title)}</div><div class="s">${esc(tr.artist)}</div></div></div>`; }).join("");
  const b = modal(`<h2 style="margin-top:0">${t("Cola ({n})", { n: P.queue.length })}</h2><div class="list">${rows}</div>`);
  b.querySelectorAll(".item").forEach((el) => el.onclick = () => { playIdx(+el.dataset.i); closeModal(); });
}

// ============================================================ acciones
async function sendToAlexa(ids, desc, shuffle = false, first = null) {
  const devs = await api("/api/devices");
  if (!devs.length) {
    modal(`<h2 style="margin-top:0">${t("Enviar a Alexa")}</h2><p>${t("Aún no conozco ningún Echo. Habla una vez con la skill desde cada dispositivo (por ejemplo <b>“Alexa, abre mi colección”</b>) y aparecerá aquí.")}</p><p class="muted">${t('Si todavía no has creado la skill, ve a <a href="#/setup" onclick="closeModal()">Configurar Alexa</a>.')}</p>`);
    return;
  }
  const b = modal(`<h2 style="margin-top:0">${t("Enviar a Alexa")}</h2><p class="muted">${t("{n} canciones", { n: ids.length })} · ${esc(desc)}</p>
    <div class="list">${devs.map((d) => `<div class="item" data-id="${esc(d.id)}"><div style="font-size:26px">🔊</div><div class="grow"><div class="t">${esc(devName(d))}</div><div class="s">${t("Visto {when}", { when: ago(d.last_seen) })}</div></div></div>`).join("")}</div>
    <label class="check"><input type="checkbox" id="sShuf" ${shuffle ? "checked" : ""}> ${t("Aleatorio")}</label>`);
  b.querySelectorAll(".item").forEach((el) => el.onclick = async () => {
    await api(`/api/devices/${enc(el.dataset.id)}/queue`, { method: "POST", body: { track_ids: ids, desc, shuffle: $("#sShuf").checked, first } });
    modal(`<h2 style="margin-top:0">${t("¡Listo!")}</h2><p>${t("La cola está preparada en ese Echo. Ahora dile:")}</p><p style="font-size:20px"><b>“Alexa, abre mi colección”</b></p><p class="muted">${t("o “Alexa, pide a mi colección que continúe”. Las skills de Alexa no pueden empezar a sonar solas: hace falta esa frase.")}</p>`);
  });
}

async function addToPlaylist(ids) {
  const pls = (await api("/api/playlists")).filter((p) => p.kind === "user");
  const b = modal(`<h2 style="margin-top:0">${t("Añadir a lista")}</h2><div class="list">${pls.map((p) => `<div class="item" data-id="${p.id}">📜 <div class="grow">${esc(p.name)} <span class="muted">(${p.tracks})</span></div></div>`).join("") || `<p class="muted">${t("No tienes listas propias todavía.")}</p>`}</div>
  <label class="f">${t("Nueva lista")}</label><div class="row"><input type="text" id="newPl" placeholder="${esc(t("Nombre"))}"><button class="btn primary" id="newPlBtn">${t("Crear")}</button></div>`);
  b.querySelectorAll(".item").forEach((el) => el.onclick = async () => { await api(`/api/playlists/${el.dataset.id}/add`, { method: "POST", body: { track_ids: ids } }); closeModal(); toast(t("Añadidas a la lista")); });
  $("#newPlBtn").onclick = async () => { const n = $("#newPl").value.trim(); if (!n) return; await api("/api/playlists", { method: "POST", body: { name: n, track_ids: ids } }); closeModal(); toast(t("Lista “{name}” creada", { name: n })); };
}

function actionBar(getTracks, desc, opts = {}) {
  const id = "ab" + Math.random().toString(36).slice(2, 7);
  setTimeout(() => {
    const el = document.getElementById(id); if (!el) return;
    el.querySelector("[data-a=play]").onclick = async () => playList(await getTracks());
    el.querySelector("[data-a=shuffle]").onclick = async () => playList(await getTracks(), 0, true);
    el.querySelector("[data-a=queue]").onclick = async () => enqueue(await getTracks());
    el.querySelector("[data-a=alexa]").onclick = async () => sendToAlexa((await getTracks()).map((x) => x.id), desc, !!opts.shuffle);
    el.querySelector("[data-a=list]").onclick = async () => addToPlaylist((await getTracks()).map((x) => x.id));
  });
  return `<div class="actions" id="${id}"><button class="btn primary" data-a="play">${t("▶ Reproducir")}</button><button class="btn" data-a="shuffle">${t("🔀 Aleatorio")}</button><button class="btn" data-a="alexa">${t("🔊 Enviar a Alexa")}</button><button class="btn" data-a="queue">${t("＋ Cola")}</button><button class="btn" data-a="list">${t("📜 A una lista")}</button>${opts.extra || ""}</div>`;
}

function trackTable(tracks, opts = {}) {
  if (!tracks.length) return `<div class="empty">${t("No hay canciones.")}</div>`;
  const id = "tt" + Math.random().toString(36).slice(2, 7);
  const cur = P.queue[P.idx]?.id;
  const rows = tracks.map((x, i) => `<tr data-i="${i}" data-tid="${x.id}" class="${x.id === cur ? "playing" : ""}">
    <td class="n">${opts.numbers === "track" ? (x.track_no || "") : i + 1}</td>
    <td><div style="font-weight:500">${esc(x.title)}</div>${opts.noArtist ? "" : `<div class="muted" style="font-size:13px">${esc(x.artist)}</div>`}</td>
    ${opts.noAlbum ? "" : `<td class="hide-m muted">${esc(x.album)}</td>`}
    <td class="d hide-m">${fmt(x.duration)}</td>
    <td class="a"><button class="icon-btn fav ${favs.has(x.id) ? "on" : ""}" data-fav title="${esc(t("Favorita"))}">★</button><button class="icon-btn" data-more title="${esc(t("Más"))}">⋯</button></td></tr>`).join("");
  setTimeout(() => {
    const el = document.getElementById(id); if (!el) return;
    el.onclick = async (e) => {
      const row = e.target.closest("tr[data-i]"); if (!row) return;
      const x = tracks[+row.dataset.i];
      if (e.target.closest("[data-fav]")) {
        const on = !favs.has(x.id); await api(`/api/favorites/${x.id}`, { method: "POST", body: { on } });
        on ? favs.add(x.id) : favs.delete(x.id); e.target.classList.toggle("on", on); return;
      }
      if (e.target.closest("[data-more]")) return trackMenu(x, tracks, +row.dataset.i, opts);
      playList(tracks, +row.dataset.i);
    };
  });
  return `<table class="tracks" id="${id}"><thead><tr><th class="n">#</th><th>${t("Título")}</th>${opts.noAlbum ? "" : `<th class="hide-m">${t("Álbum")}</th>`}<th class="d hide-m">⏱</th><th></th></tr></thead><tbody>${rows}</tbody></table>`;
}

function trackMenu(x, list, i, opts) {
  const b = modal(`<div class="row"><img src="${art(x.id)}" style="width:64px;height:64px;border-radius:8px;object-fit:cover"><div><b>${esc(x.title)}</b><div class="muted">${esc(x.artist)} — ${esc(x.album)}</div></div></div>
  <div class="list" style="margin-top:14px">
    <div class="item" data-m="play">${t("▶ Reproducir desde aquí")}</div>
    <div class="item" data-m="next">${t("⏭ Reproducir a continuación")}</div>
    <div class="item" data-m="queue">${t("＋ Añadir a la cola")}</div>
    <div class="item" data-m="alexa">${t("🔊 Enviar a Alexa")}</div>
    <div class="item" data-m="list">${t("📜 Añadir a una lista")}</div>
    ${opts.playlistId ? `<div class="item" data-m="remove">${t("🗑 Quitar de esta lista")}</div>` : ""}
    ${x.n_artist ? `<div class="item" data-m="artist">${t("🎤 Ir al artista")}</div>` : ""}
    <div class="item" data-m="album">${t("💿 Ir al álbum")}</div>
  </div><p class="muted" style="font-size:12px;word-break:break-all">${esc(x.path)}<br>${esc((x.ext || "").slice(1).toUpperCase())} ${x.bitrate ? x.bitrate + " kbps" : ""} ${x.year || ""}</p>`);
  b.onclick = async (e) => {
    const m = e.target.closest("[data-m]")?.dataset.m; if (!m) return;
    closeModal();
    if (m === "play") playList(list, i);
    if (m === "next") { if (!P.queue.length) return playList([x]); P.queue.push(x); const k = P.order.indexOf(P.idx); P.order.splice(k + 1, 0, P.queue.length - 1); toast(t("Sonará a continuación")); }
    if (m === "queue") enqueue([x]);
    if (m === "alexa") sendToAlexa([x.id], x.title);
    if (m === "list") addToPlaylist([x.id]);
    if (m === "artist") location.hash = `#/artist?n=${enc(x.n_artist)}`;
    if (m === "album") location.hash = `#/album?key=${enc(x.album_key)}`;
    if (m === "remove") { const ids = list.filter((_, k) => k !== i).map((y) => y.id); await api(`/api/playlists/${opts.playlistId}`, { method: "PUT", body: { track_ids: ids } }); route(); }
  };
}

const albumCard = (a) => `<div class="card" onclick="location.hash='#/album?key=${enc(a.key)}'"><img loading="lazy" src="${art(a.sample)}" alt=""><div class="t">${esc(a.name)}</div><div class="s">${esc(a.artist || "")}${a.year ? " · " + a.year : ""}</div></div>`;

function letterIndex(items, key) {
  const L = [...new Set(items.map((x) => (x[key] || "#")[0].toUpperCase().replace(/[^A-Z]/, "#")))];
  return `<div class="letters">${L.map((l) => `<a href="javascript:void 0" onclick="document.getElementById('L_${l === "#" ? "num" : l}')?.scrollIntoView({behavior:'smooth'})">${l}</a>`).join("")}</div>`;
}

// ============================================================ vistas
const views = {
  async home() {
    const [s, r] = await Promise.all([api("/api/status"), api("/api/recent")]);
    const c = s.counts;
    let warn = "";
    if (!c.tracks) warn += `<div class="panel">👋 ${t('<b>Bienvenido.</b> Primero añade tus carpetas de música en <a href="#/settings">Ajustes</a> y pulsa “Escanear”.')}</div>`;
    if (!s.public_url) warn += `<div class="panel">🔊 ${t('Para escuchar en Alexa sigue la guía <a href="#/setup">Configurar Alexa</a>.')}</div>`;
    if (!s.ffmpeg) warn += `<div class="panel err">⚠ ${t("No encuentro <b>ffmpeg</b>: los FLAC, WMA, OGG… no sonarán en Alexa. Instálalo con <code>sudo apt install ffmpeg</code>.")}</div>`;
    main.innerHTML = `<h1>${t("Tu música")}</h1><p class="muted">${t("Último escaneo: {when}", { when: ago(s.last_scan) })}</p>${warn}
    <div class="stats"><a class="stat link" href="#/tracks"><b>${c.tracks}</b>${t("canciones")} <span class="go">›</span></a><a class="stat link" href="#/albums"><b>${c.albums}</b>${t("álbumes")} <span class="go">›</span></a><a class="stat link" href="#/artists"><b>${c.artists}</b>${t("artistas")} <span class="go">›</span></a><a class="stat link" href="#/genres"><b>${c.genres}</b>${t("géneros")} <span class="go">›</span></a><div class="stat"><b>${Math.round(c.seconds / 3600)}</b>${t("horas")}</div></div>
    <div class="actions" style="margin-top:16px"><button class="btn primary" id="shufAll">${t("🔀 Mezclar toda mi música")}</button></div>
    ${r.albums.length ? `<h2>${t("Añadido recientemente")}</h2><div class="grid">${r.albums.slice(0, 18).map(albumCard).join("")}</div>` : ""}
    ${r.most.length ? `<h2>${t("Lo más escuchado")}</h2>${trackTable(r.most.slice(0, 15))}` : ""}`;
    $("#shufAll").onclick = async () => { const { tracks } = await api("/api/tracks?order=title&limit=500"); playList(tracks, 0, true); };
  },

  async artists() {
    const list = await api("/api/artists");
    let last = "";
    main.innerHTML = `<h1>${t("Artistas")}</h1><p class="muted">${t("{n} artistas", { n: list.length })}</p>${letterIndex(list, "n")}<div class="list">${list.map((a) => {
      const l = (a.n[0] || "#").toUpperCase().replace(/[^A-Z]/, "#"); const anchor = l !== last ? `id="L_${l === "#" ? "num" : l}"` : ""; last = l;
      return `<div class="item" ${anchor} onclick="location.hash='#/artist?n=${enc(a.n)}'"><img loading="lazy" src="${art(a.sample)}" alt=""><div class="grow"><div class="t">${esc(a.name)}</div><div class="s">${t("{a} álbumes · {n} canciones", { a: a.albums, n: a.tracks })}</div></div></div>`;
    }).join("")}</div>`;
  },

  async artist(q) {
    const d = await api(`/api/artist?n=${enc(q.n)}`);
    const name = d.tracks[0] ? (d.tracks.find((x) => x.n_artist === q.n)?.artist || d.tracks[0].album_artist) : q.n;
    main.innerHTML = `<div class="head"><img src="${art(d.tracks[0]?.id)}" alt=""><div class="meta"><div class="muted">${t("Artista")}</div><h1>${esc(name)}</h1><div class="muted">${t("{a} álbumes · {n} canciones", { a: d.albums.length, n: d.tracks.length })}</div>${actionBar(async () => d.tracks, name)}</div></div>
    <h2>${t("Álbumes")}</h2><div class="grid">${d.albums.map(albumCard).join("")}</div><h2>${t("Canciones")}</h2>${trackTable(d.tracks, { noArtist: true })}`;
  },

  async albums(q) {
    const order = q.order || "name";
    const list = await api(`/api/albums?order=${order}`);
    main.innerHTML = `<div class="row"><h1>${t("Álbumes")}</h1><span class="spacer"></span><select id="ord" style="width:auto"><option value="name">${t("Por nombre")}</option><option value="recent">${t("Recientes")}</option><option value="year">${t("Por año")}</option></select></div><p class="muted">${t("{n} álbumes", { n: list.length })}</p><div class="grid">${list.map(albumCard).join("")}</div>`;
    $("#ord").value = order; $("#ord").onchange = (e) => location.hash = `#/albums?order=${e.target.value}`;
  },

  async album(q) {
    const tracks = await api(`/api/album?key=${enc(q.key)}`);
    if (!tracks.length) { main.innerHTML = `<div class="empty">${t("Álbum no encontrado.")}</div>`; return; }
    const t0 = tracks[0], artist = t0.album_artist || t0.artist;
    const dur = tracks.reduce((s, x) => s + (x.duration || 0), 0);
    main.innerHTML = `<div class="head"><img src="${art(t0.id)}" alt=""><div class="meta"><div class="muted">${t("Álbum")}</div><h1>${esc(t0.album)}</h1>
      <div>${t0.n_album_artist || t0.n_artist ? `<a href="#/artist?n=${enc(t0.n_album_artist || t0.n_artist)}">${esc(artist)}</a>` : ""} <span class="muted">${t0.year ? "· " + t0.year : ""} · ${t("{n} canciones", { n: tracks.length })} · ${fmt(dur)} ${t0.genre ? "· " + esc(t0.genre) : ""}</span></div>
      ${actionBar(async () => tracks, t0.album)}</div></div>${trackTable(tracks, { numbers: "track", noAlbum: true })}`;
  },

  async tracks(q) {
    const order = q.order || "title", query = q.q || "";
    let offset = 0, total = 0, all = [];
    main.innerHTML = `<div class="row"><h1>${t("Canciones")}</h1><span class="spacer"></span><input id="tq" type="text" placeholder="${esc(t("Filtrar…"))}" style="width:200px" value="${esc(query)}"><select id="ord" style="width:auto"><option value="title">${t("Título")}</option><option value="artist">${t("Artista")}</option><option value="album">${t("Álbum")}</option><option value="recent">${t("Recientes")}</option><option value="year">${t("Año")}</option></select></div><p class="muted" id="tc"></p><div id="tl"></div><div class="actions"><button class="btn hidden" id="more">${t("Cargar más")}</button></div>`;
    $("#ord").value = order;
    $("#ord").onchange = (e) => location.hash = `#/tracks?order=${e.target.value}&q=${enc($("#tq").value)}`;
    $("#tq").onchange = (e) => location.hash = `#/tracks?order=${order}&q=${enc(e.target.value)}`;
    const load = async () => {
      const d = await api(`/api/tracks?order=${order}&offset=${offset}&limit=300&q=${enc(query)}`);
      total = d.total; all = all.concat(d.tracks); offset += d.tracks.length;
      $("#tc").textContent = t("{n} canciones", { n: total }); $("#tl").innerHTML = trackTable(all);
      $("#more").classList.toggle("hidden", offset >= total);
    };
    $("#more").onclick = load; await load();
  },

  async genres() {
    const list = await api("/api/genres");
    main.innerHTML = `<h1>${t("Géneros")}</h1><div class="grid">${list.map((g) => `<div class="card" onclick="location.hash='#/genre?n=${enc(g.n)}'"><img loading="lazy" src="${art(g.sample)}" alt=""><div class="t">${esc(g.name)}</div><div class="s">${t("{n} canciones", { n: g.tracks })}</div></div>`).join("") || `<div class="empty">${t("Sin géneros (revisa las etiquetas de tus archivos).")}</div>`}</div>`;
  },

  async genre(q) {
    const d = await api(`/api/genre?n=${enc(q.n)}`);
    const name = d.tracks[0]?.genre || q.n;
    main.innerHTML = `<div class="head"><img src="${art(d.tracks[0]?.id)}" alt=""><div class="meta"><div class="muted">${t("Género")}</div><h1>${esc(name)}</h1><div class="muted">${t("{n} canciones", { n: d.tracks.length })}</div>${actionBar(async () => d.tracks, name, { shuffle: true })}</div></div><h2>${t("Álbumes")}</h2><div class="grid">${d.albums.map(albumCard).join("")}</div>`;
  },

  async folders(q) {
    const d = await api(`/api/folders${q.path ? "?path=" + enc(q.path) : ""}`);
    const up = d.path ? `<div class="item" onclick="location.hash='#/folders${d.parent ? "?path=" + enc(d.parent) : ""}'">⬆️ <div class="grow">..</div></div>` : "";
    main.innerHTML = `<h1>${t("Carpetas")}</h1><p class="muted" style="word-break:break-all">${esc(d.path || t("Carpetas de música"))}</p>
    ${d.path ? actionBar(async () => api(`/api/folder-tracks?path=${enc(d.path)}`), d.path.split(/[\\/]/).pop()) : ""}
    <div class="list" style="margin-top:12px">${up}${d.folders.map((f) => `<div class="item" onclick="location.hash='#/folders?path=${enc(f.path)}'">📁 <div class="grow t">${esc(f.name)}</div></div>`).join("")}</div>
    ${d.tracks.length ? trackTable(d.tracks, { numbers: "track" }) : ""}
    ${!d.path && !d.folders.length ? `<div class="empty">${t('No hay carpetas escaneadas. Añádelas en <a href="#/settings">Ajustes</a>.')}</div>` : ""}`;
  },

  async playlists() {
    const list = await api("/api/playlists");
    main.innerHTML = `<div class="row"><h1>${t("Listas")}</h1><span class="spacer"></span><button class="btn primary" id="newPl">${t("＋ Nueva lista")}</button></div>
    <p class="muted">${t("Las listas .m3u/.m3u8/.pls que haya en tus carpetas se importan solas. Pídelas a Alexa con “pon la lista …”.")}</p>
    <div class="grid" style="margin-top:12px">
      <div class="card" onclick="location.hash='#/favorites'"><img src="/static/cover.svg" alt=""><div class="t">⭐ ${t("Favoritas")}</div><div class="s">${t("Automática")}</div></div>
      ${list.map((p) => `<div class="card" onclick="location.hash='#/playlist?id=${p.id}'"><img loading="lazy" src="${art(p.sample)}" alt=""><div class="t">${esc(p.name)}</div><div class="s">${t("{n} canciones", { n: p.tracks })} · ${p.kind === "file" ? t("archivo") : p.kind === "itunes" ? "iTunes" : t("propia")}</div></div>`).join("")}</div>`;
    $("#newPl").onclick = async () => { const n = prompt(t("Nombre de la lista")); if (n) { const r = await api("/api/playlists", { method: "POST", body: { name: n } }); location.hash = `#/playlist?id=${r.id}`; } };
  },

  async playlist(q) {
    const d = await api(`/api/playlists/${q.id}`);
    const p = d.playlist, own = p.kind === "user";
    const extra = `<a class="btn" href="/api/playlists/${p.id}/m3u">⬇ M3U</a>${own ? `<button class="btn" id="ren">${t("✏️ Renombrar")}</button><button class="btn danger" id="del">${t("🗑 Borrar")}</button>` : ""}`;
    main.innerHTML = `<div class="head"><img src="${art(d.tracks[0]?.id)}" alt=""><div class="meta"><div class="muted">${t("Lista")} ${own ? "" : esc(t("(archivo {path})", { path: p.path }))}</div><h1>${esc(p.name)}</h1><div class="muted">${t("{n} canciones", { n: d.tracks.length })}</div>${actionBar(async () => d.tracks, p.name, { extra })}</div></div>${trackTable(d.tracks, { playlistId: own ? p.id : null })}`;
    if (own) {
      $("#ren").onclick = async () => { const n = prompt(t("Nuevo nombre"), p.name); if (n) { await api(`/api/playlists/${p.id}`, { method: "PUT", body: { name: n } }); route(); } };
      $("#del").onclick = async () => { if (confirm(t("¿Borrar la lista “{name}”?", { name: p.name }))) { await api(`/api/playlists/${p.id}`, { method: "DELETE" }); location.hash = "#/playlists"; } };
    }
  },

  async radios() {
    const list = await api("/api/radios");
    main.innerHTML = `<h1>📻 ${t("Radios")}</h1><p class="muted">${t("Emisoras y streams de Internet. Pídelas a Alexa con <b>“Alexa, pide a mi colección que ponga la radio …”</b> o <b>“…la emisora …”</b>. Las listas .m3u/.pls con direcciones de radio que haya en tus carpetas se añaden solas al escanear.")}</p>
    <div class="panel"><div class="row"><input type="text" id="rName" placeholder="${esc(t("Nombre (p. ej. Radio Clásica)"))}" style="flex:1 1 180px;min-width:0"><input type="url" id="rUrl" placeholder="${esc(t("https://… dirección del stream"))}" style="flex:2 1 220px;min-width:0"><button class="btn primary" id="rAdd">${t("＋ Añadir")}</button></div>
    <p class="hint">${t("Vale la dirección directa del audio (suele acabar en .mp3, .aac o /stream). Tras añadir radios, pulsa “🗣 Actualizar modelo de voz” en Configurar Alexa para que Alexa reconozca sus nombres.")}</p></div>
    <div class="list">${list.map((r) => `<div class="item" data-id="${r.id}"><div style="font-size:24px">📻</div><div class="grow"><div class="t">${esc(r.title)}</div><div class="s" style="word-break:break-all">${esc(r.path.slice(6))}</div></div><button class="btn small" data-play="${r.id}">${t("▶ Escuchar")}</button><button class="btn small" data-alexa="${r.id}">${t("🔊 A Alexa")}</button><button class="icon-btn" data-del="${r.id}" title="${esc(t("Borrar"))}">✕</button></div>`).join("") || `<div class="empty">${t("Todavía no hay radios.")}</div>`}</div>`;
    $("#rAdd").onclick = async () => {
      const r = await fetch("/api/radios", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: $("#rName").value, url: $("#rUrl").value }) }).then((x) => x.json());
      if (r.error) return toast(ts(r.error));
      toast(t("Radio añadida")); route();
    };
    main.querySelectorAll("[data-play]").forEach((b) => b.onclick = () => playList([list.find((r) => r.id === +b.dataset.play)]));
    main.querySelectorAll("[data-alexa]").forEach((b) => b.onclick = () => { const r = list.find((x) => x.id === +b.dataset.alexa); sendToAlexa([r.id], r.title); });
    main.querySelectorAll("[data-del]").forEach((b) => b.onclick = async () => { if (confirm(t("¿Borrar esta radio?"))) { await api(`/api/radios/${b.dataset.del}`, { method: "DELETE" }); route(); } });
  },

  async favorites() {
    const tracks = await api("/api/favorites");
    main.innerHTML = `<div class="head"><img src="/static/cover.svg" alt=""><div class="meta"><div class="muted">${t("Lista automática")}</div><h1>⭐ ${t("Favoritas")}</h1><div class="muted">${t("{n} canciones", { n: tracks.length })} · ${t("Dile a Alexa “pon mis favoritas”")}</div>${actionBar(async () => tracks, "tus favoritas", { shuffle: true })}</div></div>${trackTable(tracks)}`;
  },

  async search(q) {
    const term = q.q || ""; $("#searchBox").value = term;
    const r = await api(`/api/search?q=${enc(term)}`);
    const sec = (title, html) => html ? `<h2>${title}</h2>${html}` : "";
    main.innerHTML = `<h1>${esc(t("Resultados para “{q}”", { q: term }))}</h1><p class="muted">${t("Búsqueda aproximada, igual que la que usa Alexa.")}</p>
      ${sec(t("Artistas"), (r.artists || []).map((a) => `<div class="item" onclick="location.hash='#/artist?n=${enc(a.n)}'">🎤 <div class="grow">${esc(a.name)}</div><span class="pill">${Math.round(a.score * 100)}%</span></div>`).join(""))}
      ${sec(t("Álbumes"), (r.albums || []).map((a) => `<div class="item" onclick="location.hash='#/album?key=${enc(a.key)}'">💿 <div class="grow">${esc(a.name)}</div><span class="pill">${Math.round(a.score * 100)}%</span></div>`).join(""))}
      ${sec(t("Listas"), (r.playlists || []).map((p) => `<div class="item" onclick="location.hash='#/playlist?id=${p.id}'">📜 <div class="grow">${esc(p.name)}</div></div>`).join(""))}
      ${sec(t("Géneros"), (r.genres || []).map((g) => `<div class="item" onclick="location.hash='#/genre?n=${enc(g.n)}'">🎸 <div class="grow">${esc(g.name)}</div></div>`).join(""))}
      ${sec(t("Canciones"), (r.tracks || []).length ? trackTable(r.tracks) : "")}
      ${!Object.values(r).some((v) => v.length) ? `<div class="empty">${t("Nada encontrado.")}</div>` : ""}`;
  },

  async alexa() {
    const [devs, s] = await Promise.all([api("/api/devices"), api("/api/status")]);
    main.innerHTML = `<h1>Alexa</h1><p class="muted">${t("Tus Echo aparecen aquí cuando hablan con la skill. Puedes ponerles nombre, ver qué suena y su cola.")}</p>
    ${devs.map((d) => `<div class="panel"><div class="row"><div style="font-size:30px">🔊</div><div class="grow" style="flex:1"><b>${esc(devName(d))}</b> ${d.playing ? `<span class="pill ok">${t("sonando")}</span>` : ""} ${d.pending ? `<span class="pill">${t("cola preparada")}</span>` : ""}<div class="muted" style="font-size:13px">${t("Visto {when}", { when: ago(d.last_seen) })} · ${t("{n} en cola", { n: d.queue_len })} ${d.shuffle ? "· 🔀" : ""} ${d.loop ? "· 🔁" : ""}</div></div>
      <button class="btn small" data-ren="${esc(d.id)}">${t("✏️ Nombre")}</button><button class="btn small" data-q="${esc(d.id)}">${t("☰ Cola")}</button><button class="btn small danger" data-del="${esc(d.id)}">✕</button></div>
      ${d.current ? `<div class="item" style="margin-top:10px"><img src="${art(d.current.id)}" alt=""><div class="grow"><div class="t">${esc(d.current.title)}</div><div class="s">${esc(d.current.artist)} — ${esc(d.current.album)}</div></div></div>` : ""}</div>`).join("") || `<div class="panel">${t("Todavía ningún Echo ha usado la skill. Di <b>“Alexa, abre mi colección”</b>.")}</div>`}
    <h2>${t("Últimas peticiones de Alexa")}</h2><div class="panel">${s.recent_requests.length ? s.recent_requests.map((r) => `<div class="muted" style="font-size:13px">${new Date(r.t * 1000).toLocaleTimeString(LANG)} · ${esc(r.type)} ${esc(r.intent || "")} · …${esc(r.device)}${r.error ? ` <span class="err">· ${esc(r.error)}</span>` : ""}</div>`).join("") : `<span class="muted">${t("Ninguna desde que arrancó Local Media.")}</span>`}</div>
    <h2>${t("Qué puedes decir")}</h2><div class="panel">${sayings()}</div>`;
    main.querySelectorAll("[data-ren]").forEach((b) => b.onclick = async () => { const n = prompt(t("Nombre del dispositivo (p. ej. Echo salón)")); if (n != null) { await api(`/api/devices/${enc(b.dataset.ren)}`, { method: "PUT", body: { name: n } }); route(); } });
    main.querySelectorAll("[data-del]").forEach((b) => b.onclick = async () => { if (confirm(t("¿Olvidar este dispositivo?"))) { await api(`/api/devices/${enc(b.dataset.del)}`, { method: "DELETE" }); route(); } });
    main.querySelectorAll("[data-q]").forEach((b) => b.onclick = async () => { const d = await api(`/api/devices/${enc(b.dataset.q)}/queue`); const box = modal(`<h2 style="margin-top:0">${t("Cola del Echo")}</h2>${trackTable(d.tracks)}`); box.querySelectorAll("tr[data-i]")[d.pos]?.classList.add("playing"); });
  },

  async setup() {
    const [s, c] = await Promise.all([api("/api/status"), api("/api/config")]);
    const tunnelUrl = s.tunnel || "";
    const port = c.public_port;
    main.innerHTML = `<h1>${t("Configurar Alexa")}</h1><p class="muted">${t("Se hace una sola vez. Tendrás tu propia skill privada (gratis) que solo funciona en tus Echo.")}</p>
    <ol class="steps">
      <li>${t("<b>Haz accesible el puerto público por HTTPS.</b> Alexa solo habla con direcciones <code>https://</code> con certificado válido. Local Media escucha para Alexa en el puerto <code>{port}</code> (solo expone la skill y el audio, nunca esta web).", { port })}
        <div class="panel" style="margin-top:8px">${t("<b>Opción A — Túnel rápido de Cloudflare</b> (recomendado: gratis, sin cuenta, sin dominio, sin límite de datos y sin tocar el router). En la terminal de la Raspberry, dentro de la carpeta de Local Media:")}<pre class="code">./install.sh --cloudflare</pre>
        <span class="hint">${t("La dirección (<code>xxx.trycloudflare.com</code>) cambia cada vez que se reinicia la Pi, pero Local Media la detecta sola y, si has conectado con Amazon, actualiza la skill automáticamente.")}${tunnelUrl ? ` ${t("Ahora mismo:")} <code>${esc(tunnelUrl)}</code>` : ""}</span>
        <p class="hint">${t("⚠ Los dominios gratuitos de ngrok (<code>*.ngrok-free.dev</code>) no funcionan con Alexa: Amazon no llega a conectar.")}</p>
        <div class="info-wrap"><p style="margin:0">${t("<b>Opción B — Cloudflare Tunnel</b> con un dominio propio (dirección fija):")} <button type="button" class="info-btn" aria-expanded="false" aria-controls="infoB" aria-label="${esc(t("¿Qué cuesta la Opción B?"))}">?</button></p>
        <div class="info-pop" id="infoB" role="note">
          <p>${t("<b>El túnel de Cloudflare es gratis</b>, igual que en la Opción A. Lo único que se paga es el <b>dominio</b>: tu propia dirección de Internet (p. ej. <code>tunombre.com</code>).")}</p>
          <ul>
            <li>${t("<b>Precio:</b> desde unos pocos euros al año según la terminación; un <code>.com</code> ronda los 10 € al año.")}</li>
            <li>${t('<b>Dónde comprarlo:</b> lo más sencillo es en el propio Cloudflare (<a href="https://dash.cloudflare.com/?to=/:account/domains/register" target="_blank" rel="noopener">Cloudflare Registrar</a>, a precio de coste). Si ya tienes uno en otra tienda, también vale pasándolo a Cloudflare.')}</li>
            <li>${t("<b>Qué ganas:</b> una dirección fija y con tu nombre (p. ej. <code>musica.tunombre.com</code>) que no cambia al reiniciar la Raspberry, y un túnel pensado para uso continuo.")}</li>
            <li>${t("<b>¿Hace falta?</b> No. Con la Opción A, Local Media detecta la dirección nueva tras cada reinicio y actualiza la skill solo, sin pagar nada.")}</li>
          </ul>
        </div></div><pre class="code">cloudflared tunnel login
cloudflared tunnel create localmedia
cloudflared tunnel route dns localmedia musica.TU-DOMINIO.com
cloudflared tunnel run --url http://localhost:${port} localmedia</pre>
        <span class="hint">${t("El instalador puede instalar cloudflared:")} <code>./install.sh --tunnel</code>.</span>
        <p>${t("<b>Opción C — Router + DuckDNS + Caddy</b> (abre el 443 hacia la Pi):")} <code>reverse_proxy localhost:${port}</code></p></div></li>
      <li>${t("<b>Escribe aquí la URL pública</b> y pruébala.")}
        <div class="row" style="margin-top:8px"><input type="url" id="pubUrl" placeholder="https://palabras.trycloudflare.com" value="${esc(c.public_url)}" style="flex:1 1 180px;min-width:0"><button class="btn primary" id="savePub">${t("Guardar y probar")}</button></div><p id="pubRes" class="hint"></p></li>
      <li>${t("<b>Conecta con Amazon.</b> Local Media crea y configura la skill él solo.")}
        <div id="amz" class="panel amz" style="margin-top:8px"><span class="muted">${t("Cargando…")}</span></div></li>
    </ol>
    <details class="panel manual"><summary>${t("<b>Prefiero crear la skill a mano</b>")} <span class="muted">${t("(sin conectar con Amazon)")}</span></summary>
    <ol class="steps" style="margin-top:14px">
      <li>${t('<b>Crea la skill</b> en <a href="https://developer.amazon.com/alexa/console/ask" target="_blank" rel="noopener">developer.amazon.com/alexa/console/ask</a> (con la misma cuenta de Amazon que tus Echo): <i>Create Skill</i> → nombre “Mi Colección”, idioma <b>Spanish (ES)</b> → tipo <b>Other</b> → <b>Custom</b> → <b>Provision your own</b> → <b>Start from Scratch</b>.')}</li>
      <li>${t("<b>Pega el modelo de voz</b> en <i>Build → Interaction Model → JSON Editor</i>, <i>Save</i> y <i>Build skill</i>.")}
        <div class="actions"><a class="btn primary" href="/api/skill/model?locale=es-ES">⬇ es-ES.json</a><a class="btn" href="/api/skill/model?locale=es-MX">es-MX</a><a class="btn" href="/api/skill/model?locale=es-US">es-US</a><a class="btn" href="/api/skill/model?locale=en-US">en-US</a><a class="btn" href="/api/skill/model?locale=en-GB">en-GB</a><a class="btn" href="/api/skill/model?locale=es-ES&library=0">${t("Modelo genérico")}</a></div></li>
      <li>${t("<b>Activa el reproductor de audio:</b> <i>Build → Interfaces</i> → <b>Audio Player</b> → <i>Save Interfaces</i> → <i>Build skill</i>.")}</li>
      <li>${t("<b>Endpoint:</b> <i>Build → Endpoint</i> → <b>HTTPS</b> → Default Region:")}<div style="margin:6px 0"><code id="ep">${esc(s.alexa_endpoint || "https://TU-DOMINIO/alexa")}</code> <button class="btn small" id="copyEp">${t("Copiar")}</button></div>${t("certificado: con <b>ngrok</b> o <b>trycloudflare</b> elige <b>“My development endpoint is a sub-domain of a domain that has a wildcard certificate from a certificate authority”</b>; con tu propio dominio, <b>“…has a certificate from a trusted certificate authority”</b>.")}</li>
      <li>${t('<b>Limita Local Media a tu skill:</b> copia el <i>Skill ID</i> (amzn1.ask.skill.…) en <a href="#/settings">Ajustes</a>.')}</li>
      <li>${t("<b>Prueba:</b> pestaña <i>Test</i> → <b>Development</b>.")}</li>
    </ol></details>
    <h2>${t("Qué puedes decir")}</h2><div class="panel">${sayings()}</div>`;
    $("#copyEp").onclick = () => copy($("#ep").textContent);
    $("#savePub").onclick = async () => {
      await api("/api/config", { method: "POST", body: { public_url: $("#pubUrl").value.trim() } });
      $("#pubRes").textContent = t("Probando…");
      const r = await api("/api/test-public");
      $("#pubRes").innerHTML = `<span class="${r.ok ? "ok" : "err"}">${r.ok ? "✔" : "✖"} ${esc(ts(r.msg))}</span>`;
      const s2 = await api("/api/status"); $("#ep").textContent = s2.alexa_endpoint || "https://TU-DOMINIO/alexa";
      drawAmazon();
    };
    drawAmazon();
  },

  async settings() {
    const [c, s] = await Promise.all([api("/api/config"), api("/api/status")]);
    main.innerHTML = `<h1>${t("Ajustes")}</h1>
    <div class="panel"><h2 style="margin-top:0">📁 ${t("Carpetas de música")}</h2><div id="folders"></div>
      <div class="actions"><button class="btn" id="addFolder">${t("＋ Añadir carpeta")}</button><button class="btn primary" id="scan">${t("🔄 Escanear ahora")}</button><button class="btn" id="fullScan">${t("Reescanear todo")}</button></div>
      <p class="hint" id="scanState"></p>
      <label class="f">${t("Reescaneo automático (minutos, 0 = nunca)")}</label><input type="number" id="rescan" min="0" value="${c.rescan_minutes}"></div>

    <div class="panel"><h2 style="margin-top:0">📡 ${t("Servidores UPnP / DLNA")}</h2><p class="hint">${t("Añade la música de un NAS, Plex, MiniDLNA, Jellyfin, Serviio… de tu red.")}</p>
      <label class="check"><input type="checkbox" id="upnpOn" ${c.upnp_enabled ? "checked" : ""}> ${t("Usar servidores UPnP/DLNA")}</label>
      <div id="upnpList"></div><div class="actions"><button class="btn" id="upnpFind">${t("🔍 Buscar servidores")}</button></div></div>

    <div class="panel"><h2 style="margin-top:0">🔊 Alexa</h2>
      <label class="f">${t("URL pública (https)")}</label><input type="url" id="pub" value="${esc(c.public_url)}" placeholder="https://musica.tudominio.com">
      <label class="f">${t("Skill IDs permitidos (uno por línea)")}</label><textarea id="skills" rows="2" placeholder="amzn1.ask.skill.…">${esc((c.skill_ids || []).join("\n"))}</textarea><p class="hint">${t("Vacío = acepta cualquier skill. Recomendado rellenarlo.")}</p>
      <label class="check"><input type="checkbox" id="verify" ${c.verify_signatures ? "checked" : ""}> ${t("Comprobar la firma de Amazon en cada petición")} ${s.crypto ? "" : `<span class="pill bad">${t("falta cryptography")}</span>`}</label>
      <label class="check"><input type="checkbox" id="shufArt" ${c.shuffle_artist ? "checked" : ""}> ${t("Al pedir un artista, mezclar sus canciones")}</label>
      <label class="f">${t("Máximo de canciones por cola")}</label><input type="number" id="maxq" min="50" max="5000" value="${c.max_queue}"></div>

    <div class="panel"><h2 style="margin-top:0">🎚 ${t("Conversión de audio")}</h2><p class="hint">${t("Los Echo solo reproducen MP3 y AAC/M4A. El resto (FLAC, WMA, OGG, OPUS, WAV, ALAC…) se convierte al vuelo con ffmpeg")} ${s.ffmpeg ? '<span class="pill ok">ffmpeg OK</span>' : `<span class="pill bad">${t("ffmpeg no encontrado")}</span>`}</p>
      <label class="f">${t("Modo")}</label><select id="trans"><option value="auto">${t("Automático (solo lo necesario)")}</option><option value="always">${t("Siempre a MP3")}</option><option value="never">${t("Nunca")}</option></select>
      <label class="f">${t("Calidad MP3 (kbps)")}</label><select id="br"><option>128</option><option>192</option><option>256</option><option>320</option></select>
      <label class="f">${t("Ruta de ffmpeg")}</label><input type="text" id="ffmpeg" value="${esc(c.ffmpeg)}"></div>

    <div class="panel"><h2 style="margin-top:0">🔒 ${t("Web y red")}</h2>
      <label class="f">${t("Contraseña de esta web (vacía = sin contraseña)")}</label><input type="password" id="pw" value="${esc(c.web_password)}" autocomplete="new-password">
      <div class="row"><div style="flex:1"><label class="f">${t("Puerto web (LAN)")}</label><input type="number" id="lanp" value="${c.lan_port}"></div><div style="flex:1"><label class="f">${t("Puerto público (Alexa)")}</label><input type="number" id="pubp" value="${c.public_port}"></div></div>
      <p class="hint">${t("Los cambios de puerto se aplican al reiniciar:")} <code>sudo systemctl restart localmedia</code></p></div>

    <div class="panel"><h2 style="margin-top:0">🚫 ${t("Pistas ignoradas")}</h2><p class="hint">${t("Las que pediste a Alexa no volver a oír (“no ponga esta de nuevo”, “olvide esta pista”). No entran en las colas de voz, salvo si las pides por su nombre.")}</p><div id="ignoredList" class="list"><span class="muted">${t("Cargando…")}</span></div></div>

    <div class="actions"><button class="btn primary" id="save">${t("💾 Guardar ajustes")}</button></div>
    <p class="muted" style="margin-top:20px;font-size:13px">Local Media for Alexa ${esc(s.version)} · ${t("etiquetas:")} ${s.mutagen ? "mutagen OK" : `<span class='err'>${t("falta mutagen")}</span>`}</p>`;
    let folders = c.music_folders.slice(), servers = (c.upnp_servers || []).slice();
    const drawFolders = () => $("#folders").innerHTML = folders.map((f, i) => `<div class="item"><span>📁</span><div class="grow t">${esc(f)}</div><button class="icon-btn" data-rm="${i}">✕</button></div>`).join("") || `<p class="muted">${t("Ninguna carpeta todavía.")}</p>`;
    const drawServers = () => $("#upnpList").innerHTML = servers.map((sv, i) => `<label class="check"><input type="checkbox" data-sv="${i}" ${sv.enabled !== false ? "checked" : ""}> ${esc(sv.name)} <span class="muted" style="font-size:12px">${esc(sv.location)}</span> <button class="icon-btn" data-svrm="${i}">✕</button></label>`).join("");
    drawFolders(); drawServers();
    $("#folders").onclick = (e) => { const b = e.target.closest("[data-rm]"); if (b) { folders.splice(+b.dataset.rm, 1); drawFolders(); } };
    $("#upnpList").onclick = (e) => { const b = e.target.closest("[data-svrm]"); if (b) { e.preventDefault(); servers.splice(+b.dataset.svrm, 1); drawServers(); } const cb = e.target.closest("[data-sv]"); if (cb) servers[+cb.dataset.sv].enabled = cb.checked; };
    $("#trans").value = c.transcode; $("#br").value = String(c.transcode_bitrate);
    $("#addFolder").onclick = () => pickFolder((p) => { if (!folders.includes(p)) folders.push(p); drawFolders(); });
    $("#upnpFind").onclick = async () => {
      $("#upnpFind").textContent = t("Buscando…");
      try { const found = await api("/api/upnp/discover"); for (const f of found) if (!servers.some((x) => x.location === f.location)) servers.push({ location: f.location, name: f.name, enabled: true }); drawServers(); toast(found.length ? t("{n} servidores encontrados", { n: found.length }) : t("No se encontró ninguno")); } catch (e) { toast(t("Error buscando servidores")); }
      $("#upnpFind").textContent = t("🔍 Buscar servidores");
    };
    const save = async () => {
      await api("/api/config", { method: "POST", body: {
        music_folders: folders, rescan_minutes: +$("#rescan").value, upnp_enabled: $("#upnpOn").checked, upnp_servers: servers,
        public_url: $("#pub").value.trim(), skill_ids: $("#skills").value.split(/\s+/), verify_signatures: $("#verify").checked,
        shuffle_artist: $("#shufArt").checked, max_queue: +$("#maxq").value, transcode: $("#trans").value, transcode_bitrate: +$("#br").value,
        ffmpeg: $("#ffmpeg").value.trim() || "ffmpeg", web_password: $("#pw").value, lan_port: +$("#lanp").value, public_port: +$("#pubp").value } });
      toast(t("Ajustes guardados"));
    };
    $("#save").onclick = save;
    $("#scan").onclick = async () => { await save(); await api("/api/scan", { method: "POST", body: {} }); pollScan(); };
    $("#fullScan").onclick = async () => { await save(); await api("/api/scan", { method: "POST", body: { full: true } }); pollScan(); };
    const drawIgnored = async () => {
      const ign = await api("/api/ignored");
      $("#ignoredList").innerHTML = ign.map((x) => `<div class="item"><img src="${art(x.id)}" loading="lazy" alt=""><div class="grow"><div class="t">${esc(x.title)}</div><div class="s">${esc(x.artist)} — ${esc(x.album)}</div></div><button class="btn small" data-unign="${x.id}">${t("↩ Recuperar")}</button></div>`).join("") || `<span class="muted">${t("Ninguna.")}</span>`;
      $("#ignoredList").querySelectorAll("[data-unign]").forEach((b) => b.onclick = async () => { await api(`/api/ignored/${b.dataset.unign}`, { method: "DELETE" }); toast(t("Recuperada")); drawIgnored(); });
    };
    drawIgnored();
    pollScan();
  },
};

// ============================================================ Conectar con Amazon
const LOCALES = [["es-ES", "Español (España)"], ["es-MX", "Español (México)"], ["es-US", "Español (EE. UU.)"], ["en-US", "Inglés (EE. UU.)"], ["en-GB", "Inglés (Reino Unido)"]];
function copy(text) { navigator.clipboard?.writeText(text).then(() => toast(t("Copiado"))); }
const copyRow = (v) => `<div class="copyrow"><code>${esc(v)}</code><button class="btn small" data-copy="${esc(v)}">${t("Copiar")}</button></div>`;
let amzTimer = null, amzWaitingLogin = false;

async function drawAmazon() {
  clearTimeout(amzTimer);
  const box = document.getElementById("amz"); if (!box) return;
  let a; try { a = await api("/api/amazon"); } catch (e) { return; }
  const j = a.job || {};
  const steps = j.steps || [];
  const locBoxes = `<div class="locales">${LOCALES.map(([k, n]) => `<label class="check"><input type="checkbox" data-loc="${k}" ${a.locales.includes(k) ? "checked" : ""}> ${t(n)}</label>`).join("")}</div>`;
  const progress = steps.length || j.error ? `<div class="amz-log">${steps.map((x, i) => { const now = i === steps.length - 1 && j.running; return `<div class="${now ? "now" : "done"}">${now ? '<span class="spin"></span>' : "✔"} ${esc(ts(x.text))}</div>`; }).join("")}${j.error ? `<div class="err">✖ ${esc(ts(j.error))}</div>` : ""}</div>` : "";
  let html;
  if (!a.public_ok) {
    html = `<p class="muted">${t("Primero completa el paso 2: hace falta la URL pública <code>https://…</code>.")}</p>`;
  } else if (!a.configured) {
    html = `<p>${t("Amazon pide que crees una vez un <b>perfil de seguridad</b>: es el permiso para que Local Media cree la skill en tu cuenta. Son 2 minutos:")}</p>
    <ol class="sub">
      <li>${t('Abre <a href="https://developer.amazon.com/loginwithamazon/console/site/lwa/overview.html" target="_blank" rel="noopener">Login with Amazon</a> con la misma cuenta de Amazon que tus Echo y pulsa <b>Create a New Security Profile</b>.')}</li>
      <li>${t("Rellena <b>Name</b>: <code>Local Media for Alexa</code>, <b>Description</b>: <code>Mi música en Alexa</code>, y en <b>Consent Privacy Notice URL</b> pega:")}${copyRow(a.privacy_url)}${t("Pulsa <b>Save</b>.")}</li>
      <li>${t("En el perfil nuevo abre <b>Web Settings</b> → <b>Edit</b>, y en <b>Allowed Return URLs</b> pega:")}${copyRow(a.redirect_uri)}${t("Pulsa <b>Save</b>.")}</li>
      <li>${t("En esa misma pantalla están el <b>Client ID</b> y el <b>Client Secret</b> (pulsa <i>Show Secret</i>). Pégalos aquí:")}</li>
    </ol>
    <label class="f">Client ID</label><input type="text" id="lwaId" placeholder="amzn1.application-oa2-client.…" value="${esc(a.client_id || "")}">
    <label class="f">Client Secret</label><input type="password" id="lwaSecret" placeholder="amzn1.oa2-cs.v1.…" autocomplete="off">
    <div class="actions"><button class="btn primary" id="lwaSave">${t("Guardar")}</button></div>`;
  } else if (!a.connected) {
    html = `<p>${t("Elige los idiomas de tus Echo y pulsa el botón. Se abrirá Amazon para que inicies sesión y des permiso.")}</p>${locBoxes}
    <div class="actions"><button class="btn amazon" id="amzConnect">${t("CONECTAR CON AMAZON")}</button></div>
    ${amzWaitingLogin ? `<p class="hint"><span class="spin"></span> ${t("Esperando a que inicies sesión en la pestaña de Amazon…")}</p>` : ""}${progress}
    <p class="hint">${t("¿Te equivocaste con el Client ID o el Secret?")} <a href="javascript:void 0" id="lwaReset">${t("Cambiarlos")}</a></p>`;
  } else {
    const done = !j.running && a.skill_id && !j.error && steps.length;
    html = `<div class="row"><span class="pill ok">${t("✔ Conectado")}</span><span class="muted">${esc(a.vendor_name || t("tu cuenta de Amazon"))}</span></div>
    ${a.skill_id ? `<p class="hint">${t("Tu skill:")} <code>${esc(a.skill_id)}</code> · <a href="https://developer.amazon.com/alexa/console/ask" target="_blank" rel="noopener">${t("verla en Amazon")}</a></p>` : ""}
    ${progress}
    ${done ? `<p class="ok" style="font-size:17px">${t("Ya puedes decir: <b>“Alexa, abre mi colección”</b>")}</p>` : ""}
    <label class="f">${t("Idiomas de la skill")}</label>${locBoxes}
    <label class="check"><input type="checkbox" id="amzAuto" ${a.auto_model ? "checked" : ""}> ${t("Actualizar el modelo de voz tras cada escaneo si cambia la biblioteca")}</label>
    <div class="actions"><button class="btn primary" id="amzSetup" ${j.running ? "disabled" : ""}>${a.skill_id ? t("🔄 Volver a configurar la skill") : t("Crear mi skill")}</button>
    <button class="btn" id="amzModel" ${j.running || !a.skill_id ? "disabled" : ""}>${t("🗣 Actualizar modelo de voz")}</button>
    <button class="btn danger" id="amzOff" ${j.running ? "disabled" : ""}>${t("Desconectar")}</button></div>`;
  }
  box.innerHTML = html;
  box.querySelectorAll("[data-copy]").forEach((b) => b.onclick = () => copy(b.dataset.copy));
  const saveLocales = () => api("/api/amazon/settings", { method: "POST", body: { locales: [...box.querySelectorAll("[data-loc]:checked")].map((x) => x.dataset.loc) } });
  box.querySelectorAll("[data-loc]").forEach((x) => x.onchange = saveLocales);
  const on = (id, fn) => { const el = document.getElementById(id); if (el) el.onclick = fn; };
  on("lwaSave", async () => {
    const id = $("#lwaId").value.trim(), sec = $("#lwaSecret").value.trim();
    if (!id.startsWith("amzn1.application-oa2-client.")) return toast(t("El Client ID empieza por amzn1.application-oa2-client."));
    if (!sec) return toast(t("Falta el Client Secret"));
    await api("/api/amazon/settings", { method: "POST", body: { client_id: id, client_secret: sec } }); drawAmazon();
  });
  on("lwaReset", async () => { await api("/api/amazon/settings", { method: "POST", body: { client_id: "" } }); drawAmazon(); });
  on("amzConnect", async () => {
    const w = window.open("about:blank", "_blank");
    const r = await fetch("/api/amazon/login").then((x) => x.json()).catch(() => ({ error: t("No se pudo contactar con Local Media") }));
    if (r.url) { if (w) w.location = r.url; else location.href = r.url; amzWaitingLogin = true; drawAmazon(); }
    else { if (w) w.close(); toast(ts(r.error) || t("No se pudo abrir Amazon")); }
  });
  on("amzSetup", async () => { await saveLocales(); await api("/api/amazon/setup", { method: "POST", body: {} }); drawAmazon(); });
  on("amzModel", async () => { await api("/api/amazon/update-model", { method: "POST", body: {} }); drawAmazon(); });
  on("amzOff", async () => { if (confirm(t("¿Desconectar de Amazon? Tu skill seguirá funcionando; solo dejará de actualizarse sola."))) { await api("/api/amazon/disconnect", { method: "POST", body: {} }); drawAmazon(); } });
  const au = document.getElementById("amzAuto"); if (au) au.onchange = () => api("/api/amazon/settings", { method: "POST", body: { auto_model: au.checked } });
  if (a.connected) amzWaitingLogin = false;
  if (j.running || amzWaitingLogin) amzTimer = setTimeout(drawAmazon, 2000);
}

// Frases de voz: van en el idioma de la skill (español o ingles), que es lo que entiende
// Alexa; solo se traducen los titulos de cada apartado.
function sayings() {
  const A = "Alexa, abre mi colección";
  const groups = [
    ["Empezar", ["Alexa, abre mi colección", "Alexa, pide a mi colección que ponga Queen", `${A} y pon toda mi música`]],
    ["Pistas y canciones", [`${A} reproduzca la pista control de sueño`, `${A} ponga la canción Bohemian Rhapsody de Queen`, `${A} reproduzca el audio relajación`, `${A} ponga la pista dormir bien del álbum Dormir bien`, "Alexa, pídele a mi colección que reproduzca la pista …"]],
    ["Álbumes, artistas y carpetas", [`${A} reproduzca el álbum Thriller`, `${A} ponga música de Estopa`, `${A} ponga la carpeta Vinilos`]],
    ["Playlists", [`${A} reproduzca mi playlist Viaje`, `${A} ponga la playlist Fiesta de iTunes`, `${A} añada esta a mi playlist Favoritas`]],
    ["Géneros y épocas", [`${A} ponga música rock`, `${A} ponga algo de jazz`, `${A} ponga música de los ochenta`, `${A} ponga música del 1995`]],
    ["Aleatorio", [`${A} reproduzca aleatoriamente el álbum Thriller`, `${A} ponga aleatoriamente música de Queen`, `${A} ponga aleatoriamente la playlist Viaje`, `${A} active el modo aleatorio`, `${A} desactive shuffle`]],
    ["Repetición", [`${A} active la repetición`, `${A} encienda el modo loop`, `${A} desactive la repetición`]],
    ["Lo que está sonando", [`${A} qué se está reproduciendo`, `${A} quién está cantando`, `${A} reproduzca esta canción`, `${A} ponga este álbum`, `${A} ponga este artista`]],
    ["No volver a oír una pista", [`${A} no ponga esta de nuevo`, `${A} olvide esta pista`, `${A} ignore esta canción`]],
    ["Radios por Internet", [`${A} ponga la radio Radio Clásica`, `${A} reproduzca la emisora de radio internet Los 40`, `${A} ponga mi stream Jazz`]],
    ["Audiolibros", [`${A} lea El principito`, `${A} continúe el libro El principito`]],
    ["Favoritas, novedades, más escuchado", [`${A} ponga mis favoritas`, `${A} ponga lo último que he añadido`, `${A} ponga lo más escuchado`]],
    ["Mientras suena", ["Alexa, siguiente / anterior / pausa / continúa", "Alexa, aleatorio / quita el aleatorio", "Alexa, repite / desactiva la repetición", "Alexa, vuelve a empezar"]],
    ["Servidor", [`${A} cuál es mi servidor actual`]],
  ];
  const note = LANG === "es" ? "" : `<p class="hint">${t("Las frases van en español porque es el idioma de tu skill de Alexa.")}</p>`;
  return note + groups.map(([g, xs]) => `<p style="margin:12px 0 4px"><b>${esc(t(g))}</b></p>` + xs.map((x) => `<div>🗣 ${esc(x)}</div>`).join("")).join("") +
    `<p class="hint" style="margin-top:12px">${t("También vale con “Alexa, pide a mi colección que…” y “Alexa, abre mi colección y…”.")}</p>`;
}

async function pickFolder(cb, path) {
  const d = await api(`/api/browse-dirs${path ? "?path=" + enc(path) : ""}`);
  const b = modal(`<h2 style="margin-top:0">${t("Elegir carpeta")}</h2><div class="row">${(d.shortcuts || []).map((s) => `<button class="btn small" data-go="${esc(s)}">${esc(s)}</button>`).join("")}</div>
    <p><code>${esc(d.path)}</code></p>${d.error ? `<p class="err">${esc(d.error)}</p>` : ""}
    <div class="dirlist"><div data-go="${esc(d.parent)}">⬆️ ..</div>${d.dirs.map((x) => `<div data-go="${esc(d.path.replace(/[\\/]$/, "") + (d.path.includes("\\") ? "\\" : "/") + x)}">📁 ${esc(x)}</div>`).join("")}</div>
    <div class="row"><input type="text" id="manualPath" value="${esc(d.path)}" style="flex:1"><button class="btn primary" id="choose">${t("Usar esta carpeta")}</button></div>
    <p class="hint">${t("Discos USB: /media/… · Carpetas de red montadas: /mnt/…")}</p>`);
  b.querySelectorAll("[data-go]").forEach((el) => el.onclick = () => pickFolder(cb, el.dataset.go));
  $("#choose").onclick = () => { cb($("#manualPath").value.trim()); closeModal(); };
}

let scanTimer = null;
async function pollScan() {
  clearTimeout(scanTimer);
  try {
    const s = await api("/api/status"); const sc = s.scan;
    const badge = $("#scanBadge");
    if (sc.running) {
      const txt = `🔄 ${ts(sc.phase)} ${sc.total ? `${sc.done}/${sc.total}` : ""}`;
      badge.textContent = txt; badge.classList.remove("hidden");
      if ($("#scanState")) $("#scanState").textContent = txt;
      scanTimer = setTimeout(pollScan, 1500);
    } else {
      badge.classList.add("hidden");
      if ($("#scanState")) $("#scanState").innerHTML = sc.finished ? `${esc(t("Último escaneo: {when} · +{a} nuevas · {u} actualizadas · −{r} borradas", { when: ago(sc.finished), a: sc.added, u: sc.updated, r: sc.removed }))} ${sc.error ? `<span class="err">${esc(sc.error)}</span>` : ""}` : "";
      if (pollScan.wasRunning) { toast(t("Escaneo terminado")); pollScan.wasRunning = false; }
    }
    if (sc.running) pollScan.wasRunning = true;
  } catch (e) { }
}

// ============================================================ tema (auto / oscuro / claro)
const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");
function getTheme() { try { return localStorage.getItem("lm-theme") || "auto"; } catch (e) { return "auto"; } }
function applyTheme(th) {
  if (th === "dark" || th === "light") document.documentElement.dataset.theme = th;
  else delete document.documentElement.dataset.theme;
  try { th === "auto" ? localStorage.removeItem("lm-theme") : localStorage.setItem("lm-theme", th); } catch (e) { }
  const effective = th === "auto" ? (darkQuery.matches ? "dark" : "light") : th;
  document.querySelectorAll("[data-theme-set]").forEach((b) => b.classList.toggle("on", b.dataset.themeSet === th));
  $("#themeBtn").textContent = effective === "dark" ? "🌙" : "☀️";
  $('meta[name="theme-color"]').content = effective === "dark" ? "#161922" : "#ffffff";
}
document.querySelectorAll("[data-theme-set]").forEach((b) => b.onclick = () => applyTheme(b.dataset.themeSet));
// en el movil el boton alterna entre oscuro y claro
$("#themeBtn").onclick = () => { const cur = document.documentElement.dataset.theme || (darkQuery.matches ? "dark" : "light"); applyTheme(cur === "dark" ? "light" : "dark"); };
darkQuery.addEventListener?.("change", () => { if (getTheme() === "auto") applyTheme("auto"); });
applyTheme(getTheme());

// ============================================================ idioma de la web
function setLang(code) {
  LANG = code;
  try { localStorage.setItem("lm-lang", code); } catch (e) { }
  applyI18nDom();
  $("#langSel").value = code;
  setOut(OUT);
  updateSideToggle();
  route();
}
$("#langSel").innerHTML = LANGS.map(([c, n]) => `<option value="${c}">${n}</option>`).join("");
$("#langSel").value = LANG;
$("#langSel").onchange = (e) => setLang(e.target.value);
applyI18nDom();

// ============================================================ router
// Si una vista lenta termina despues de haber navegado a otra, la tapa: se lleva la
// cuenta de navegaciones y, si la ultima ya habia terminado, se vuelve a pintar.
let navSeq = 0, navDone = 0;
async function route() {
  const seq = ++navSeq;
  const h = location.hash.slice(1) || "/";
  const [path, qs] = h.split("?");
  const name = path.replace(/^\//, "") || "home";
  const q = Object.fromEntries(new URLSearchParams(qs || ""));
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === name || (name === "artist" && a.dataset.nav === "artists") || (name === "album" && a.dataset.nav === "albums") || (name === "genre" && a.dataset.nav === "genres") || (name === "playlist" && a.dataset.nav === "playlists")));
  setDrawer(false);
  const v = views[name] || views.home;
  main.innerHTML = `<div class="empty">${t("Cargando…")}</div>`;
  try { await v(q); } catch (e) { if (e.message !== "auth" && seq === navSeq) main.innerHTML = `<div class="empty err">${t("Error:")} ${esc(e.message)}</div>`; }
  if (seq === navSeq) { navDone = seq; main.scrollTop = 0; }
  else if (navDone === navSeq) route();   // esta vista vieja ha tapado a la actual
}
window.addEventListener("hashchange", route);
$("#searchForm").onsubmit = (e) => { e.preventDefault(); const q = $("#searchBox").value.trim(); if (q) location.hash = `#/search?q=${enc(q)}`; };
// ---- barra lateral: en el ordenador se recoge a solo iconos; en pantallas estrechas es
// un menu que se abre con ☰ y se cierra con « o tocando fuera
const narrow = () => window.matchMedia("(max-width: 860px)").matches;
function setDrawer(open) {
  $("#side").classList.toggle("open", open);
  $("#sideBackdrop").classList.toggle("show", open);
  $("#sideBackdrop").hidden = !open;
}
function setCollapsed(c) {
  document.documentElement.classList.toggle("side-collapsed", c);
  try { c ? localStorage.setItem("lm-side", "collapsed") : localStorage.removeItem("lm-side"); } catch (e) { }
  updateSideToggle();
}
function updateSideToggle() {
  const b = $("#sideToggle");
  const collapsed = !narrow() && document.documentElement.classList.contains("side-collapsed");
  b.textContent = collapsed ? "»" : "«";
  const label = narrow() ? t("Cerrar el menú") : collapsed ? t("Desplegar el menú") : t("Recoger el menú");
  b.title = label; b.setAttribute("aria-label", label);
  b.setAttribute("aria-expanded", String(narrow() ? $("#side").classList.contains("open") : !collapsed));
}
$("#sideToggle").onclick = () => narrow() ? setDrawer(false)
  : setCollapsed(!document.documentElement.classList.contains("side-collapsed"));
$("#menuBtn").onclick = () => setDrawer(!$("#side").classList.contains("open"));
$("#sideBackdrop").onclick = () => setDrawer(false);
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && $("#side").classList.contains("open")) setDrawer(false); });
window.matchMedia("(max-width: 860px)").addEventListener?.("change", () => { setDrawer(false); updateSideToggle(); });
updateSideToggle();

// ============================================================ login
function showLogin() { $("#login").classList.remove("hidden"); $("#loginPw").focus(); }
$("#loginForm").onsubmit = async (e) => {
  e.preventDefault();
  const r = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: $("#loginPw").value }) });
  if (r.ok) { $("#login").classList.add("hidden"); await loadFavs(); route(); pollScan(); } else $("#loginErr").textContent = t("Contraseña incorrecta");
};

(async function start() {
  const a = await (await fetch("/api/auth")).json();
  if (a.required && !a.ok) return showLogin();
  await loadFavs(); route(); pollScan();
})();

// botones redondos "?": abren/cierran su explicacion
document.addEventListener("click", (e) => {
  const b = e.target.closest(".info-btn");
  if (!b) return;
  const pop = document.getElementById(b.getAttribute("aria-controls"));
  if (!pop) return;
  const open = !pop.classList.contains("open");
  pop.classList.toggle("open", open);
  b.setAttribute("aria-expanded", String(open));
});
