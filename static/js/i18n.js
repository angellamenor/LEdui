/*
 * i18n mínimo para LEdui (sin dependencias).
 *
 * - Traducciones en /static/i18n/<idioma>.json
 * - En el HTML: data-i18n="clave"               -> textContent
 *               data-i18n-placeholder="clave"   -> placeholder
 *               data-i18n-title / -aria-label   -> atributos
 * - En JS: I18n.t('clave', {variable: valor})
 * - El idioma elegido se recuerda en localStorage ('ledui_lang').
 */
(function (global) {
  const SUPPORTED = ['es', 'en'];
  const STORAGE_KEY = 'ledui_lang';
  const LOCALES = { es: 'es-ES', en: 'en-GB' };
  const cache = {};
  const listeners = [];
  let current = 'es';
  let dict = {};

  function storageGet() {
    try { return localStorage.getItem(STORAGE_KEY); } catch (_) { return null; }
  }
  function storageSet(v) {
    try { localStorage.setItem(STORAGE_KEY, v); } catch (_) { /* modo privado */ }
  }

  function detect(defaultLang) {
    const saved = storageGet();
    if (SUPPORTED.includes(saved)) return saved;
    const nav = (navigator.language || '').slice(0, 2).toLowerCase();
    if (SUPPORTED.includes(nav)) return nav;
    return SUPPORTED.includes(defaultLang) ? defaultLang : 'es';
  }

  async function load(lang) {
    if (!cache[lang]) {
      const res = await fetch(`/static/i18n/${lang}.json`, { cache: 'no-cache' });
      if (!res.ok) throw new Error(`No se pudo cargar el idioma ${lang}`);
      cache[lang] = await res.json();
    }
    return cache[lang];
  }

  function t(key, params) {
    let text = (dict && dict[key]) || (cache.es && cache.es[key]) || key;
    if (params) {
      Object.keys(params).forEach(k => {
        text = text.split(`{${k}}`).join(String(params[k]));
      });
    }
    return text;
  }

  function apply(root) {
    const scope = root || document;
    scope.querySelectorAll('[data-i18n]').forEach(el => { el.textContent = t(el.dataset.i18n); });
    scope.querySelectorAll('[data-i18n-placeholder]').forEach(el => { el.placeholder = t(el.dataset.i18nPlaceholder); });
    scope.querySelectorAll('[data-i18n-title]').forEach(el => { el.title = t(el.dataset.i18nTitle); });
    scope.querySelectorAll('[data-i18n-aria-label]').forEach(el => { el.setAttribute('aria-label', t(el.dataset.i18nAriaLabel)); });
    document.documentElement.lang = current;
    document.title = t('app.title');
  }

  async function setLanguage(lang) {
    if (!SUPPORTED.includes(lang)) lang = 'es';
    if (!cache.es) await load('es'); // respaldo para claves que falten
    dict = await load(lang);
    current = lang;
    storageSet(lang);
    apply();
    listeners.forEach(fn => { try { fn(lang); } catch (e) { console.error(e); } });
  }

  function formatDate(value, withTime = true) {
    if (!value) return '-';
    const opts = { year: 'numeric', month: 'short', day: 'numeric' };
    if (withTime) Object.assign(opts, { hour: '2-digit', minute: '2-digit' });
    return new Date(value).toLocaleString(LOCALES[current], opts);
  }

  function formatNumber(n) {
    return Number(n || 0).toLocaleString(LOCALES[current]);
  }

  global.I18n = {
    SUPPORTED,
    t,
    apply,
    detect,
    setLanguage,
    formatDate,
    formatNumber,
    get lang() { return current; },
    onChange(fn) { listeners.push(fn); },
  };
})(window);
