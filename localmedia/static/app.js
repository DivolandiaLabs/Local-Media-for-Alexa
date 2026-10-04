"use strict";
// ============================================================ utilidades
const $ = (s, el = document) => el.querySelector(s);
const main = $("#main");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const enc = encodeURIComponent;
const fmt = (s) => { s = Math.max(0, Math.floor(s || 0)); const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = String(s % 60).padStart(2, "0"); return h ? `${h}:${String(m).padStart(2, "0")}:${x}` : `${m}:${x}`; };
const art = (tid) => tid ? `/api/art/${tid}` : "/static/cover.svg";
const ago = (t) => { if (!t) return "nunca"; const d = (Date.now() / 1000 - t); if (d < 60) return "ahora"; if (d < 3600) return `hace ${Math.floor(d / 60)} min`; if (d < 86400) return `hace ${Math.floor(d / 3600)} h`; return new Date(t * 1000).toLocaleString(); };

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
  const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden");
  clearTimeout(toast._t); toast._t = setTimeout(() => t.classList.add("hidden"), ms);
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
  P.queue = tracks.slice(); P.shuffle = shuffle; P.idx = shuffle ? Math.floor(Math.random() * tracks.length) : start;
  if (shuffle && start) P.idx = start;
  pOrder(); playIdx(P.idx); updateBtns();
}
function enqueue(tracks) { if (!P.queue.length) return playList(tracks); P.queue.push(...tracks); P.order.push(...tracks.map((_, i) => P.queue.length - tracks.length + i)); toast(`Añadidas ${tracks.length} a la cola`); }
function playIdx(i) {
  const t = P.queue[i]; if (!t) return;
  P.idx = i; audio.src = `/api/stream/${t.id}`; audio.play().catch(() => { });
  $("#npTitle").textContent = t.title; $("#npSub").textContent = [t.artist, t.album].filter(Boolean).join(" — ");
  $("#npArt").src = art(t.id); document.title = `${t.title} · Local Media for Alexa`;
  if ("mediaSession" in navigator) navigator.mediaSession.metadata = new MediaMetadata({ title: t.title, artist: t.artist, album: t.album, artwork: [{ src: art(t.id) }] });
  document.querySelectorAll("tr[data-tid]").forEach((tr) => tr.classList.toggle("playing", +tr.dataset.tid === t.id));
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
$("#pPlay").onclick = () => { if (!audio.src) return; audio.paused ? audio.play() : audio.pause(); };
$("#pNext").onclick = () => step(1);
$("#pPrev").onclick = () => audio.currentTime > 4 ? (audio.currentTime = 0) : step(-1);
$("#pShuffle").onclick = () => { P.shuffle = !P.shuffle; pOrder(); updateBtns(); };
$("#pLoop").onclick = () => { P.loop = !P.loop; updateBtns(); };
$("#pVol").oninput = (e) => audio.volume = e.target.value / 100;
$("#pQueue").onclick = showQueue;
$("#pAlexa").onclick = () => P.queue.length ? sendToAlexa(P.queue.map((t) => t.id), "la cola del navegador", P.shuffle, P.idx) : toast("La cola está vacía");
function updateBtns() { $("#pShuffle").classList.toggle("on", P.shuffle); $("#pLoop").classList.toggle("on", P.loop); }
if ("mediaSession" in navigator) { navigator.mediaSession.setActionHandler("nexttrack", () => step(1)); navigator.mediaSession.setActionHandler("previoustrack", () => step(-1)); }
function showQueue() {
  if (!P.queue.length) return toast("La cola está vacía");
  const rows = P.order.map((i) => { const t = P.queue[i]; return `<div class="item" data-i="${i}"><img src="${art(t.id)}" loading="lazy" alt=""><div class="grow"><div class="t" style="${i === P.idx ? "color:var(--accent)" : ""}">${esc(t.title)}</div><div class="s">${esc(t.artist)}</div></div></div>`; }).join("");
  const b = modal(`<h2 style="margin-top:0">Cola (${P.queue.length})</h2><div class="list">${rows}</div>`);
  b.querySelectorAll(".item").forEach((el) => el.onclick = () => { playIdx(+el.dataset.i); closeModal(); });
}

// ============================================================ acciones
async function sendToAlexa(ids, desc, shuffle = false, first = null) {
  const devs = await api("/api/devices");
  if (!devs.length) {
    modal(`<h2 style="margin-top:0">Enviar a Alexa</h2><p>Aún no conozco ningún Echo. Habla una vez con la skill desde cada dispositivo (por ejemplo <b>“Alexa, abre mi colección”</b>) y aparecerá aquí.</p><p class="muted">Si todavía no has creado la skill, ve a <a href="#/setup" onclick="closeModal()">Configurar Alexa</a>.</p>`);
    return;
  }
  const b = modal(`<h2 style="margin-top:0">Enviar a Alexa</h2><p class="muted">${ids.length} canciones · ${esc(desc)}</p>
    <div class="list">${devs.map((d) => `<div class="item" data-id="${esc(d.id)}"><div style="font-size:26px">🔊</div><div class="grow"><div class="t">${esc(d.name || "Echo …" + d.id.slice(-6))}</div><div class="s">Visto ${ago(d.last_seen)}</div></div></div>`).join("")}</div>
    <label class="check"><input type="checkbox" id="sShuf" ${shuffle ? "checked" : ""}> Aleatorio</label>`);
  b.querySelectorAll(".item").forEach((el) => el.onclick = async () => {
    await api(`/api/devices/${enc(el.dataset.id)}/queue`, { method: "POST", body: { track_ids: ids, desc, shuffle: $("#sShuf").checked, first } });
    modal(`<h2 style="margin-top:0">¡Listo!</h2><p>La cola está preparada en ese Echo. Ahora dile:</p><p style="font-size:20px"><b>“Alexa, abre mi colección”</b></p><p class="muted">o “Alexa, pide a mi colección que continúe”. Las skills de Alexa no pueden empezar a sonar solas: hace falta esa frase.</p>`);
  });
}

async function addToPlaylist(ids) {
  const pls = (await api("/api/playlists")).filter((p) => p.kind === "user");
  const b = modal(`<h2 style="margin-top:0">Añadir a lista</h2><div class="list">${pls.map((p) => `<div class="item" data-id="${p.id}">📜 <div class="grow">${esc(p.name)} <span class="muted">(${p.tracks})</span></div></div>`).join("") || '<p class="muted">No tienes listas propias todavía.</p>'}</div>
  <label class="f">Nueva lista</label><div class="row"><input type="text" id="newPl" placeholder="Nombre"><button class="btn primary" id="newPlBtn">Crear</button></div>`);
  b.querySelectorAll(".item").forEach((el) => el.onclick = async () => { await api(`/api/playlists/${el.dataset.id}/add`, { method: "POST", body: { track_ids: ids } }); closeModal(); toast("Añadidas a la lista"); });
  $("#newPlBtn").onclick = async () => { const n = $("#newPl").value.trim(); if (!n) return; await api("/api/playlists", { method: "POST", body: { name: n, track_ids: ids } }); closeModal(); toast(`Lista “${n}” creada`); };
}

function actionBar(getTracks, desc, opts = {}) {
  const id = "ab" + Math.random().toString(36).slice(2, 7);
  setTimeout(() => {
    const el = document.getElementById(id); if (!el) return;
    el.querySelector("[data-a=play]").onclick = async () => playList(await getTracks());
    el.querySelector("[data-a=shuffle]").onclick = async () => playList(await getTracks(), 0, true);
    el.querySelector("[data-a=queue]").onclick = async () => enqueue(await getTracks());
    el.querySelector("[data-a=alexa]").onclick = async () => sendToAlexa((await getTracks()).map((t) => t.id), desc, !!opts.shuffle);
    el.querySelector("[data-a=list]").onclick = async () => addToPlaylist((await getTracks()).map((t) => t.id));
  });
  return `<div class="actions" id="${id}"><button class="btn primary" data-a="play">▶ Reproducir</button><button class="btn" data-a="shuffle">🔀 Aleatorio</button><button class="btn" data-a="alexa">🔊 Enviar a Alexa</button><button class="btn" data-a="queue">＋ Cola</button><button class="btn" data-a="list">📜 A una lista</button>${opts.extra || ""}</div>`;
}

function trackTable(tracks, opts = {}) {
  if (!tracks.length) return `<div class="empty">No hay canciones.</div>`;
  const id = "tt" + Math.random().toString(36).slice(2, 7);
  const cur = P.queue[P.idx]?.id;
  const rows = tracks.map((t, i) => `<tr data-i="${i}" data-tid="${t.id}" class="${t.id === cur ? "playing" : ""}">
    <td class="n">${opts.numbers === "track" ? (t.track_no || "") : i + 1}</td>
    <td><div style="font-weight:500">${esc(t.title)}</div>${opts.noArtist ? "" : `<div class="muted" style="font-size:13px">${esc(t.artist)}</div>`}</td>
    ${opts.noAlbum ? "" : `<td class="hide-m muted">${esc(t.album)}</td>`}
    <td class="d hide-m">${fmt(t.duration)}</td>
    <td class="a"><button class="icon-btn fav ${favs.has(t.id) ? "on" : ""}" data-fav title="Favorita">★</button><button class="icon-btn" data-more title="Más">⋯</button></td></tr>`).join("");
  setTimeout(() => {
    const el = document.getElementById(id); if (!el) return;
    el.onclick = async (e) => {
      const tr = e.target.closest("tr[data-i]"); if (!tr) return;
      const t = tracks[+tr.dataset.i];
      if (e.target.closest("[data-fav]")) {
        const on = !favs.has(t.id); await api(`/api/favorites/${t.id}`, { method: "POST", body: { on } });
        on ? favs.add(t.id) : favs.delete(t.id); e.target.classList.toggle("on", on); return;
      }
      if (e.target.closest("[data-more]")) return trackMenu(t, tracks, +tr.dataset.i, opts);
      playList(tracks, +tr.dataset.i);
    };
  });
  return `<table class="tracks" id="${id}"><thead><tr><th class="n">#</th><th>Título</th>${opts.noAlbum ? "" : '<th class="hide-m">Álbum</th>'}<th class="d hide-m">⏱</th><th></th></tr></thead><tbody>${rows}</tbody></table>`;
}

function trackMenu(t, list, i, opts) {
  const b = modal(`<div class="row"><img src="${art(t.id)}" style="width:64px;height:64px;border-radius:8px;object-fit:cover"><div><b>${esc(t.title)}</b><div class="muted">${esc(t.artist)} — ${esc(t.album)}</div></div></div>
  <div class="list" style="margin-top:14px">
    <div class="item" data-m="play">▶ Reproducir desde aquí</div>
    <div class="item" data-m="next">⏭ Reproducir a continuación</div>
    <div class="item" data-m="queue">＋ Añadir a la cola</div>
    <div class="item" data-m="alexa">🔊 Enviar a Alexa</div>
    <div class="item" data-m="list">📜 Añadir a una lista</div>
    ${opts.playlistId ? '<div class="item" data-m="remove">🗑 Quitar de esta lista</div>' : ""}
    ${t.n_artist ? `<div class="item" data-m="artist">🎤 Ir al artista</div>` : ""}
    <div class="item" data-m="album">💿 Ir al álbum</div>
  </div><p class="muted" style="font-size:12px;word-break:break-all">${esc(t.path)}<br>${esc((t.ext || "").slice(1).toUpperCase())} ${t.bitrate ? t.bitrate + " kbps" : ""} ${t.year || ""}</p>`);
  b.onclick = async (e) => {
    const m = e.target.closest("[data-m]")?.dataset.m; if (!m) return;
    closeModal();
    if (m === "play") playList(list, i);
    if (m === "next") { if (!P.queue.length) return playList([t]); P.queue.push(t); const k = P.order.indexOf(P.idx); P.order.splice(k + 1, 0, P.queue.length - 1); toast("Sonará a continuación"); }
    if (m === "queue") enqueue([t]);
    if (m === "alexa") sendToAlexa([t.id], t.title);
    if (m === "list") addToPlaylist([t.id]);
    if (m === "artist") location.hash = `#/artist?n=${enc(t.n_artist)}`;
    if (m === "album") location.hash = `#/album?key=${enc(t.album_key)}`;
    if (m === "remove") { const ids = list.filter((_, k) => k !== i).map((x) => x.id); await api(`/api/playlists/${opts.playlistId}`, { method: "PUT", body: { track_ids: ids } }); route(); }
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
    if (!c.tracks) warn += `<div class="panel">👋 <b>Bienvenido.</b> Primero añade tus carpetas de música en <a href="#/settings">Ajustes</a> y pulsa “Escanear”.</div>`;
    if (!s.public_url) warn += `<div class="panel">🔊 Para escuchar en Alexa sigue la guía <a href="#/setup">Configurar Alexa</a>.</div>`;
    if (!s.ffmpeg) warn += `<div class="panel err">⚠ No encuentro <b>ffmpeg</b>: los FLAC, WMA, OGG… no sonarán en Alexa. Instálalo con <code>sudo apt install ffmpeg</code>.</div>`;
    main.innerHTML = `<h1>Tu música</h1><p class="muted">Último escaneo: ${ago(s.last_scan)}</p>${warn}
    <div class="stats"><div class="stat"><b>${c.tracks}</b>canciones</div><div class="stat"><b>${c.albums}</b>álbumes</div><div class="stat"><b>${c.artists}</b>artistas</div><div class="stat"><b>${c.genres}</b>géneros</div><div class="stat"><b>${Math.round(c.seconds / 3600)}</b>horas</div></div>
    <div class="actions" style="margin-top:16px"><button class="btn primary" id="shufAll">🔀 Mezclar toda mi música</button></div>
    ${r.albums.length ? `<h2>Añadido recientemente</h2><div class="grid">${r.albums.slice(0, 18).map(albumCard).join("")}</div>` : ""}
    ${r.most.length ? `<h2>Lo más escuchado</h2>${trackTable(r.most.slice(0, 15))}` : ""}`;
    $("#shufAll").onclick = async () => { const { tracks } = await api("/api/tracks?order=title&limit=500"); playList(tracks, 0, true); };
  },

  async artists() {
    const list = await api("/api/artists");
    let last = "";
    main.innerHTML = `<h1>Artistas</h1><p class="muted">${list.length} artistas</p>${letterIndex(list, "n")}<div class="list">${list.map((a) => {
      const l = (a.n[0] || "#").toUpperCase().replace(/[^A-Z]/, "#"); const anchor = l !== last ? `id="L_${l === "#" ? "num" : l}"` : ""; last = l;
      return `<div class="item" ${anchor} onclick="location.hash='#/artist?n=${enc(a.n)}'"><img loading="lazy" src="${art(a.sample)}" alt=""><div class="grow"><div class="t">${esc(a.name)}</div><div class="s">${a.albums} álbumes · ${a.tracks} canciones</div></div></div>`;
    }).join("")}</div>`;
  },

  async artist(q) {
    const d = await api(`/api/artist?n=${enc(q.n)}`);
    const name = d.tracks[0] ? (d.tracks.find((t) => t.n_artist === q.n)?.artist || d.tracks[0].album_artist) : q.n;
    main.innerHTML = `<div class="head"><img src="${art(d.tracks[0]?.id)}" alt=""><div class="meta"><div class="muted">Artista</div><h1>${esc(name)}</h1><div class="muted">${d.albums.length} álbumes · ${d.tracks.length} canciones</div>${actionBar(async () => d.tracks, name)}</div></div>
    <h2>Álbumes</h2><div class="grid">${d.albums.map(albumCard).join("")}</div><h2>Canciones</h2>${trackTable(d.tracks, { noArtist: true })}`;
  },

  async albums(q) {
    const order = q.order || "name";
    const list = await api(`/api/albums?order=${order}`);
    main.innerHTML = `<div class="row"><h1>Álbumes</h1><span class="spacer"></span><select id="ord" style="width:auto"><option value="name">Por nombre</option><option value="recent">Recientes</option><option value="year">Por año</option></select></div><p class="muted">${list.length} álbumes</p><div class="grid">${list.map(albumCard).join("")}</div>`;
    $("#ord").value = order; $("#ord").onchange = (e) => location.hash = `#/albums?order=${e.target.value}`;
  },

  async album(q) {
    const tracks = await api(`/api/album?key=${enc(q.key)}`);
    if (!tracks.length) { main.innerHTML = `<div class="empty">Álbum no encontrado.</div>`; return; }
    const t0 = tracks[0], artist = t0.album_artist || t0.artist;
    const dur = tracks.reduce((s, t) => s + (t.duration || 0), 0);
    main.innerHTML = `<div class="head"><img src="${art(t0.id)}" alt=""><div class="meta"><div class="muted">Álbum</div><h1>${esc(t0.album)}</h1>
      <div>${t0.n_album_artist || t0.n_artist ? `<a href="#/artist?n=${enc(t0.n_album_artist || t0.n_artist)}">${esc(artist)}</a>` : ""} <span class="muted">${t0.year ? "· " + t0.year : ""} · ${tracks.length} canciones · ${fmt(dur)} ${t0.genre ? "· " + esc(t0.genre) : ""}</span></div>
      ${actionBar(async () => tracks, t0.album)}</div></div>${trackTable(tracks, { numbers: "track", noAlbum: true })}`;
  },

  async tracks(q) {
    const order = q.order || "title", query = q.q || "";
    let offset = 0, total = 0, all = [];
    main.innerHTML = `<div class="row"><h1>Canciones</h1><span class="spacer"></span><input id="tq" type="text" placeholder="Filtrar…" style="width:200px" value="${esc(query)}"><select id="ord" style="width:auto"><option value="title">Título</option><option value="artist">Artista</option><option value="album">Álbum</option><option value="recent">Recientes</option><option value="year">Año</option></select></div><p class="muted" id="tc"></p><div id="tl"></div><div class="actions"><button class="btn hidden" id="more">Cargar más</button></div>`;
    $("#ord").value = order;
    $("#ord").onchange = (e) => location.hash = `#/tracks?order=${e.target.value}&q=${enc($("#tq").value)}`;
    $("#tq").onchange = (e) => location.hash = `#/tracks?order=${order}&q=${enc(e.target.value)}`;
    const load = async () => {
      const d = await api(`/api/tracks?order=${order}&offset=${offset}&limit=300&q=${enc(query)}`);
      total = d.total; all = all.concat(d.tracks); offset += d.tracks.length;
      $("#tc").textContent = `${total} canciones`; $("#tl").innerHTML = trackTable(all);
      $("#more").classList.toggle("hidden", offset >= total);
    };
    $("#more").onclick = load; await load();
  },

  async genres() {
    const list = await api("/api/genres");
    main.innerHTML = `<h1>Géneros</h1><div class="grid">${list.map((g) => `<div class="card" onclick="location.hash='#/genre?n=${enc(g.n)}'"><img loading="lazy" src="${art(g.sample)}" alt=""><div class="t">${esc(g.name)}</div><div class="s">${g.tracks} canciones</div></div>`).join("") || '<div class="empty">Sin géneros (revisa las etiquetas de tus archivos).</div>'}</div>`;
  },

  async genre(q) {
    const d = await api(`/api/genre?n=${enc(q.n)}`);
    const name = d.tracks[0]?.genre || q.n;
    main.innerHTML = `<div class="head"><img src="${art(d.tracks[0]?.id)}" alt=""><div class="meta"><div class="muted">Género</div><h1>${esc(name)}</h1><div class="muted">${d.tracks.length} canciones</div>${actionBar(async () => d.tracks, name, { shuffle: true })}</div></div><h2>Álbumes</h2><div class="grid">${d.albums.map(albumCard).join("")}</div>`;
  },

  async folders(q) {
    const d = await api(`/api/folders${q.path ? "?path=" + enc(q.path) : ""}`);
    const up = d.path ? `<div class="item" onclick="location.hash='#/folders${d.parent ? "?path=" + enc(d.parent) : ""}'">⬆️ <div class="grow">..</div></div>` : "";
    main.innerHTML = `<h1>Carpetas</h1><p class="muted" style="word-break:break-all">${esc(d.path || "Carpetas de música")}</p>
    ${d.path ? actionBar(async () => api(`/api/folder-tracks?path=${enc(d.path)}`), d.path.split(/[\\/]/).pop()) : ""}
    <div class="list" style="margin-top:12px">${up}${d.folders.map((f) => `<div class="item" onclick="location.hash='#/folders?path=${enc(f.path)}'">📁 <div class="grow t">${esc(f.name)}</div></div>`).join("")}</div>
    ${d.tracks.length ? trackTable(d.tracks, { numbers: "track" }) : ""}
    ${!d.path && !d.folders.length ? '<div class="empty">No hay carpetas escaneadas. Añádelas en <a href="#/settings">Ajustes</a>.</div>' : ""}`;
  },

  async playlists() {
    const list = await api("/api/playlists");
    main.innerHTML = `<div class="row"><h1>Listas</h1><span class="spacer"></span><button class="btn primary" id="newPl">＋ Nueva lista</button></div>
    <p class="muted">Las listas .m3u/.m3u8/.pls que haya en tus carpetas se importan solas. Pídelas a Alexa con “pon la lista …”.</p>
    <div class="grid" style="margin-top:12px">
      <div class="card" onclick="location.hash='#/favorites'"><img src="/static/cover.svg" alt=""><div class="t">⭐ Favoritas</div><div class="s">Automática</div></div>
      ${list.map((p) => `<div class="card" onclick="location.hash='#/playlist?id=${p.id}'"><img loading="lazy" src="${art(p.sample)}" alt=""><div class="t">${esc(p.name)}</div><div class="s">${p.tracks} canciones · ${p.kind === "file" ? "archivo" : "propia"}</div></div>`).join("")}</div>`;
    $("#newPl").onclick = async () => { const n = prompt("Nombre de la lista"); if (n) { const r = await api("/api/playlists", { method: "POST", body: { name: n } }); location.hash = `#/playlist?id=${r.id}`; } };
  },

  async playlist(q) {
    const d = await api(`/api/playlists/${q.id}`);
    const p = d.playlist, own = p.kind === "user";
    const extra = `<a class="btn" href="/api/playlists/${p.id}/m3u">⬇ M3U</a>${own ? `<button class="btn" id="ren">✏️ Renombrar</button><button class="btn danger" id="del">🗑 Borrar</button>` : ""}`;
    main.innerHTML = `<div class="head"><img src="${art(d.tracks[0]?.id)}" alt=""><div class="meta"><div class="muted">Lista ${own ? "" : "(archivo " + esc(p.path) + ")"}</div><h1>${esc(p.name)}</h1><div class="muted">${d.tracks.length} canciones</div>${actionBar(async () => d.tracks, p.name, { extra })}</div></div>${trackTable(d.tracks, { playlistId: own ? p.id : null })}`;
    if (own) {
      $("#ren").onclick = async () => { const n = prompt("Nuevo nombre", p.name); if (n) { await api(`/api/playlists/${p.id}`, { method: "PUT", body: { name: n } }); route(); } };
      $("#del").onclick = async () => { if (confirm(`¿Borrar la lista “${p.name}”?`)) { await api(`/api/playlists/${p.id}`, { method: "DELETE" }); location.hash = "#/playlists"; } };
    }
  },

  async favorites() {
    const tracks = await api("/api/favorites");
    main.innerHTML = `<div class="head"><img src="/static/cover.svg" alt=""><div class="meta"><div class="muted">Lista automática</div><h1>⭐ Favoritas</h1><div class="muted">${tracks.length} canciones · Dile a Alexa “pon mis favoritas”</div>${actionBar(async () => tracks, "tus favoritas", { shuffle: true })}</div></div>${trackTable(tracks)}`;
  },

  async search(q) {
    const term = q.q || ""; $("#searchBox").value = term;
    const r = await api(`/api/search?q=${enc(term)}`);
    const sec = (title, html) => html ? `<h2>${title}</h2>${html}` : "";
    main.innerHTML = `<h1>Resultados para “${esc(term)}”</h1><p class="muted">Búsqueda aproximada, igual que la que usa Alexa.</p>
      ${sec("Artistas", (r.artists || []).map((a) => `<div class="item" onclick="location.hash='#/artist?n=${enc(a.n)}'">🎤 <div class="grow">${esc(a.name)}</div><span class="pill">${Math.round(a.score * 100)}%</span></div>`).join(""))}
      ${sec("Álbumes", (r.albums || []).map((a) => `<div class="item" onclick="location.hash='#/album?key=${enc(a.key)}'">💿 <div class="grow">${esc(a.name)}</div><span class="pill">${Math.round(a.score * 100)}%</span></div>`).join(""))}
      ${sec("Listas", (r.playlists || []).map((p) => `<div class="item" onclick="location.hash='#/playlist?id=${p.id}'">📜 <div class="grow">${esc(p.name)}</div></div>`).join(""))}
      ${sec("Géneros", (r.genres || []).map((g) => `<div class="item" onclick="location.hash='#/genre?n=${enc(g.n)}'">🎸 <div class="grow">${esc(g.name)}</div></div>`).join(""))}
      ${sec("Canciones", (r.tracks || []).length ? trackTable(r.tracks) : "")}
      ${!Object.values(r).some((v) => v.length) ? '<div class="empty">Nada encontrado.</div>' : ""}`;
  },

  async alexa() {
    const [devs, s] = await Promise.all([api("/api/devices"), api("/api/status")]);
    main.innerHTML = `<h1>Alexa</h1><p class="muted">Tus Echo aparecen aquí cuando hablan con la skill. Puedes ponerles nombre, ver qué suena y su cola.</p>
    ${devs.map((d) => `<div class="panel"><div class="row"><div style="font-size:30px">🔊</div><div class="grow" style="flex:1"><b>${esc(d.name || "Echo …" + d.id.slice(-6))}</b> ${d.playing ? '<span class="pill ok">sonando</span>' : ""} ${d.pending ? '<span class="pill">cola preparada</span>' : ""}<div class="muted" style="font-size:13px">Visto ${ago(d.last_seen)} · ${d.queue_len} en cola ${d.shuffle ? "· 🔀" : ""} ${d.loop ? "· 🔁" : ""}</div></div>
      <button class="btn small" data-ren="${esc(d.id)}">✏️ Nombre</button><button class="btn small" data-q="${esc(d.id)}">☰ Cola</button><button class="btn small danger" data-del="${esc(d.id)}">✕</button></div>
      ${d.current ? `<div class="item" style="margin-top:10px"><img src="${art(d.current.id)}" alt=""><div class="grow"><div class="t">${esc(d.current.title)}</div><div class="s">${esc(d.current.artist)} — ${esc(d.current.album)}</div></div></div>` : ""}</div>`).join("") || `<div class="panel">Todavía ningún Echo ha usado la skill. Di <b>“Alexa, abre mi colección”</b>.</div>`}
    <h2>Últimas peticiones de Alexa</h2><div class="panel">${s.recent_requests.length ? s.recent_requests.map((r) => `<div class="muted" style="font-size:13px">${new Date(r.t * 1000).toLocaleTimeString()} · ${esc(r.type)} ${esc(r.intent || "")} · …${esc(r.device)}</div>`).join("") : '<span class="muted">Ninguna desde que arrancó Local Media.</span>'}</div>
    <h2>Qué puedes decir</h2><div class="panel">${sayings()}</div>`;
    main.querySelectorAll("[data-ren]").forEach((b) => b.onclick = async () => { const n = prompt("Nombre del dispositivo (p. ej. Echo salón)"); if (n != null) { await api(`/api/devices/${enc(b.dataset.ren)}`, { method: "PUT", body: { name: n } }); route(); } });
    main.querySelectorAll("[data-del]").forEach((b) => b.onclick = async () => { if (confirm("¿Olvidar este dispositivo?")) { await api(`/api/devices/${enc(b.dataset.del)}`, { method: "DELETE" }); route(); } });
    main.querySelectorAll("[data-q]").forEach((b) => b.onclick = async () => { const d = await api(`/api/devices/${enc(b.dataset.q)}/queue`); const box = modal(`<h2 style="margin-top:0">Cola del Echo</h2>${trackTable(d.tracks)}`); box.querySelectorAll("tr[data-i]")[d.pos]?.classList.add("playing"); });
  },

  async setup() {
    const [s, c] = await Promise.all([api("/api/status"), api("/api/config")]);
    main.innerHTML = `<h1>Configurar Alexa</h1><p class="muted">Se hace una sola vez. Tendrás tu propia skill privada (gratis) que solo funciona en tus Echo.</p>
    <ol class="steps">
      <li><b>Haz accesible el puerto público por HTTPS.</b> Alexa solo habla con direcciones <code>https://</code> con certificado válido. Local Media escucha para Alexa en el puerto <code>${c.public_port}</code> (solo expone la skill y el audio, nunca esta web).
        <div class="panel" style="margin-top:8px"><b>Opción A — ngrok</b> (gratis, sin dominio ni tocar el router): crea una cuenta en ngrok.com, reserva tu dominio gratuito y ejecuta <code>ngrok http --domain=TU-NOMBRE.ngrok-free.app ${c.public_port}</code>
        <p><b>Opción B — Cloudflare Tunnel</b> con un dominio propio:</p><pre class="code">cloudflared tunnel login
cloudflared tunnel create localmedia
cloudflared tunnel route dns localmedia musica.TU-DOMINIO.com
cloudflared tunnel run --url http://localhost:${c.public_port} localmedia</pre>
        <span class="hint">El instalador puede instalar cloudflared: <code>./install.sh --tunnel</code>.</span>
        <p><b>Opción C — Router + DuckDNS + Caddy</b> (abre el 443 hacia la Pi): <code>reverse_proxy localhost:${c.public_port}</code></p></div></li>
      <li><b>Escribe aquí la URL pública</b> y pruébala.
        <div class="row" style="margin-top:8px"><input type="url" id="pubUrl" placeholder="https://tu-nombre.ngrok-free.app" value="${esc(c.public_url)}" style="flex:1 1 180px;min-width:0"><button class="btn primary" id="savePub">Guardar y probar</button></div><p id="pubRes" class="hint"></p></li>
      <li><b>Conecta con Amazon.</b> Local Media crea y configura la skill él solo.
        <div id="amz" class="panel amz" style="margin-top:8px"><span class="muted">Cargando…</span></div></li>
    </ol>
    <details class="panel manual"><summary><b>Prefiero crear la skill a mano</b> <span class="muted">(sin conectar con Amazon)</span></summary>
    <ol class="steps" style="margin-top:14px">
      <li><b>Crea la skill</b> en <a href="https://developer.amazon.com/alexa/console/ask" target="_blank" rel="noopener">developer.amazon.com/alexa/console/ask</a> (con la misma cuenta de Amazon que tus Echo): <i>Create Skill</i> → nombre “Mi Colección”, idioma <b>Spanish (ES)</b> → tipo <b>Other</b> → <b>Custom</b> → <b>Provision your own</b> → <b>Start from Scratch</b>.</li>
      <li><b>Pega el modelo de voz</b> en <i>Build → Interaction Model → JSON Editor</i>, <i>Save</i> y <i>Build skill</i>.
        <div class="actions"><a class="btn primary" href="/api/skill/model?locale=es-ES">⬇ es-ES.json</a><a class="btn" href="/api/skill/model?locale=es-MX">es-MX</a><a class="btn" href="/api/skill/model?locale=es-US">es-US</a><a class="btn" href="/api/skill/model?locale=en-US">en-US</a><a class="btn" href="/api/skill/model?locale=en-GB">en-GB</a><a class="btn" href="/api/skill/model?locale=es-ES&library=0">Modelo genérico</a></div></li>
      <li><b>Activa el reproductor de audio:</b> <i>Build → Interfaces</i> → <b>Audio Player</b> → <i>Save Interfaces</i> → <i>Build skill</i>.</li>
      <li><b>Endpoint:</b> <i>Build → Endpoint</i> → <b>HTTPS</b> → Default Region:<div style="margin:6px 0"><code id="ep">${esc(s.alexa_endpoint || "https://TU-DOMINIO/alexa")}</code> <button class="btn small" id="copyEp">Copiar</button></div>certificado: <b>“My development endpoint has a certificate from a trusted certificate authority”</b>.</li>
      <li><b>Limita Local Media a tu skill:</b> copia el <i>Skill ID</i> (amzn1.ask.skill.…) en <a href="#/settings">Ajustes</a>.</li>
      <li><b>Prueba:</b> pestaña <i>Test</i> → <b>Development</b>.</li>
    </ol></details>
    <h2>Qué puedes decir</h2><div class="panel">${sayings()}</div>`;
    $("#copyEp").onclick = () => copy($("#ep").textContent);
    $("#savePub").onclick = async () => {
      await api("/api/config", { method: "POST", body: { public_url: $("#pubUrl").value.trim() } });
      $("#pubRes").textContent = "Probando…";
      const r = await api("/api/test-public");
      $("#pubRes").innerHTML = `<span class="${r.ok ? "ok" : "err"}">${r.ok ? "✔" : "✖"} ${esc(r.msg)}</span>`;
      const s2 = await api("/api/status"); $("#ep").textContent = s2.alexa_endpoint || "https://TU-DOMINIO/alexa";
      drawAmazon();
    };
    drawAmazon();
  },

  async settings() {
    const [c, s] = await Promise.all([api("/api/config"), api("/api/status")]);
    main.innerHTML = `<h1>Ajustes</h1>
    <div class="panel"><h2 style="margin-top:0">📁 Carpetas de música</h2><div id="folders"></div>
      <div class="actions"><button class="btn" id="addFolder">＋ Añadir carpeta</button><button class="btn primary" id="scan">🔄 Escanear ahora</button><button class="btn" id="fullScan">Reescanear todo</button></div>
      <p class="hint" id="scanState"></p>
      <label class="f">Reescaneo automático (minutos, 0 = nunca)</label><input type="number" id="rescan" min="0" value="${c.rescan_minutes}"></div>

    <div class="panel"><h2 style="margin-top:0">📡 Servidores UPnP / DLNA</h2><p class="hint">Añade la música de un NAS, Plex, MiniDLNA, Jellyfin, Serviio… de tu red.</p>
      <label class="check"><input type="checkbox" id="upnpOn" ${c.upnp_enabled ? "checked" : ""}> Usar servidores UPnP/DLNA</label>
      <div id="upnpList"></div><div class="actions"><button class="btn" id="upnpFind">🔍 Buscar servidores</button></div></div>

    <div class="panel"><h2 style="margin-top:0">🔊 Alexa</h2>
      <label class="f">URL pública (https)</label><input type="url" id="pub" value="${esc(c.public_url)}" placeholder="https://musica.tudominio.com">
      <label class="f">Skill IDs permitidos (uno por línea)</label><textarea id="skills" rows="2" placeholder="amzn1.ask.skill.…">${esc((c.skill_ids || []).join("\n"))}</textarea><p class="hint">Vacío = acepta cualquier skill. Recomendado rellenarlo.</p>
      <label class="check"><input type="checkbox" id="verify" ${c.verify_signatures ? "checked" : ""}> Comprobar la firma de Amazon en cada petición ${s.crypto ? "" : '<span class="pill bad">falta cryptography</span>'}</label>
      <label class="check"><input type="checkbox" id="shufArt" ${c.shuffle_artist ? "checked" : ""}> Al pedir un artista, mezclar sus canciones</label>
      <label class="f">Máximo de canciones por cola</label><input type="number" id="maxq" min="50" max="5000" value="${c.max_queue}"></div>

    <div class="panel"><h2 style="margin-top:0">🎚 Conversión de audio</h2><p class="hint">Los Echo solo reproducen MP3 y AAC/M4A. El resto (FLAC, WMA, OGG, OPUS, WAV, ALAC…) se convierte al vuelo con ffmpeg ${s.ffmpeg ? '<span class="pill ok">ffmpeg OK</span>' : '<span class="pill bad">ffmpeg no encontrado</span>'}</p>
      <label class="f">Modo</label><select id="trans"><option value="auto">Automático (solo lo necesario)</option><option value="always">Siempre a MP3</option><option value="never">Nunca</option></select>
      <label class="f">Calidad MP3 (kbps)</label><select id="br"><option>128</option><option>192</option><option>256</option><option>320</option></select>
      <label class="f">Ruta de ffmpeg</label><input type="text" id="ffmpeg" value="${esc(c.ffmpeg)}"></div>

    <div class="panel"><h2 style="margin-top:0">🔒 Web y red</h2>
      <label class="f">Contraseña de esta web (vacía = sin contraseña)</label><input type="password" id="pw" value="${esc(c.web_password)}" autocomplete="new-password">
      <div class="row"><div style="flex:1"><label class="f">Puerto web (LAN)</label><input type="number" id="lanp" value="${c.lan_port}"></div><div style="flex:1"><label class="f">Puerto público (Alexa)</label><input type="number" id="pubp" value="${c.public_port}"></div></div>
      <p class="hint">Los cambios de puerto se aplican al reiniciar: <code>sudo systemctl restart localmedia</code></p></div>

    <div class="actions"><button class="btn primary" id="save">💾 Guardar ajustes</button></div>
    <p class="muted" style="margin-top:20px;font-size:13px">Local Media for Alexa ${esc(s.version)} · etiquetas: ${s.mutagen ? "mutagen OK" : "<span class='err'>falta mutagen</span>"}</p>`;
    let folders = c.music_folders.slice(), servers = (c.upnp_servers || []).slice();
    const drawFolders = () => $("#folders").innerHTML = folders.map((f, i) => `<div class="item"><span>📁</span><div class="grow t">${esc(f)}</div><button class="icon-btn" data-rm="${i}">✕</button></div>`).join("") || '<p class="muted">Ninguna carpeta todavía.</p>';
    const drawServers = () => $("#upnpList").innerHTML = servers.map((sv, i) => `<label class="check"><input type="checkbox" data-sv="${i}" ${sv.enabled !== false ? "checked" : ""}> ${esc(sv.name)} <span class="muted" style="font-size:12px">${esc(sv.location)}</span> <button class="icon-btn" data-svrm="${i}">✕</button></label>`).join("");
    drawFolders(); drawServers();
    $("#folders").onclick = (e) => { const b = e.target.closest("[data-rm]"); if (b) { folders.splice(+b.dataset.rm, 1); drawFolders(); } };
    $("#upnpList").onclick = (e) => { const b = e.target.closest("[data-svrm]"); if (b) { e.preventDefault(); servers.splice(+b.dataset.svrm, 1); drawServers(); } const cb = e.target.closest("[data-sv]"); if (cb) servers[+cb.dataset.sv].enabled = cb.checked; };
    $("#trans").value = c.transcode; $("#br").value = String(c.transcode_bitrate);
    $("#addFolder").onclick = () => pickFolder((p) => { if (!folders.includes(p)) folders.push(p); drawFolders(); });
    $("#upnpFind").onclick = async () => {
      $("#upnpFind").textContent = "Buscando…";
      try { const found = await api("/api/upnp/discover"); for (const f of found) if (!servers.some((x) => x.location === f.location)) servers.push({ location: f.location, name: f.name, enabled: true }); drawServers(); toast(found.length ? `${found.length} servidores encontrados` : "No se encontró ninguno"); } catch (e) { toast("Error buscando servidores"); }
      $("#upnpFind").textContent = "🔍 Buscar servidores";
    };
    const save = async () => {
      await api("/api/config", { method: "POST", body: {
        music_folders: folders, rescan_minutes: +$("#rescan").value, upnp_enabled: $("#upnpOn").checked, upnp_servers: servers,
        public_url: $("#pub").value.trim(), skill_ids: $("#skills").value.split(/\s+/), verify_signatures: $("#verify").checked,
        shuffle_artist: $("#shufArt").checked, max_queue: +$("#maxq").value, transcode: $("#trans").value, transcode_bitrate: +$("#br").value,
        ffmpeg: $("#ffmpeg").value.trim() || "ffmpeg", web_password: $("#pw").value, lan_port: +$("#lanp").value, public_port: +$("#pubp").value } });
      toast("Ajustes guardados");
    };
    $("#save").onclick = save;
    $("#scan").onclick = async () => { await save(); await api("/api/scan", { method: "POST", body: {} }); pollScan(); };
    $("#fullScan").onclick = async () => { await save(); await api("/api/scan", { method: "POST", body: { full: true } }); pollScan(); };
    pollScan();
  },
};

// ============================================================ Conectar con Amazon
const LOCALES = [["es-ES", "Español (España)"], ["es-MX", "Español (México)"], ["es-US", "Español (EE. UU.)"], ["en-US", "Inglés (EE. UU.)"], ["en-GB", "Inglés (Reino Unido)"]];
function copy(text) { navigator.clipboard?.writeText(text).then(() => toast("Copiado")); }
const copyRow = (v) => `<div class="copyrow"><code>${esc(v)}</code><button class="btn small" data-copy="${esc(v)}">Copiar</button></div>`;
let amzTimer = null, amzWaitingLogin = false;

async function drawAmazon() {
  clearTimeout(amzTimer);
  const box = document.getElementById("amz"); if (!box) return;
  let a; try { a = await api("/api/amazon"); } catch (e) { return; }
  const j = a.job || {};
  const steps = j.steps || [];
  const locBoxes = `<div class="locales">${LOCALES.map(([k, n]) => `<label class="check"><input type="checkbox" data-loc="${k}" ${a.locales.includes(k) ? "checked" : ""}> ${n}</label>`).join("")}</div>`;
  const progress = steps.length || j.error ? `<div class="amz-log">${steps.map((x, i) => { const now = i === steps.length - 1 && j.running; return `<div class="${now ? "now" : "done"}">${now ? '<span class="spin"></span>' : "✔"} ${esc(x.text)}</div>`; }).join("")}${j.error ? `<div class="err">✖ ${esc(j.error)}</div>` : ""}</div>` : "";
  let html;
  if (!a.public_ok) {
    html = `<p class="muted">Primero completa el paso 2: hace falta la URL pública <code>https://…</code>.</p>`;
  } else if (!a.configured) {
    html = `<p>Amazon pide que crees una vez un <b>perfil de seguridad</b>: es el permiso para que Local Media cree la skill en tu cuenta. Son 2 minutos:</p>
    <ol class="sub">
      <li>Abre <a href="https://developer.amazon.com/loginwithamazon/console/site/lwa/overview.html" target="_blank" rel="noopener">Login with Amazon</a> con la misma cuenta de Amazon que tus Echo y pulsa <b>Create a New Security Profile</b>.</li>
      <li>Rellena <b>Name</b>: <code>Local Media for Alexa</code>, <b>Description</b>: <code>Mi música en Alexa</code>, y en <b>Consent Privacy Notice URL</b> pega:${copyRow(a.privacy_url)}Pulsa <b>Save</b>.</li>
      <li>En el perfil nuevo abre <b>Web Settings</b> → <b>Edit</b>, y en <b>Allowed Return URLs</b> pega:${copyRow(a.redirect_uri)}Pulsa <b>Save</b>.</li>
      <li>En esa misma pantalla están el <b>Client ID</b> y el <b>Client Secret</b> (pulsa <i>Show Secret</i>). Pégalos aquí:</li>
    </ol>
    <label class="f">Client ID</label><input type="text" id="lwaId" placeholder="amzn1.application-oa2-client.…" value="${esc(a.client_id || "")}">
    <label class="f">Client Secret</label><input type="password" id="lwaSecret" placeholder="amzn1.oa2-cs.v1.…" autocomplete="off">
    <div class="actions"><button class="btn primary" id="lwaSave">Guardar</button></div>`;
  } else if (!a.connected) {
    html = `<p>Elige los idiomas de tus Echo y pulsa el botón. Se abrirá Amazon para que inicies sesión y des permiso.</p>${locBoxes}
    <div class="actions"><button class="btn amazon" id="amzConnect">CONECTAR CON AMAZON</button></div>
    ${amzWaitingLogin ? `<p class="hint"><span class="spin"></span> Esperando a que inicies sesión en la pestaña de Amazon…</p>` : ""}${progress}
    <p class="hint">¿Te equivocaste con el Client ID o el Secret? <a href="javascript:void 0" id="lwaReset">Cambiarlos</a></p>`;
  } else {
    const done = !j.running && a.skill_id && !j.error && steps.length;
    html = `<div class="row"><span class="pill ok">✔ Conectado</span><span class="muted">${esc(a.vendor_name || "tu cuenta de Amazon")}</span></div>
    ${a.skill_id ? `<p class="hint">Tu skill: <code>${esc(a.skill_id)}</code> · <a href="https://developer.amazon.com/alexa/console/ask" target="_blank" rel="noopener">verla en Amazon</a></p>` : ""}
    ${progress}
    ${done ? `<p class="ok" style="font-size:17px">Ya puedes decir: <b>“Alexa, abre mi colección”</b></p>` : ""}
    <label class="f">Idiomas de la skill</label>${locBoxes}
    <label class="check"><input type="checkbox" id="amzAuto" ${a.auto_model ? "checked" : ""}> Actualizar el modelo de voz tras cada escaneo si cambia la biblioteca</label>
    <div class="actions"><button class="btn primary" id="amzSetup" ${j.running ? "disabled" : ""}>${a.skill_id ? "🔄 Volver a configurar la skill" : "Crear mi skill"}</button>
    <button class="btn" id="amzModel" ${j.running || !a.skill_id ? "disabled" : ""}>🗣 Actualizar modelo de voz</button>
    <button class="btn danger" id="amzOff" ${j.running ? "disabled" : ""}>Desconectar</button></div>`;
  }
  box.innerHTML = html;
  box.querySelectorAll("[data-copy]").forEach((b) => b.onclick = () => copy(b.dataset.copy));
  const saveLocales = () => api("/api/amazon/settings", { method: "POST", body: { locales: [...box.querySelectorAll("[data-loc]:checked")].map((x) => x.dataset.loc) } });
  box.querySelectorAll("[data-loc]").forEach((x) => x.onchange = saveLocales);
  const on = (id, fn) => { const el = document.getElementById(id); if (el) el.onclick = fn; };
  on("lwaSave", async () => {
    const id = $("#lwaId").value.trim(), sec = $("#lwaSecret").value.trim();
    if (!id.startsWith("amzn1.application-oa2-client.")) return toast("El Client ID empieza por amzn1.application-oa2-client.");
    if (!sec) return toast("Falta el Client Secret");
    await api("/api/amazon/settings", { method: "POST", body: { client_id: id, client_secret: sec } }); drawAmazon();
  });
  on("lwaReset", async () => { await api("/api/amazon/settings", { method: "POST", body: { client_id: "" } }); drawAmazon(); });
  on("amzConnect", async () => {
    const w = window.open("about:blank", "_blank");
    const r = await fetch("/api/amazon/login").then((x) => x.json()).catch(() => ({ error: "No se pudo contactar con Local Media" }));
    if (r.url) { if (w) w.location = r.url; else location.href = r.url; amzWaitingLogin = true; drawAmazon(); }
    else { if (w) w.close(); toast(r.error || "No se pudo abrir Amazon"); }
  });
  on("amzSetup", async () => { await saveLocales(); await api("/api/amazon/setup", { method: "POST", body: {} }); drawAmazon(); });
  on("amzModel", async () => { await api("/api/amazon/update-model", { method: "POST", body: {} }); drawAmazon(); });
  on("amzOff", async () => { if (confirm("¿Desconectar de Amazon? Tu skill seguirá funcionando; solo dejará de actualizarse sola.")) { await api("/api/amazon/disconnect", { method: "POST", body: {} }); drawAmazon(); } });
  const au = document.getElementById("amzAuto"); if (au) au.onchange = () => api("/api/amazon/settings", { method: "POST", body: { auto_model: au.checked } });
  if (a.connected) amzWaitingLogin = false;
  if (j.running || amzWaitingLogin) amzTimer = setTimeout(drawAmazon, 2000);
}

function sayings() {
  const s = ["Alexa, abre mi colección", "Alexa, pide a mi colección que ponga Queen", "Alexa, pide a mi colección que ponga música de Estopa", "Alexa, pide a mi colección que ponga el álbum Thriller", "Alexa, pide a mi colección que ponga la canción Bohemian Rhapsody", "Alexa, pide a mi colección que ponga la lista Viaje", "Alexa, pide a mi colección que ponga música rock", "Alexa, pide a mi colección que ponga música de los ochenta", "Alexa, pide a mi colección que ponga música del 1995", "Alexa, pide a mi colección que ponga la carpeta Vinilos", "Alexa, pide a mi colección que ponga toda mi música", "Alexa, pide a mi colección que ponga mis favoritas", "Alexa, pide a mi colección que ponga lo último que he añadido", "Alexa, pide a mi colección que ponga lo más escuchado", "Alexa, pide a mi colección qué está sonando", "Alexa, pide a mi colección que ponga más de este artista", "Alexa, pide a mi colección que ponga este álbum", "Alexa, siguiente / anterior / pausa / continúa", "Alexa, aleatorio / quita el aleatorio", "Alexa, repite / desactiva la repetición", "Alexa, vuelve a empezar"];
  return s.map((x) => `<div>🗣 ${esc(x)}</div>`).join("");
}

async function pickFolder(cb, path) {
  const d = await api(`/api/browse-dirs${path ? "?path=" + enc(path) : ""}`);
  const b = modal(`<h2 style="margin-top:0">Elegir carpeta</h2><div class="row">${(d.shortcuts || []).map((s) => `<button class="btn small" data-go="${esc(s)}">${esc(s)}</button>`).join("")}</div>
    <p><code>${esc(d.path)}</code></p>${d.error ? `<p class="err">${esc(d.error)}</p>` : ""}
    <div class="dirlist"><div data-go="${esc(d.parent)}">⬆️ ..</div>${d.dirs.map((x) => `<div data-go="${esc(d.path.replace(/[\\/]$/, "") + (d.path.includes("\\") ? "\\" : "/") + x)}">📁 ${esc(x)}</div>`).join("")}</div>
    <div class="row"><input type="text" id="manualPath" value="${esc(d.path)}" style="flex:1"><button class="btn primary" id="choose">Usar esta carpeta</button></div>
    <p class="hint">Discos USB: /media/… · Carpetas de red montadas: /mnt/…</p>`);
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
      const txt = `🔄 ${sc.phase} ${sc.total ? `${sc.done}/${sc.total}` : ""}`;
      badge.textContent = txt; badge.classList.remove("hidden");
      if ($("#scanState")) $("#scanState").textContent = txt;
      scanTimer = setTimeout(pollScan, 1500);
    } else {
      badge.classList.add("hidden");
      if ($("#scanState")) $("#scanState").innerHTML = sc.finished ? `Último escaneo: ${ago(sc.finished)} · +${sc.added} nuevas · ${sc.updated} actualizadas · −${sc.removed} borradas ${sc.error ? `<span class="err">${esc(sc.error)}</span>` : ""}` : "";
      if (pollScan.wasRunning) { toast("Escaneo terminado"); pollScan.wasRunning = false; }
    }
    if (sc.running) pollScan.wasRunning = true;
  } catch (e) { }
}

// ============================================================ tema (auto / oscuro / claro)
const darkQuery = window.matchMedia("(prefers-color-scheme: dark)");
function getTheme() { try { return localStorage.getItem("lm-theme") || "auto"; } catch (e) { return "auto"; } }
function applyTheme(t) {
  if (t === "dark" || t === "light") document.documentElement.dataset.theme = t;
  else delete document.documentElement.dataset.theme;
  try { t === "auto" ? localStorage.removeItem("lm-theme") : localStorage.setItem("lm-theme", t); } catch (e) { }
  const effective = t === "auto" ? (darkQuery.matches ? "dark" : "light") : t;
  document.querySelectorAll("[data-theme-set]").forEach((b) => b.classList.toggle("on", b.dataset.themeSet === t));
  $("#themeBtn").textContent = effective === "dark" ? "🌙" : "☀️";
  $('meta[name="theme-color"]').content = effective === "dark" ? "#161922" : "#ffffff";
}
document.querySelectorAll("[data-theme-set]").forEach((b) => b.onclick = () => applyTheme(b.dataset.themeSet));
// en el movil el boton alterna entre oscuro y claro
$("#themeBtn").onclick = () => { const cur = document.documentElement.dataset.theme || (darkQuery.matches ? "dark" : "light"); applyTheme(cur === "dark" ? "light" : "dark"); };
darkQuery.addEventListener?.("change", () => { if (getTheme() === "auto") applyTheme("auto"); });
applyTheme(getTheme());

// ============================================================ router
async function route() {
  const h = location.hash.slice(1) || "/";
  const [path, qs] = h.split("?");
  const name = path.replace(/^\//, "") || "home";
  const q = Object.fromEntries(new URLSearchParams(qs || ""));
  document.querySelectorAll("[data-nav]").forEach((a) => a.classList.toggle("active", a.dataset.nav === name || (name === "artist" && a.dataset.nav === "artists") || (name === "album" && a.dataset.nav === "albums") || (name === "genre" && a.dataset.nav === "genres") || (name === "playlist" && a.dataset.nav === "playlists")));
  $("#side").classList.remove("open");
  const v = views[name] || views.home;
  main.innerHTML = `<div class="empty">Cargando…</div>`;
  try { await v(q); } catch (e) { if (e.message !== "auth") main.innerHTML = `<div class="empty err">Error: ${esc(e.message)}</div>`; }
  main.scrollTop = 0;
}
window.addEventListener("hashchange", route);
$("#searchForm").onsubmit = (e) => { e.preventDefault(); const q = $("#searchBox").value.trim(); if (q) location.hash = `#/search?q=${enc(q)}`; };
$("#menuBtn").onclick = () => $("#side").classList.toggle("open");

// ============================================================ login
function showLogin() { $("#login").classList.remove("hidden"); $("#loginPw").focus(); }
$("#loginForm").onsubmit = async (e) => {
  e.preventDefault();
  const r = await fetch("/api/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ password: $("#loginPw").value }) });
  if (r.ok) { $("#login").classList.add("hidden"); await loadFavs(); route(); pollScan(); } else $("#loginErr").textContent = "Contraseña incorrecta";
};

(async function start() {
  const a = await (await fetch("/api/auth")).json();
  if (a.required && !a.ok) return showLogin();
  await loadFavs(); route(); pollScan();
})();
