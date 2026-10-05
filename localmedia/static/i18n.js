"use strict";
// Traducciones de la web. La clave es el texto en español; cada idioma tiene su archivo en
// /static/i18n/<codigo>.js que rellena I18N.<codigo>. Si falta una frase, se ve en español.
const I18N = {};
const LANGS = [
  ["es", "Español"], ["en", "English"], ["pt", "Português"], ["fr", "Français"],
  ["de", "Deutsch"], ["it", "Italiano"], ["pl", "Polski"], ["ru", "Русский"],
  ["ko", "한국어"], ["ja", "日本語"],
];
let LANG = (() => {
  try {  // ?lang=xx en la direccion manda (enlaces directos y capturas)
    const q = new URLSearchParams(location.search).get("lang");
    if (q && LANGS.some(([c]) => c === q)) { localStorage.setItem("lm-lang", q); return q; }
  } catch (e) { }
  try {
    const saved = localStorage.getItem("lm-lang");
    if (saved && LANGS.some(([c]) => c === saved)) return saved;
  } catch (e) { }
  const nav = (navigator.language || "es").slice(0, 2).toLowerCase();
  return LANGS.some(([c]) => c === nav) ? nav : "es";
})();
document.documentElement.lang = LANG;

function t(s, vars) {
  let out = (LANG !== "es" && I18N[LANG] && I18N[LANG][s]) || s;
  if (vars) out = out.replace(/\{(\w+)\}/g, (m, k) => (k in vars ? vars[k] : m));
  return out;
}

// textos que manda el servidor (fases del escaneo, pasos de "Conectar con Amazon"...)
const SERVER_PATTERNS = [
  [/^Subiendo el modelo de voz con tu biblioteca \((.+)\)…$/, "Subiendo el modelo de voz con tu biblioteca ({x})…"],
  [/^Amazon está preparando el modelo de voz \((.+)\)\. Tarda 1–2 minutos…$/, "Amazon está preparando el modelo de voz ({x}). Tarda 1–2 minutos…"],
  [/^La dirección del túnel ha cambiado: actualizando la skill a (.+)…$/, "La dirección del túnel ha cambiado: actualizando la skill a {x}…"],
  [/^UPnP: (.+)$/, "UPnP: {x}"],
  [/^No se puede acceder: (.+)$/, "No se puede acceder: {x}"],
  [/^Responde, pero no es (?:Local Media|PiMedia): (.+)$/, "Responde, pero no es Local Media: {x}"],
];
function ts(s) {
  if (!s || LANG === "es") return s;
  if (I18N[LANG] && I18N[LANG][s]) return I18N[LANG][s];
  for (const [re, key] of SERVER_PATTERNS) {
    const m = s.match(re);
    if (m) return t(key, { x: m[1] });
  }
  return s;
}

// elementos fijos del HTML: data-i18n (texto), data-i18n-ph (placeholder),
// data-i18n-title (title y aria-label)
function applyI18nDom(root = document) {
  root.querySelectorAll("[data-i18n]").forEach((el) => {
    el.dataset.i18nSrc = el.dataset.i18nSrc || el.dataset.i18n;
    el.textContent = t(el.dataset.i18nSrc);
  });
  root.querySelectorAll("[data-i18n-ph]").forEach((el) => { el.placeholder = t(el.dataset.i18nPh); });
  root.querySelectorAll("[data-i18n-title]").forEach((el) => {
    el.title = t(el.dataset.i18nTitle);
    if (el.hasAttribute("aria-label")) el.setAttribute("aria-label", t(el.dataset.i18nTitle));
  });
  document.documentElement.lang = LANG;
}
