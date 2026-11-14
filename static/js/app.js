/*
 * LEdui frontend logic.
 * Depends on i18n.js (window.I18n). No frameworks.
 *
 * View model: each transformation is a "vm" object with three parts
 * (texto, pictos, imagenes), each with a status:
 *   pending · loading · ok · error · none · skipped
 * Cards are re-rendered from the vm whenever something changes,
 * which lets the user watch the generation "live".
 */
(function () {
  'use strict';

  // The interface is served by the API itself, so the same origin is used.
  // Only when the HTML is opened as a local file does it point to the local server.
  const API_URL = window.location.protocol === 'file:' ? 'http://localhost:8000' : window.location.origin;

  // Default client ID; the server can override it through /config/public
  const DEFAULT_GOOGLE_CLIENT_ID = '1016751986529-b87941fcfc310qut1am83t7fe5b0rvcl.apps.googleusercontent.com';
  const ARASAAC_IMG = 'https://api.arasaac.org/api/pictograms/';
  const MAX_CHARS = 15000;
  const OUTPUT_LANG_KEY = 'ledui_output_lang';

  const state = {
    config: { requiere_clave: true, google_client_id: null },
    configLoaded: false,
    accessToken: null,
    currentUser: null,
    accessKey: '',
    accessKeyValid: false,
    googleReady: false,
    googleInitialised: false,
    activeTab: 'mine',
    mine: [],              // vms of "My transformations", most recent first
    mineLoaded: false,
    admin: new Map(),      // vms opened from the admin panel (by id)
    tmpCounter: 0,
  };

  const $ = (id) => document.getElementById(id);
  const t = (k, p) => I18n.t(k, p);

  // ================================================================ utilities

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text == null ? '' : String(text);
    return div.innerHTML;
  }

  /** Keep only the tags the model produces, without attributes (prevents XSS). */
  const ALLOWED_TAGS = new Set(['H1', 'H2', 'H3', 'H4', 'P', 'OL', 'UL', 'LI', 'STRONG', 'B', 'EM', 'I', 'BR']);
  function sanitizeHtml(html) {
    const doc = new DOMParser().parseFromString(`<div>${html || ''}</div>`, 'text/html');
    const walk = (node) => {
      Array.from(node.childNodes).forEach(child => {
        if (child.nodeType === Node.ELEMENT_NODE) {
          if (!ALLOWED_TAGS.has(child.tagName)) {
            if (['SCRIPT', 'STYLE', 'IFRAME', 'OBJECT'].includes(child.tagName)) { child.remove(); return; }
            walk(child);
            child.replaceWith(...child.childNodes);
            return;
          }
          Array.from(child.attributes).forEach(a => child.removeAttribute(a.name));
          walk(child);
        } else if (child.nodeType !== Node.TEXT_NODE) {
          child.remove();
        }
      });
    };
    const root = doc.body.firstChild;
    walk(root);
    return root.innerHTML;
  }

  /** **bold** and paragraphs separated by blank lines -> safe HTML. */
  function markdownToHtml(text) {
    if (!text) return '';
    return escapeHtml(text)
      .split(/\n\s*\n/)
      .map(p => p.trim())
      .filter(Boolean)
      .map(p => `<p style="margin-bottom: 10px;">${p.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>')}</p>`)
      .join('');
  }

  function titleFromHtml(html) {
    const m = /<h1[^>]*>([\s\S]*?)<\/h1>/i.exec(html || '');
    if (!m) return null;
    const div = document.createElement('div');
    div.innerHTML = m[1];
    return div.textContent.trim() || null;
  }

  function truncate(text, n) {
    const s = (text || '').replace(/\s+/g, ' ').trim();
    return s.length > n ? s.slice(0, n) + '…' : s;
  }

  function formatDuration(ms) {
    if (!ms) return '-';
    return ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
  }

  function levelLabel(value) {
    if (!value) return t('common.na');
    const key = `levels.${String(value).toLowerCase()}`;
    const label = t(key);
    return label === key ? value : label;
  }

  const langLabel = (code) => (code || 'es').toUpperCase();

  function statusBadge(ok) {
    return ok
      ? `<span class="badge badge-success">${t('badge.success')}</span>`
      : `<span class="badge badge-error">${t('badge.error')}</span>`;
  }

  function messageRow(tbody, cols, html, color) {
    tbody.innerHTML = `<tr><td colspan="${cols}" style="text-align: center; padding: 40px;${color ? ` color: ${color};` : ''}">${html}</td></tr>`;
  }

  const spinnerBlock = (key) => `<div style="text-align: center; padding: 40px;"><div class="spinner"></div><p>${escapeHtml(t(key))}</p></div>`;

  const errorTimers = {};
  function showError(message, elementId = 'error') {
    const el = $(elementId);
    el.textContent = '❌ ' + message;
    el.classList.add('active');
    clearTimeout(errorTimers[elementId]);
    errorTimers[elementId] = setTimeout(() => el.classList.remove('active'), 7000);
  }

  // ================================================================ API

  class ApiError extends Error {
    constructor(message, status) { super(message); this.status = status; }
  }

  async function api(path, { method = 'GET', body, timeout = 60000, raw = false } = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    const headers = { 'Accept-Language': I18n.lang };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (state.accessToken) headers['Authorization'] = `Bearer ${state.accessToken}`;
    try {
      const res = await fetch(`${API_URL}${path}`, {
        method, headers, signal: controller.signal,
        body: body !== undefined ? JSON.stringify(body) : undefined,
      });
      if (res.status === 401 && state.accessToken) {
        logout();
        throw new ApiError(t('errors.token_expired'), 401);
      }
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new ApiError(typeof data.detail === 'string' ? data.detail : `HTTP ${res.status}`, res.status);
      }
      return raw ? res : res.json();
    } catch (err) {
      if (err.name === 'AbortError') throw new ApiError(t('errors.timeout'), 0);
      throw err;
    } finally {
      clearTimeout(timer);
    }
  }

  async function fetchImageAsDataUrl(path) {
    try {
      const res = await api(path, { raw: true });
      const blob = await res.blob();
      return await new Promise(resolve => {
        const reader = new FileReader();
        reader.onloadend = () => resolve(reader.result);
        reader.readAsDataURL(blob);
      });
    } catch (err) {
      console.warn('No se pudo cargar la imagen', path, err);
      return null;
    }
  }

  async function downloadFile(path, fallbackName) {
    try {
      const res = await api(path, { raw: true });
      const blob = await res.blob();
      const match = (res.headers.get('Content-Disposition') || '').match(/filename="?([^"]+)"?/);
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = match ? match[1] : fallbackName;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      showError(t('errors.download', { msg: err.message }));
    }
  }

  // ================================================================ view model

  function newVm(fields) {
    return Object.assign({
      key: null, id: null, scope: 'user', open: false, activeTab: 'texto',
      loaded: false, loading: false, loadError: null, running: false, step: null, justAdded: false,
      titulo: null, enunciado_original: '', nivel: null, idioma: null, created_at: null,
      exito: null, error_mensaje: null, user_email: null, user_id: null, prompt_version: null,
      tokens: 0, duracion_ms: null,
      texto: { status: 'pending', html: '', notes: '' },
      pictos: { status: 'pending', composite: null, items: [], text: '', error: null },
      imagenes: { status: 'pending', items: [], error: null },
    }, fields);
  }

  /** List summary (no detail yet). */
  function vmFromSummary(s, scope) {
    return newVm({
      key: `${scope}-${s.id}`, id: s.id, scope,
      titulo: s.titulo, enunciado_original: s.enunciado_original, nivel: s.nivel, idioma: s.idioma,
      created_at: s.created_at, exito: s.exito, user_email: s.user_email, user_id: s.user_id,
      prompt_version: s.prompt_version, duracion_ms: s.duracion_ms,
      tokens: (s.tokens_entrada || 0) + (s.tokens_salida || 0),
      hasPictos: s.tiene_pictogramas, numImagenes: s.num_imagenes_contexto,
    });
  }

  function pictoItemsFrom(list) {
    return (list || []).filter(p => p.exito).map(p => ({
      label: p.etiqueta || p.accion_en_ingles || p.accion_simplificada || p.keyword || '',
      text: p.explicacion_alumno || '',
      thumb: p.imagen_base64 ? `data:image/png;base64,${p.imagen_base64}` : (p.id ? `${ARASAAC_IMG}${encodeURIComponent(p.id)}` : null),
    }));
  }

  /** Fill the vm with the API detail (and download the images with authentication). */
  async function loadDetail(vm) {
    vm.loading = true;
    vm.loadError = null;
    render(vm);
    try {
      const d = await api(vm.scope === 'admin' ? `/admin/transformaciones/${vm.id}` : `/mi-historial/${vm.id}`);
      Object.assign(vm, {
        titulo: d.titulo, enunciado_original: d.enunciado_original, nivel: d.nivel, idioma: d.idioma,
        created_at: d.created_at, exito: d.exito, error_mensaje: d.error_mensaje, user_email: d.user_email,
        prompt_version: d.prompt_version, duracion_ms: d.duracion_ms,
        tokens: (d.tokens_entrada || 0) + (d.tokens_salida || 0),
      });

      vm.texto = d.enunciado_adaptado
        ? { status: 'ok', html: d.enunciado_adaptado, notes: d.indicaciones_docentes || '' }
        : { status: 'error', html: '', notes: '', error: d.error_mensaje };

      const p = d.pictogramas;
      if (!p) {
        vm.pictos = { status: d.enunciado_adaptado ? 'none' : 'skipped', items: [] };
      } else if (!p.exito) {
        vm.pictos = { status: 'error', items: [], error: p.error_mensaje };
      } else {
        vm.pictos = {
          status: 'ok',
          composite: p.tiene_imagen ? await fetchImageAsDataUrl(`/mi-historial/pictogramas/${p.id}/imagen`) : null,
          items: pictoItemsFrom(p.pasos),
          text: p.explicacion_habilidades || '',
        };
      }

      const imgs = d.imagenes_contexto || [];
      const okImgs = imgs.filter(i => i.tiene_imagen);
      if (okImgs.length) {
        const items = [];
        for (const img of okImgs) {
          items.push({ src: await fetchImageAsDataUrl(`/mi-historial/imagenes/${img.id}/imagen`), text: img.texto_explicativo });
        }
        vm.imagenes = { status: 'ok', items };
      } else if (imgs.some(i => i.exito === false)) {
        vm.imagenes = { status: 'error', items: [], error: imgs.find(i => i.error_mensaje)?.error_mensaje };
      } else {
        vm.imagenes = { status: d.enunciado_adaptado ? 'none' : 'skipped', items: [] };
      }
      vm.loaded = true;
    } catch (err) {
      vm.loadError = err.message;
    } finally {
      vm.loading = false;
      render(vm);
    }
  }

  function overallStatus(vm) {
    if (vm.running) return 'running';
    if (vm.exito === false) return 'error';
    if (vm.loaded && [vm.pictos.status, vm.imagenes.status].includes('error')) return 'partial';
    return 'ok';
  }

  // ================================================================ detail rendering

  const STATUS_DOT = {
    ok: '<span class="dot dot-ok" aria-hidden="true">✓</span>',
    error: '<span class="dot dot-error" aria-hidden="true">!</span>',
    loading: '<span class="dot dot-loading" aria-hidden="true"></span>',
    pending: '<span class="dot dot-pending" aria-hidden="true">·</span>',
    none: '<span class="dot dot-none" aria-hidden="true">–</span>',
    skipped: '<span class="dot dot-none" aria-hidden="true">–</span>',
  };

  function notice(key, params, kind) {
    const spinner = kind === 'loading' ? '<div class="spinner"></div>' : '';
    return `<div class="notice ${kind === 'error' ? 'notice-error' : ''}">${spinner}<div>${escapeHtml(t(key, params))}</div></div>`;
  }

  function partStateNotice(part, loadingKey, emptyKey) {
    switch (part.status) {
      case 'loading': return notice(loadingKey, null, 'loading');
      case 'pending': return notice('detail.waiting');
      case 'skipped': return notice('detail.skipped');
      case 'none': return notice('detail.not_generated');
      case 'error': return notice('detail.error', { msg: part.error || t('common.na') }, 'error');
      default: return emptyKey ? notice(emptyKey) : '';
    }
  }

  function renderTextoPanel(vm) {
    const original = vm.enunciado_original
      ? `<details class="original-box"><summary>${escapeHtml(t('detail.original'))}</summary><div>${escapeHtml(vm.enunciado_original)}</div></details>`
      : '';
    if (vm.texto.status === 'loading') {
      return `${original}<div class="skeleton"><span></span><span></span><span></span><span></span><span></span>
              <div class="skeleton-label">⏳ ${escapeHtml(t('detail.loading_text'))}</div></div>`;
    }
    if (vm.texto.status !== 'ok') {
      return original + notice('detail.error', { msg: vm.texto.error || vm.error_mensaje || t('common.na') }, 'error');
    }
    const notes = vm.texto.notes
      ? `<div class="teacher-box"><h4>${escapeHtml(t('detail.teacher'))}</h4>
         <p class="teacher-sub">${escapeHtml(t('detail.teacher_sub'))}</p>${markdownToHtml(vm.texto.notes)}</div>` : '';
    return `${original}<div class="result-content">${sanitizeHtml(vm.texto.html)}</div>${notes}`;
  }

  function renderPictosPanel(vm) {
    const p = vm.pictos;
    if (p.status !== 'ok') return partStateNotice(p, 'detail.loading_pictos');
    if (!p.items.length && !p.composite) {
      return p.text ? `<div class="result-content" style="white-space: pre-wrap;">${escapeHtml(p.text)}</div>` : notice('detail.no_pictos');
    }
    const composite = p.composite ? `<img class="pictogram-image" src="${p.composite}" alt="">` : '';
    const items = p.items.length
      ? p.items.map(i => `
        <div class="habilidad-item"><div style="display: flex; align-items: start; gap: 16px;">
          ${i.thumb ? `<img src="${i.thumb}" alt="${escapeHtml(i.label)}" loading="lazy" style="width: 72px; height: 72px; object-fit: contain; flex-shrink: 0; background: #f3f4f6; border-radius: 8px; padding: 6px;">` : ''}
          <div style="flex: 1;"><div class="habilidad-nombre">${escapeHtml(i.label)}</div>
          <div class="habilidad-aplicacion">${escapeHtml(i.text || t('detail.default_skill'))}</div></div>
        </div></div>`).join('')
      : (p.text ? `<div class="result-content" style="white-space: pre-wrap;">${escapeHtml(p.text)}</div>` : '');
    return `${composite}<h4 style="margin: 18px 0 12px; font-size: 15px;">${escapeHtml(t('detail.where_skill'))}</h4>
            <div class="habilidades-list">${items}</div>`;
  }

  function renderImagenesPanel(vm) {
    const im = vm.imagenes;
    if (im.status !== 'ok') return partStateNotice(im, 'detail.loading_images');
    if (!im.items.length) return notice('detail.no_images');
    return `<div class="context-images">${im.items.map((img, i) => `
      <div class="context-image-item">
        ${img.src ? `<img src="${img.src}" alt="${escapeHtml(t('detail.image', { n: i + 1 }))}" class="context-image">` : ''}
        ${img.text ? `<div class="context-explanation"><strong>${escapeHtml(t('detail.why_image'))}</strong>${escapeHtml(img.text)}</div>` : ''}
      </div>`).join('')}</div>`;
  }

  function renderDetail(vm) {
    if (vm.loadError) return notice('detail.load_error', { msg: vm.loadError }, 'error');
    if (!vm.loaded && !vm.running) return notice('detail.loading', null, 'loading');

    const chips = [];
    if (vm.id) chips.push(`<span class="chip">#${vm.id}</span>`);
    if (vm.scope === 'admin' && vm.user_email) chips.push(`<span class="chip">👤 ${escapeHtml(vm.user_email)}</span>`);
    if (vm.tokens) chips.push(`<span class="chip">${escapeHtml(t('detail.tokens', { n: I18n.formatNumber(vm.tokens) }))}</span>`);
    if (vm.duracion_ms) chips.push(`<span class="chip">⏱ ${formatDuration(vm.duracion_ms)}</span>`);
    if (vm.scope === 'admin' && vm.prompt_version) chips.push(`<span class="chip" title="prompt_version">🧪 ${escapeHtml(vm.prompt_version)}</span>`);
    const canDownload = vm.id && !vm.running && vm.texto.status === 'ok';
    const download = canDownload
      ? `<button type="button" class="btn-download" data-download="${vm.id}" data-scope="${vm.scope}">${escapeHtml(t('detail.download'))}</button>` : '';

    const tabs = [
      ['texto', 'dtabs.text', vm.texto.status],
      ['pictos', 'dtabs.pictos', vm.pictos.status],
      ['imagenes', 'dtabs.images', vm.imagenes.status],
    ].map(([name, key, st]) => `
      <button type="button" class="dtab" role="tab" aria-selected="${vm.activeTab === name}"
              data-dtab="${name}" data-key="${vm.key}">${STATUS_DOT[st] || ''}${escapeHtml(t(key))}</button>`).join('');

    const panel = vm.activeTab === 'pictos' ? renderPictosPanel(vm)
      : vm.activeTab === 'imagenes' ? renderImagenesPanel(vm)
      : renderTextoPanel(vm);

    return `<div class="detail-toolbar">${chips.join('')}${download}</div>
            <div class="dtabs" role="tablist" aria-label="${escapeHtml(t('dtabs.label'))}">${tabs}</div>
            <div class="dpanel" role="tabpanel">${panel}</div>`;
  }

  // ================================================================ card rendering

  function statusChip(vm) {
    switch (overallStatus(vm)) {
      case 'running': return `<span class="chip chip-running"><span class="dot dot-loading"></span>${escapeHtml(t(vm.step || 'status.step1'))}</span>`;
      case 'error': return `<span class="chip chip-error">${escapeHtml(t('status.error'))}</span>`;
      case 'partial': return `<span class="chip chip-warn">${escapeHtml(t('status.partial'))}</span>`;
      default: return `<span class="chip chip-ok">${escapeHtml(t('status.ok'))}</span>`;
    }
  }

  function cardHtml(vm) {
    const title = vm.titulo || (vm.id ? t('mine.untitled', { id: vm.id }) : t('mine.new_untitled'));
    const classes = ['trans-card', vm.open && 'open', vm.running && 'running', vm.justAdded && 'just-added'].filter(Boolean).join(' ');
    return `<article class="${classes}" data-card="${vm.key}">
      <button type="button" class="trans-card-header" data-toggle="${vm.key}" aria-expanded="${vm.open}">
        <div class="trans-card-main">
          <div class="trans-title">${escapeHtml(title)}</div>
          <div class="trans-sub">${escapeHtml(truncate(vm.enunciado_original, 140))}</div>
        </div>
        <div class="trans-meta">
          <span class="chip">${escapeHtml(levelLabel(vm.nivel))}</span>
          <span class="chip">${escapeHtml(langLabel(vm.idioma))}</span>
          <span class="chip">${escapeHtml(vm.created_at ? I18n.formatDate(vm.created_at) : '…')}</span>
          ${statusChip(vm)}
        </div>
        <span class="chevron" aria-hidden="true">▾</span>
      </button>
      ${vm.open ? `<div class="trans-body">${renderDetail(vm)}</div>` : ''}
    </article>`;
  }

  /** Re-render wherever the vm is shown (card or admin row). */
  function render(vm) {
    if (vm.scope === 'admin') {
      const cell = document.querySelector(`[data-admin-detail="${vm.id}"]`);
      if (cell) cell.innerHTML = renderDetail(vm);
      return;
    }
    const el = document.querySelector(`[data-card="${vm.key}"]`);
    if (el) {
      el.outerHTML = cardHtml(vm);
      vm.justAdded = false;
      updateMineCount();
    } else {
      renderMineList();
    }
  }

  function updateMineCount() {
    const n = state.mine.filter(vm => vm.id).length;
    $('mineCount').textContent = n === 1 ? t('mine.count_one') : t('mine.count_other', { n });
  }

  function renderMineList() {
    const list = $('transList');
    list.innerHTML = state.mine.map(cardHtml).join('');
    state.mine.forEach(vm => { vm.justAdded = false; });
    $('transEmpty').hidden = !(state.mineLoaded && state.mine.length === 0);
    updateMineCount();
  }

  async function loadMine() {
    $('transList').innerHTML = spinnerBlock('mine.loading');
    $('transEmpty').hidden = true;
    try {
      const data = await api('/mi-historial');
      const running = state.mine.filter(vm => vm.running);
      const runningIds = new Set(running.map(vm => vm.id).filter(Boolean));
      const previous = new Map(state.mine.map(vm => [vm.key, vm]));
      state.mine = running.concat(
        (data.transformaciones || [])
          .filter(s => !runningIds.has(s.id))
          .map(s => {
            const old = previous.get(`user-${s.id}`);
            return old && old.loaded ? old : vmFromSummary(s, 'user');
          })
      );
      state.mineLoaded = true;
      renderMineList();
    } catch (err) {
      $('transList').innerHTML = `<div class="notice notice-error">${escapeHtml(t('mine.error', { msg: err.message }))}<br><br>
        <button type="button" class="btn-secondary" data-action="reload-mine">${escapeHtml(t('mine.retry'))}</button></div>`;
    }
  }

  function findVm(key) {
    return state.mine.find(vm => vm.key === key)
      || Array.from(state.admin.values()).find(vm => vm.key === key);
  }

  function toggleCard(key) {
    const vm = findVm(key);
    if (!vm) return;
    vm.open = !vm.open;
    if (vm.open) {
      state.mine.forEach(other => { if (other !== vm && other.open) { other.open = false; render(other); } });
    }
    render(vm);
    if (vm.open && !vm.loaded && !vm.loading && !vm.running) loadDetail(vm);
  }

  // ================================================================ new transformation

  /** Adaptation language: the last one chosen or, if none, the interface language. */
  function defaultOutputLang() {
    let saved = null;
    try { saved = localStorage.getItem(OUTPUT_LANG_KEY); } catch (_) { /* ignore */ }
    return I18n.SUPPORTED.includes(saved) ? saved : I18n.lang;
  }

  function openNewModal() {
    $('newError').classList.remove('active');
    $('idiomaSalida').value = defaultOutputLang();
    $('newModal').classList.add('active');
    updateCharCount();
    setTimeout(() => $('enunciado').focus(), 50);
  }

  function closeNewModal() {
    $('newModal').classList.remove('active');
  }

  function updateCharCount() {
    const len = $('enunciado').value.length;
    $('charCount').textContent = t('new.chars', { n: I18n.formatNumber(len) });
    // Examples are only offered while the box is empty: users pasting their own task never see them.
    $('examples').hidden = len > 0;
  }

  /** Example task statements (one per level), in the chosen adaptation language. */
  let examplesCache = null;
  async function loadExample(nivel) {
    try {
      if (!examplesCache) {
        const res = await fetch('/static/data/ejemplos.json');
        if (!res.ok) throw new Error(res.statusText);
        examplesCache = await res.json();
      }
    } catch (_) { return; }
    const lang = $('idiomaSalida').value;
    const text = (examplesCache[lang] || examplesCache.es || {})[nivel];
    if (!text) return;
    $('enunciado').value = text;
    $('nivel').value = nivel;
    updateCharCount();
    $('enunciado').focus();
  }

  function submitNew(e) {
    e.preventDefault();
    const enunciado = $('enunciado').value;
    const nivel = $('nivel').value;
    const idioma = $('idiomaSalida').value;
    if (!enunciado.trim()) return showError(t('errors.write_statement'), 'newError');
    if (enunciado.length > MAX_CHARS) return showError(t('errors.too_long'), 'newError');
    if (!nivel) return showError(t('errors.select_level'), 'newError');
    if (!state.accessToken) { closeNewModal(); return logout(); }

    try { localStorage.setItem(OUTPUT_LANG_KEY, idioma); } catch (_) { /* ignore */ }
    closeNewModal();
    $('enunciado').value = '';
    runTransformation(enunciado, nivel, idioma);
  }

  async function runTransformation(enunciado, nivel, idioma) {
    const vm = newVm({
      key: `tmp-${++state.tmpCounter}`, scope: 'user', open: true, running: true, justAdded: true,
      step: 'status.step1', enunciado_original: enunciado, nivel, idioma, created_at: new Date().toISOString(),
      texto: { status: 'loading', html: '', notes: '' },
    });
    state.mine.forEach(other => { other.open = false; });
    state.mine.unshift(vm);
    renderMineList();
    document.querySelector(`[data-card="${vm.key}"]`)?.scrollIntoView({ behavior: 'smooth', block: 'start' });

    const started = performance.now();
    let adapted;
    try {
      adapted = await api('/adaptar_enunciado_ledu', {
        method: 'POST', body: { enunciado, nivel, max_palabras: 350, idioma }, timeout: 120000,
      });
    } catch (err) {
      Object.assign(vm, { running: false, exito: false, error_mensaje: err.message, loaded: true });
      vm.texto = { status: 'error', error: err.message };
      vm.pictos = { status: 'skipped', items: [] };
      vm.imagenes = { status: 'skipped', items: [] };
      render(vm);
      loadStats();
      return;
    }

    // The text is ready: show it and request pictograms and images IN PARALLEL
    Object.assign(vm, {
      id: adapted.transformacion_id, exito: true, idioma: adapted.idioma,
      titulo: titleFromHtml(adapted.enunciado_adaptado), prompt_version: adapted.prompt_version,
      tokens: (adapted.tokens_entrada || 0) + (adapted.tokens_salida || 0), step: 'status.step2',
    });
    vm.texto = { status: 'ok', html: adapted.enunciado_adaptado, notes: adapted.indicaciones_docentes };
    vm.pictos = { status: 'loading', items: [] };
    vm.imagenes = { status: 'loading', items: [] };
    render(vm);

    const body = { enunciado: adapted.enunciado_adaptado, transformacion_id: vm.id, idioma: vm.idioma };
    const pictosJob = api('/generar_pictogramas', { method: 'POST', body, timeout: 120000 })
      .then(p => {
        vm.tokens += (p.tokens_analisis?.entrada || 0) + (p.tokens_analisis?.salida || 0);
        vm.pictos = {
          status: 'ok',
          composite: p.imagen_compuesta_base64 ? `data:image/png;base64,${p.imagen_compuesta_base64}` : null,
          items: pictoItemsFrom(p.pictogramas),
        };
      })
      .catch(err => { vm.pictos = { status: 'error', items: [], error: err.message }; })
      .finally(() => render(vm));

    const imagesJob = api('/generar_imagenes_contexto', { method: 'POST', body: { ...body, num_imagenes: 1 }, timeout: 180000 })
      .then(c => {
        vm.tokens += (c.tokens_analisis?.entrada || 0) + (c.tokens_analisis?.salida || 0);
        const ok = (c.imagenes || []).filter(i => i.exito && i.imagen_base64);
        const failed = (c.imagenes || []).find(i => !i.exito);
        vm.imagenes = ok.length
          ? { status: 'ok', items: ok.map(i => ({ src: `data:image/png;base64,${i.imagen_base64}`, text: i.justificacion })) }
          : { status: 'error', items: [], error: failed?.error || t('detail.no_images') };
      })
      .catch(err => { vm.imagenes = { status: 'error', items: [], error: err.message }; })
      .finally(() => render(vm));

    await Promise.allSettled([pictosJob, imagesJob]);
    Object.assign(vm, { running: false, loaded: true, step: null, duracion_ms: Math.round(performance.now() - started) });
    vm.key = `user-${vm.id}`;
    // The card had a temporary key: re-render the whole list
    renderMineList();
    loadStats();
  }

  // ================================================================ language

  function updateLangButtons(lang) {
    document.querySelectorAll('.lang-switch button').forEach(btn => {
      btn.setAttribute('aria-pressed', String(btn.dataset.lang === lang));
    });
  }

  function onLanguageChanged(lang) {
    updateLangButtons(lang);
    updateDemoVideo();
    $('authSubtitle').textContent = t(state.config.requiere_clave ? 'auth.subtitle' : 'auth.subtitle_nokey');
    refreshKeyHint();
    renderGoogleButton();
    updateCharCount();
    if (state.currentUser) {
      loadStats();
      if (state.mineLoaded) renderMineList();      // interface texts change; the content does not
      state.admin.forEach(render);
      if (state.activeTab === 'admin') { loadUsers(); loadTransformaciones(); }
    }
  }

  // ================================================================ sign-in

  function setGoogleEnabled(enabled) {
    const wrapper = $('googleSigninWrapper');
    wrapper.classList.toggle('disabled', !enabled);
    wrapper.classList.toggle('enabled', enabled);
  }

  function refreshKeyHint(status) {
    const hint = $('keyHint');
    const input = $('accessKey');
    const st = status || (state.accessKey === '' ? 'neutral' : state.accessKeyValid ? 'valid' : 'invalid');
    const keys = { neutral: 'auth.key_hint', valid: 'auth.key_ok', invalid: 'auth.key_bad', checking: 'auth.key_checking' };
    hint.className = `key-hint ${st === 'checking' ? 'neutral' : st}`;
    hint.textContent = t(keys[st]);
    input.classList.toggle('valid', st === 'valid');
    input.classList.toggle('invalid', st === 'invalid');
  }

  let keyTimer = null;
  function onAccessKeyInput(e) {
    state.accessKey = e.target.value;
    state.accessKeyValid = false;
    setGoogleEnabled(false);
    clearTimeout(keyTimer);
    if (!state.accessKey) { refreshKeyHint(); return; }
    refreshKeyHint('checking');
    keyTimer = setTimeout(async () => {
      try {
        const res = await api('/auth/check-key', { method: 'POST', body: { access_key: state.accessKey }, timeout: 10000 });
        state.accessKeyValid = !!res.valida;
      } catch (_) {
        state.accessKeyValid = false;
      }
      refreshKeyHint();
      setGoogleEnabled(state.accessKeyValid);
    }, 400);
  }

  function togglePasswordVisibility() {
    const input = $('accessKey');
    const showing = input.type === 'text';
    input.type = showing ? 'password' : 'text';
    $('togglePassword').textContent = showing ? '👁️' : '🙈';
  }

  // ================================================================ Google

  function initGoogle() {
    if (!state.configLoaded || !state.googleReady || state.googleInitialised || !window.google?.accounts?.id) return;
    google.accounts.id.initialize({
      client_id: state.config.google_client_id || DEFAULT_GOOGLE_CLIENT_ID,
      callback: handleCredentialResponse,
    });
    state.googleInitialised = true;
    renderGoogleButton();
  }

  function renderGoogleButton() {
    if (!state.googleInitialised) return;
    const el = $('googleButton');
    el.innerHTML = '';
    google.accounts.id.renderButton(el, {
      type: 'standard', size: 'large', theme: 'outline', text: 'signin_with',
      shape: 'rectangular', logo_alignment: 'left', width: 300, locale: I18n.lang,
    });
  }

  async function handleCredentialResponse(response) {
    if (state.config.requiere_clave && !state.accessKeyValid) {
      showError(t('auth.need_key'), 'authError');
      return;
    }
    try {
      const data = await api('/auth/google', {
        method: 'POST',
        body: { token: response.credential, access_key: state.accessKey || null },
        timeout: 15000,
      });
      state.accessToken = data.access_token;
      state.currentUser = data.user;
      saveSession();
      showApp();
    } catch (err) {
      showError(t('auth.error', { msg: err.message }), 'authError');
    }
  }

  // ================================================================ session

  function saveSession() {
    try {
      localStorage.setItem('access_token', state.accessToken);
      localStorage.setItem('current_user', JSON.stringify(state.currentUser));
    } catch (_) { /* storage not available */ }
  }

  function clearSession() {
    try {
      ['access_token', 'current_user', 'is_admin_mode'].forEach(k => localStorage.removeItem(k));
    } catch (_) { /* ignore */ }
  }

  async function restoreSession() {
    let token, user;
    try {
      token = localStorage.getItem('access_token');
      user = JSON.parse(localStorage.getItem('current_user') || 'null');
    } catch (_) { return; }
    if (!token || !user) return;
    state.accessToken = token;
    state.currentUser = user;
    try {
      state.currentUser = await api('/auth/me', { timeout: 10000 });
      saveSession();
      showApp();
    } catch (err) {
      console.warn('Sesión no válida:', err.message);
      state.accessToken = null;
      state.currentUser = null;
      clearSession();
    }
  }

  function showApp() {
    const user = state.currentUser;
    $('authSection').hidden = true;
    $('userInfo').classList.add('active');
    $('appSection').classList.add('active');
    $('userName').textContent = user.name || '';
    $('userEmail').textContent = user.email || '';
    $('userAvatar').src = user.picture || '';
    $('userAvatar').alt = user.name || '';
    $('mainTabs').hidden = !user.is_admin;
    state.mine = [];
    state.mineLoaded = false;
    switchTab('mine');
    loadMine();
    loadStats();
  }

  function logout() {
    Object.assign(state, {
      accessToken: null, currentUser: null, accessKey: '', accessKeyValid: false,
      mine: [], mineLoaded: false, admin: new Map(),
    });
    clearSession();

    $('appSection').classList.remove('active');
    $('userInfo').classList.remove('active');
    $('authSection').hidden = false;
    showInfoTab('acceder');
    $('transList').innerHTML = '';
    closeNewModal();

    $('accessKey').value = '';
    refreshKeyHint();
    setGoogleEnabled(!state.config.requiere_clave);
    if (window.google?.accounts?.id) google.accounts.id.disableAutoSelect();
  }

  async function loadStats() {
    try {
      const data = await api('/auth/stats');
      $('statTotal').textContent = I18n.formatNumber(data.total_transformaciones);
      $('statTokens').textContent = I18n.formatNumber(data.tokens_usados);
    } catch (err) {
      console.warn('Error cargando estadísticas:', err.message);
    }
  }

  function switchTab(name) {
    state.activeTab = name;
    document.querySelectorAll('#mainTabs .tab-button').forEach(btn => {
      const active = btn.dataset.tab === name;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-selected', String(active));
    });
    $('tabMine').classList.toggle('active', name === 'mine');
    $('tabAdmin').classList.toggle('active', name === 'admin');
    if (name === 'admin') { loadUsers(); loadTransformaciones(); }
  }

  // ================================================================ admin

  async function loadUsers() {
    const tbody = $('usuariosTableBody');
    messageRow(tbody, 6, `<div class="spinner"></div><p>${escapeHtml(t('admin.loading_users'))}</p>`);
    try {
      const data = await api('/admin/users');
      if (!data.users?.length) return messageRow(tbody, 6, escapeHtml(t('admin.no_users')), '#6b7280');
      tbody.innerHTML = data.users.map(u => `<tr>
        <td><strong>#${u.id}</strong></td>
        <td>${escapeHtml(u.email)}</td>
        <td>${escapeHtml(u.name || '-')}</td>
        <td>${u.is_admin ? `<span class="badge badge-admin">${t('badge.admin')}</span>` : `<span class="badge badge-user">${t('badge.user')}</span>`}</td>
        <td>${escapeHtml(I18n.formatDate(u.created_at))}</td>
        <td><strong>${u.total_transformaciones || 0}</strong></td>
      </tr>`).join('');
    } catch (err) {
      messageRow(tbody, 6, escapeHtml(t('admin.error_users', { msg: err.message })), '#ef4444');
    }
  }

  async function loadTransformaciones() {
    const tbody = $('transformacionesTableBody');
    messageRow(tbody, 8, `<div class="spinner"></div><p>${escapeHtml(t('admin.loading_trans'))}</p>`);
    try {
      const data = await api('/admin/transformaciones');
      if (!data.transformaciones?.length) return messageRow(tbody, 8, escapeHtml(t('admin.no_trans')), '#6b7280');
      tbody.innerHTML = data.transformaciones.map(tr => {
        const open = state.admin.has(tr.id);
        return `<tr>
          <td>#${tr.id}</td>
          <td title="${escapeHtml(tr.user_email || '')}">${escapeHtml(tr.user_email || '#' + tr.user_id)}</td>
          <td>${escapeHtml(truncate(tr.titulo || tr.enunciado_original, 60))}</td>
          <td>${escapeHtml(levelLabel(tr.nivel))}</td>
          <td>${escapeHtml(langLabel(tr.idioma))}</td>
          <td>${formatDuration(tr.duracion_ms)}</td>
          <td>${statusBadge(tr.exito)}</td>
          <td><button type="button" class="btn-view" data-admin-view="${tr.id}">${escapeHtml(t(open ? 'common.hide' : 'common.view'))}</button></td>
        </tr>${open ? `<tr class="admin-detail-row"><td colspan="8" data-admin-detail="${tr.id}"></td></tr>` : ''}`;
      }).join('');
      state.admin.forEach(render);
    } catch (err) {
      messageRow(tbody, 8, escapeHtml(t('admin.error_trans', { msg: err.message })), '#ef4444');
    }
  }

  function toggleAdminDetail(id, button) {
    id = Number(id);
    const row = button.closest('tr');
    if (state.admin.has(id)) {
      state.admin.delete(id);
      row.nextElementSibling?.classList.contains('admin-detail-row') && row.nextElementSibling.remove();
      button.textContent = t('common.view');
      return;
    }
    const vm = newVm({ key: `admin-${id}`, id, scope: 'admin', open: true });
    state.admin.set(id, vm);
    row.insertAdjacentHTML('afterend', `<tr class="admin-detail-row"><td colspan="8" data-admin-detail="${id}"></td></tr>`);
    button.textContent = t('common.hide');
    loadDetail(vm);
  }

  // ================================================================ sign-in box tabs

  // YouTube demo video according to the interface language
  const DEMO_VIDEOS = { es: 'veY3e7kjzFA', en: 'othEd50vC2I' };
  let activeInfoTab = 'acceder';

  function updateDemoVideo() {
    const frame = $('demoVideo');
    if (!frame) return;
    if (activeInfoTab !== 'video') {
      // Leaving the tab empties the iframe so the video stops playing
      if (frame.getAttribute('src')) frame.removeAttribute('src');
      return;
    }
    const id = DEMO_VIDEOS[I18n.lang] || DEMO_VIDEOS.es;
    const url = `https://www.youtube-nocookie.com/embed/${id}?rel=0`;
    if (frame.getAttribute('src') !== url) frame.setAttribute('src', url);
  }

  function showInfoTab(name) {
    activeInfoTab = name;
    document.querySelectorAll('[data-info-tab]').forEach(btn => btn.setAttribute('aria-selected', String(btn.dataset.infoTab === name)));
    document.querySelectorAll('[data-info-panel]').forEach(panel => { panel.hidden = panel.dataset.infoPanel !== name; });
    updateDemoVideo();
  }

  // ================================================================ startup

  function bindEvents() {
    document.querySelectorAll('.lang-switch button').forEach(btn => {
      btn.addEventListener('click', () => I18n.setLanguage(btn.dataset.lang));
    });
    $('accessKey').addEventListener('input', onAccessKeyInput);
    $('accessKey').addEventListener('keypress', e => { if (e.key === 'Enter') { e.preventDefault(); e.target.blur(); } });
    $('togglePassword').addEventListener('click', togglePasswordVisibility);
    $('btnLogout').addEventListener('click', logout);
    $('btnReloadUsers').addEventListener('click', loadUsers);
    $('btnReloadTrans').addEventListener('click', loadTransformaciones);
    $('newForm').addEventListener('submit', submitNew);
    $('enunciado').addEventListener('input', updateCharCount);
    $('enunciado').addEventListener('keydown', e => {
      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) $('newForm').requestSubmit();
    });
    document.querySelectorAll('#mainTabs .tab-button').forEach(btn => btn.addEventListener('click', () => switchTab(btn.dataset.tab)));

    // Event delegation for everything rendered dynamically
    document.addEventListener('click', e => {
      const target = e.target;
      const infoTab = target.closest('[data-info-tab]');
      if (infoTab) return showInfoTab(infoTab.dataset.infoTab);

      const example = target.closest('[data-example]');
      if (example) return loadExample(example.dataset.example);

      const toggle = target.closest('[data-toggle]');
      if (toggle) return toggleCard(toggle.dataset.toggle);

      const dtab = target.closest('[data-dtab]');
      if (dtab) {
        const vm = findVm(dtab.dataset.key);
        if (vm) { vm.activeTab = dtab.dataset.dtab; render(vm); }
        return;
      }

      const dl = target.closest('[data-download]');
      if (dl) {
        const id = dl.dataset.download;
        const path = dl.dataset.scope === 'admin' ? `/admin/transformaciones/${id}/download-docx` : `/mi-historial/${id}/download-docx`;
        return downloadFile(path, `transformacion_${id}_LEdui.docx`);
      }

      const adminView = target.closest('[data-admin-view]');
      if (adminView) return toggleAdminDetail(adminView.dataset.adminView, adminView);

      const action = target.closest('[data-action]')?.dataset.action;
      if (action === 'new') return openNewModal();
      if (action === 'close-new') return closeNewModal();
      if (action === 'reload-mine') return loadMine();
      if (target === $('newModal')) closeNewModal();
    });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeNewModal(); });
  }

  async function init() {
    bindEvents();
    I18n.onChange(onLanguageChanged);
    try {
      state.config = { ...state.config, ...(await api('/config/public', { timeout: 10000 })) };
    } catch (err) {
      console.warn('No se pudo leer /config/public; se usan valores por defecto', err);
    }
    state.configLoaded = true;
    $('accessKeyGroup').hidden = !state.config.requiere_clave;
    setGoogleEnabled(!state.config.requiere_clave);
    await I18n.setLanguage(I18n.detect(state.config.idioma_por_defecto));
    initGoogle();
    await restoreSession();
  }

  window.LEdui = {
    onGoogleLoaded() {
      state.googleReady = true;
      initGoogle();
    },
  };

  document.addEventListener('DOMContentLoaded', init);
})();
