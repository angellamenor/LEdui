/*
 * LEdui — lógica del frontend.
 * Depende de i18n.js (window.I18n). Sin frameworks.
 */
(function () {
  'use strict';

  const API_URL = window.location.hostname === 'localhost' && window.location.port !== '8000'
    ? 'http://localhost:8000'
    : window.location.origin;

  // Client ID por defecto (el de la versión anterior); el servidor puede sustituirlo vía /config/public
  const DEFAULT_GOOGLE_CLIENT_ID = '1016751986529-b87941fcfc310qut1am83t7fe5b0rvcl.apps.googleusercontent.com';

  const state = {
    config: { requiere_clave: true, google_client_id: null },
    accessToken: null,
    currentUser: null,
    accessKey: '',
    accessKeyValid: false,
    configLoaded: false,
    googleReady: false,
    googleInitialised: false,
    activeTab: 'adaptar',
  };

  const $ = (id) => document.getElementById(id);
  const t = (k, p) => I18n.t(k, p);

  // ---------------------------------------------------------------- utilidades

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text == null ? '' : String(text);
    return div.innerHTML;
  }

  /** Deja solo las etiquetas que genera el modelo, sin atributos (evita XSS). */
  const ALLOWED_TAGS = new Set(['H1', 'H2', 'H3', 'H4', 'P', 'OL', 'UL', 'LI', 'STRONG', 'B', 'EM', 'I', 'BR']);
  function sanitizeHtml(html) {
    const doc = new DOMParser().parseFromString(`<div>${html || ''}</div>`, 'text/html');
    const walk = (node) => {
      Array.from(node.childNodes).forEach(child => {
        if (child.nodeType === Node.ELEMENT_NODE) {
          if (!ALLOWED_TAGS.has(child.tagName)) {
            if (['SCRIPT', 'STYLE', 'IFRAME', 'OBJECT'].includes(child.tagName)) {
              child.remove();
              return;
            }
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

  /** **negrita** y párrafos separados por línea en blanco -> HTML seguro. */
  function markdownToHtml(text) {
    if (!text) return '';
    return escapeHtml(text)
      .split(/\n\s*\n/)
      .map(p => p.trim())
      .filter(Boolean)
      .map(p => {
        const html = p.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>');
        const isRule = /^<strong>(Regla|Rule)\b/.test(html);
        return `<p style="margin-bottom: 12px;${isRule ? ' margin-top: 20px;' : ''}">${html}</p>`;
      })
      .join('');
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

  function langLabel(code) {
    return code ? code.toUpperCase() : 'ES';
  }

  function statusBadge(ok) {
    return ok
      ? `<span class="badge badge-success">${t('badge.success')}</span>`
      : `<span class="badge badge-error">${t('badge.error')}</span>`;
  }

  function messageRow(tbody, cols, html, color) {
    tbody.innerHTML = `<tr><td colspan="${cols}" style="text-align: center; padding: 40px;${color ? ` color: ${color};` : ''}">${html}</td></tr>`;
  }

  function loadingRow(tbody, cols, key) {
    messageRow(tbody, cols, `<div class="spinner"></div><p>${escapeHtml(t(key))}</p>`);
  }

  let errorTimer = null;
  function showError(message, elementId = 'error') {
    const el = $(elementId);
    el.textContent = '❌ ' + message;
    el.classList.add('active');
    clearTimeout(errorTimer);
    errorTimer = setTimeout(() => el.classList.remove('active'), 7000);
  }

  // ---------------------------------------------------------------- API

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
        const detail = typeof data.detail === 'string' ? data.detail : `HTTP ${res.status}`;
        throw new ApiError(detail, res.status);
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
      const disposition = res.headers.get('Content-Disposition') || '';
      const match = disposition.match(/filename="?([^"]+)"?/);
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

  // ---------------------------------------------------------------- idioma

  function updateLangButtons(lang) {
    document.querySelectorAll('.lang-switch button').forEach(btn => {
      btn.setAttribute('aria-pressed', String(btn.dataset.lang === lang));
    });
  }

  function onLanguageChanged(lang) {
    updateLangButtons(lang);
    $('authSubtitle').textContent = t(state.config.requiere_clave ? 'auth.subtitle' : 'auth.subtitle_nokey');
    refreshKeyHint();
    renderGoogleButton();
    if (state.currentUser) {
      loadStats();
      if (state.activeTab === 'historial') loadHistorial();
      if (state.activeTab === 'admin') { loadUsers(); loadTransformaciones(); }
    }
  }

  // ---------------------------------------------------------------- acceso

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

  // ---------------------------------------------------------------- Google

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

  // ---------------------------------------------------------------- sesión

  function saveSession() {
    try {
      localStorage.setItem('access_token', state.accessToken);
      localStorage.setItem('current_user', JSON.stringify(state.currentUser));
    } catch (_) { /* almacenamiento no disponible */ }
  }

  function clearSession() {
    try {
      ['access_token', 'current_user', 'is_admin_mode'].forEach(k => localStorage.removeItem(k));
    } catch (_) { /* nada */ }
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
      // Se confirma con el servidor (y se actualiza is_admin por si ha cambiado)
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
    $('authSection').style.display = 'none';
    $('userInfo').classList.add('active');
    $('tabsContainer').classList.add('active');
    $('userName').textContent = user.name || '';
    $('userEmail').textContent = user.email || '';
    $('userAvatar').src = user.picture || '';
    $('userAvatar').alt = user.name || '';
    document.querySelector('.tab-button[data-tab="admin"]').hidden = !user.is_admin;
    switchTab('adaptar');
    loadStats();
  }

  function logout() {
    state.accessToken = null;
    state.currentUser = null;
    state.accessKey = '';
    state.accessKeyValid = false;
    clearSession();

    $('tabsContainer').classList.remove('active');
    $('userInfo').classList.remove('active');
    $('authSection').style.display = 'block';
    $('result').classList.remove('active');
    $('error').classList.remove('active');
    closeModal();

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

  // ---------------------------------------------------------------- pestañas

  function switchTab(name) {
    state.activeTab = name;
    document.querySelectorAll('.tab-button').forEach(btn => {
      const active = btn.dataset.tab === name;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-selected', String(active));
    });
    $('tabAdaptar').classList.toggle('active', name === 'adaptar');
    $('tabHistorial').classList.toggle('active', name === 'historial');
    $('tabAdmin').classList.toggle('active', name === 'admin');
    if (name === 'historial') loadHistorial();
    if (name === 'admin') { loadUsers(); loadTransformaciones(); }
  }

  // ---------------------------------------------------------------- adaptación

  function renderPictogramas(data) {
    const img = $('pictogramImage');
    if (data.imagen_compuesta_base64) {
      img.src = `data:image/png;base64,${data.imagen_compuesta_base64}`;
      img.hidden = false;
    }
    const list = $('habilidadesList');
    const ok = (data.pictogramas || []).filter(p => p.exito);
    if (!ok.length) {
      list.innerHTML = `<p style="color: #6b7280; text-align: center;">${escapeHtml(t('result.no_pictos'))}</p>`;
      return;
    }
    list.innerHTML = ok.map(p => {
      const name = escapeHtml(p.etiqueta || p.accion_simplificada || p.keyword || '');
      const text = escapeHtml(p.explicacion_alumno || t('result.default_skill'));
      const thumb = p.imagen_base64
        ? `<img src="data:image/png;base64,${p.imagen_base64}" alt="${name}" style="width: 80px; height: 80px; object-fit: contain; flex-shrink: 0; background: #f3f4f6; border-radius: 8px; padding: 8px;">`
        : '';
      return `<div class="habilidad-item"><div style="display: flex; align-items: start; gap: 16px;">${thumb}
                <div style="flex: 1;"><div class="habilidad-nombre">${name}</div>
                <div class="habilidad-aplicacion">${text}</div></div></div></div>`;
    }).join('');
  }

  function renderImagenes(data) {
    const container = $('contextImages');
    const ok = (data.imagenes || []).filter(i => i.exito && i.imagen_base64);
    if (!ok.length) {
      container.innerHTML = `<p style="color: #6b7280; text-align: center;">${escapeHtml(t('result.no_images'))}</p>`;
      return;
    }
    container.innerHTML = ok.map((img, i) => `
      <div class="context-image-item">
        <img src="data:image/png;base64,${img.imagen_base64}" alt="${escapeHtml(img.concepto_clave || t('detail.image', { n: i + 1 }))}" class="context-image">
        <div class="context-explanation">
          <strong>${escapeHtml(t('result.why_image'))}</strong>
          ${escapeHtml(img.justificacion || t('result.default_image'))}
        </div>
      </div>`).join('');
  }

  async function adaptar() {
    const enunciado = $('enunciado').value;
    const nivel = $('nivel').value;
    if (!enunciado.trim()) return showError(t('errors.write_statement'));
    if (enunciado.length > 15000) return showError(t('errors.too_long'));
    if (!nivel) return showError(t('errors.select_level'));
    if (!state.accessToken) { showError(t('errors.not_auth')); return logout(); }

    const idioma = I18n.lang;  // el idioma de la interfaz decide el de la adaptación
    $('loading').classList.add('active');
    $('result').classList.remove('active');
    $('error').classList.remove('active');
    $('btnAdaptar').disabled = true;
    ['resultStatement', 'resultIndicaciones', 'habilidadesList', 'contextImages', 'resultTokens']
      .forEach(id => { $(id).innerHTML = ''; });
    $('pictogramImage').hidden = true;
    $('pictogramImage').removeAttribute('src');

    let tokensIn = 0, tokensOut = 0;
    let adaptacionLista = false;
    try {
      $('loadingStep').textContent = t('loading.step1');
      const a = await api('/adaptar_enunciado_ledu', {
        method: 'POST', body: { enunciado, nivel, max_palabras: 350, idioma }, timeout: 120000,
      });
      tokensIn += a.tokens_entrada || 0;
      tokensOut += a.tokens_salida || 0;
      $('resultStatement').innerHTML = sanitizeHtml(a.enunciado_adaptado);
      $('resultIndicaciones').innerHTML = markdownToHtml(a.indicaciones_docentes);
      $('result').classList.add('active');
      adaptacionLista = true;

      $('loadingStep').textContent = t('loading.step2');
      const p = await api('/generar_pictogramas', {
        method: 'POST', body: { enunciado: a.enunciado_adaptado, transformacion_id: a.transformacion_id, idioma },
        timeout: 120000,
      });
      tokensIn += p.tokens_analisis?.entrada || 0;
      tokensOut += p.tokens_analisis?.salida || 0;
      renderPictogramas(p);

      $('loadingStep').textContent = t('loading.step3');
      const c = await api('/generar_imagenes_contexto', {
        method: 'POST', body: { enunciado: a.enunciado_adaptado, num_imagenes: 1, transformacion_id: a.transformacion_id, idioma },
        timeout: 180000,
      });
      tokensIn += c.tokens_analisis?.entrada || 0;
      tokensOut += c.tokens_analisis?.salida || 0;
      renderImagenes(c);
    } catch (err) {
      showError(adaptacionLista ? t('result.partial', { msg: err.message }) : t('errors.process', { msg: err.message }));
    } finally {
      if (tokensIn || tokensOut) {
        $('resultTokens').textContent = t('result.tokens', {
          in: I18n.formatNumber(tokensIn), out: I18n.formatNumber(tokensOut), total: I18n.formatNumber(tokensIn + tokensOut),
        });
      }
      $('loading').classList.remove('active');
      $('btnAdaptar').disabled = false;
      loadStats();
    }
  }

  // ---------------------------------------------------------------- historial

  async function loadHistorial() {
    const tbody = $('historialTableBody');
    const stats = $('historialStats');
    $('historialEmpty').hidden = true;
    loadingRow(tbody, 7, 'history.loading');
    stats.textContent = '';
    try {
      const data = await api('/mi-historial');
      stats.textContent = data.total === 1 ? t('history.total_one') : t('history.total_other', { n: data.total });
      if (!data.transformaciones?.length) {
        tbody.innerHTML = '';
        $('historialEmpty').hidden = false;
        return;
      }
      tbody.innerHTML = data.transformaciones.map(tr => {
        const full = tr.enunciado_original || t('history.no_statement');
        const short = full.length > 50 ? full.slice(0, 50) + '...' : full;
        return `<tr>
          <td><strong>#${tr.id}</strong></td>
          <td title="${escapeHtml(full)}">${escapeHtml(short)}</td>
          <td><span class="badge badge-user">${escapeHtml(levelLabel(tr.nivel))}</span></td>
          <td>${escapeHtml(langLabel(tr.idioma))}</td>
          <td style="font-size: 13px;">${escapeHtml(I18n.formatDate(tr.created_at))}</td>
          <td>${statusBadge(tr.exito)}</td>
          <td><button type="button" class="btn-action-small" data-detail="${tr.id}" data-scope="user">${escapeHtml(t('common.view'))}</button></td>
        </tr>`;
      }).join('');
    } catch (err) {
      messageRow(tbody, 7, `${escapeHtml(t('history.error', { msg: err.message }))}<br><br>
        <button type="button" class="btn-secondary" data-action="reload-historial">${escapeHtml(t('history.retry'))}</button>`, '#ef4444');
      stats.textContent = t('history.error_short');
    }
  }

  // ---------------------------------------------------------------- admin

  async function loadUsers() {
    const tbody = $('usuariosTableBody');
    loadingRow(tbody, 6, 'admin.loading_users');
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
    loadingRow(tbody, 7, 'admin.loading_trans');
    try {
      const data = await api('/admin/transformaciones');
      if (!data.transformaciones?.length) return messageRow(tbody, 7, escapeHtml(t('admin.no_trans')), '#6b7280');
      tbody.innerHTML = data.transformaciones.map(tr => `<tr>
        <td>#${tr.id}</td>
        <td title="${escapeHtml(tr.user_email || '')}">#${tr.user_id}</td>
        <td>${escapeHtml(levelLabel(tr.nivel))}</td>
        <td>${escapeHtml(langLabel(tr.idioma))}</td>
        <td>${formatDuration(tr.duracion_ms)}</td>
        <td>${statusBadge(tr.exito)}</td>
        <td><button type="button" class="btn-view" data-detail="${tr.id}" data-scope="admin">${escapeHtml(t('common.view'))}</button></td>
      </tr>`).join('');
    } catch (err) {
      messageRow(tbody, 7, escapeHtml(t('admin.error_trans', { msg: err.message })), '#ef4444');
    }
  }

  // ---------------------------------------------------------------- detalle

  async function showDetail(id, scope) {
    const base = scope === 'admin' ? `/admin/transformaciones/${id}` : `/mi-historial/${id}`;
    try {
      const tr = await api(base);
      // Las imágenes se piden por /mi-historial, que permite al dueño y a los admins
      const pictoUrl = tr.pictogramas?.tiene_imagen
        ? await fetchImageAsDataUrl(`/mi-historial/pictogramas/${tr.pictogramas.id}/imagen`) : null;
      const imagenes = [];
      for (const img of tr.imagenes_contexto || []) {
        if (!img.tiene_imagen) continue;
        imagenes.push({ ...img, dataUrl: await fetchImageAsDataUrl(`/mi-historial/imagenes/${img.id}/imagen`) });
      }

      const badges = [
        `<div class="detail-badge">ID: #${tr.id}</div>`,
        scope === 'admin' ? `<div class="detail-badge">${escapeHtml(t('detail.user'))}: ${escapeHtml(tr.user_email || '#' + tr.user_id)}</div>` : '',
        `<div class="detail-badge">${escapeHtml(t('detail.level'))}: ${escapeHtml(levelLabel(tr.nivel))}</div>`,
        `<div class="detail-badge">${escapeHtml(t('detail.language'))}: ${escapeHtml(langLabel(tr.idioma))}</div>`,
        `<div class="detail-badge">${escapeHtml(t('detail.date'))}: ${escapeHtml(I18n.formatDate(tr.created_at, false))}</div>`,
        scope === 'admin' && tr.prompt_version ? `<div class="detail-badge">${escapeHtml(t('detail.prompt_version'))}: ${escapeHtml(tr.prompt_version)}</div>` : '',
        `<div class="detail-badge ${tr.exito ? 'badge-success' : 'badge-error'}">${tr.exito ? t('badge.success') : t('badge.error')}</div>`,
        `<button type="button" class="detail-badge" data-download="${tr.id}" data-scope="${scope}"
           style="padding: 8px 12px; font-size: 13px; cursor: pointer; background: var(--primary-color); color: white; border: none; border-radius: 6px; font-weight: 500; margin-left: auto;">${escapeHtml(t('detail.download'))}</button>`,
      ].join('');

      const section = (titleKey, inner) => `<div class="detail-section"><h4>${escapeHtml(t(titleKey))}</h4>${inner}</div>`;
      let html = `<div class="detail-header" style="display: flex; align-items: center; flex-wrap: wrap; gap: 10px;">${badges}</div>`;

      if (tr.enunciado_original) {
        html += section('detail.original', `<div class="detail-content" style="white-space: pre-wrap;">${escapeHtml(tr.enunciado_original)}</div>`);
      }
      if (tr.enunciado_adaptado) {
        html += section('detail.adapted', `<div class="detail-content detail-content-html" style="background: #f0f9ff; padding: 20px; border-radius: 12px; border-left: 4px solid #3b82f6;">${sanitizeHtml(tr.enunciado_adaptado)}</div>`);
      }
      if (tr.indicaciones_docentes) {
        html += section('detail.teacher', `<div class="detail-content">${markdownToHtml(tr.indicaciones_docentes)}</div>`);
      }
      if (tr.pictogramas) {
        html += section('detail.pictograms',
          (pictoUrl ? `<div class="detail-image-container"><img src="${pictoUrl}" alt="" style="max-width: 100%; border-radius: 12px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);"></div>` : '') +
          (tr.pictogramas.explicacion_habilidades
            ? `<div class="detail-content" style="background: #fef3c7; padding: 20px; border-radius: 12px; border-left: 4px solid #f59e0b; margin-top: 15px; white-space: pre-wrap;"><strong>${escapeHtml(t('detail.skills'))}:</strong><br>${escapeHtml(tr.pictogramas.explicacion_habilidades)}</div>`
            : ''));
      }
      if (imagenes.length) {
        html += section('detail.context_images', `<div style="display: grid; gap: 20px;">${imagenes.map((img, i) => `
          <div style="background: white; border: 2px solid #e5e7eb; border-radius: 12px; padding: 20px;">
            <h5 style="margin: 0 0 15px 0; color: var(--text-primary);">${escapeHtml(t('detail.image', { n: i + 1 }))}</h5>
            ${img.dataUrl ? `<img src="${img.dataUrl}" alt="" style="max-width: 100%; border-radius: 8px; margin-bottom: 15px; box-shadow: 0 2px 4px rgba(0,0,0,0.1);">` : ''}
            ${img.texto_explicativo ? `<div style="background: #f0fdf4; padding: 15px; border-radius: 8px; border-left: 4px solid #10b981; white-space: pre-wrap;"><strong>${escapeHtml(t('detail.why_image'))}</strong><br>${escapeHtml(img.texto_explicativo)}</div>` : ''}
          </div>`).join('')}</div>`);
      }
      if (tr.error_mensaje) {
        html += section('detail.error', `<div class="detail-content" style="background: #fee2e2; padding: 20px; border-radius: 12px; border-left: 4px solid #ef4444;">${escapeHtml(tr.error_mensaje)}</div>`);
      }
      const metric = (key, value, bg, color) => `<div style="background: ${bg}; padding: 15px; border-radius: 8px;">
          <div style="font-size: 12px; color: #6b7280; margin-bottom: 4px;">${escapeHtml(t(key))}</div>
          <div style="font-size: 20px; font-weight: 600; color: ${color};">${value}</div></div>`;
      html += section('detail.metrics', `<div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px;">
          ${metric('detail.tokens_in', I18n.formatNumber(tr.tokens_entrada), '#f0f9ff', '#2563eb')}
          ${metric('detail.tokens_out', I18n.formatNumber(tr.tokens_salida), '#f0f9ff', '#2563eb')}
          ${metric('detail.duration', formatDuration(tr.duracion_ms), '#fef3c7', '#d97706')}</div>`);

      $('transformacionDetail').innerHTML = html;
      $('transformacionModal').classList.add('active');
    } catch (err) {
      showError(err.status === 404 ? t('errors.not_found') : t('errors.detail', { msg: err.message }));
    }
  }

  function closeModal() {
    $('transformacionModal').classList.remove('active');
  }

  // ---------------------------------------------------------------- arranque

  function bindEvents() {
    document.querySelectorAll('.lang-switch button').forEach(btn => {
      btn.addEventListener('click', () => I18n.setLanguage(btn.dataset.lang));
    });
    $('accessKey').addEventListener('input', onAccessKeyInput);
    $('accessKey').addEventListener('keypress', e => { if (e.key === 'Enter') { e.preventDefault(); e.target.blur(); } });
    $('togglePassword').addEventListener('click', togglePasswordVisibility);
    $('btnLogout').addEventListener('click', logout);
    $('btnAdaptar').addEventListener('click', adaptar);
    $('btnReloadHistorial').addEventListener('click', loadHistorial);
    $('btnReloadUsers').addEventListener('click', loadUsers);
    $('btnReloadTrans').addEventListener('click', loadTransformaciones);
    $('btnCloseModal').addEventListener('click', closeModal);
    document.querySelectorAll('.tab-button').forEach(btn => btn.addEventListener('click', () => switchTab(btn.dataset.tab)));

    // Delegación para botones generados dinámicamente
    document.addEventListener('click', e => {
      const detail = e.target.closest('[data-detail]');
      if (detail) return showDetail(detail.dataset.detail, detail.dataset.scope);
      const dl = e.target.closest('[data-download]');
      if (dl) {
        const id = dl.dataset.download;
        const path = dl.dataset.scope === 'admin' ? `/admin/transformaciones/${id}/download-docx` : `/mi-historial/${id}/download-docx`;
        return downloadFile(path, `transformacion_${id}_LEdui.docx`);
      }
      if (e.target.closest('[data-action="reload-historial"]')) return loadHistorial();
      if (e.target === $('transformacionModal')) closeModal();
    });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });
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
