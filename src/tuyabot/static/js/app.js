/**
 * Dashboard Tuyabot — ES module, tanpa framework.
 *
 * Prinsip:
 * - Semua teks dari API dimasukkan lewat textContent (tanpa menyisipkan HTML dari data).
 * - Status perangkat datang dari SSE (/api/stream); tabel dimuat saat tab dibuka.
 * - Login memakai cookie HttpOnly; API key tidak disimpan di browser.
 */

import { ApiError, api, getSession, login, logout } from './api.js';
import { drawPowerChart } from './chart.js';

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const state = {
  devices: [],
  powerLogs: [],
  activities: [],
  range: '1h',
  sse: null,
  clockTimer: null,
  lastSnapshotTs: 0,
};

const DEVICE_META = {
  air: { icon: '💧', label: 'Pompa air', hasPower: true },
  lampu: { icon: '💡', label: 'Lampu', hasPower: false },
};

// ── Utilitas DOM ──

function el(tag, props = {}, children = []) {
  const node = document.createElement(tag);
  Object.entries(props).forEach(([key, value]) => {
    if (value === undefined || value === null) return;
    if (key === 'class') node.className = value;
    else if (key === 'text') node.textContent = value;
    else if (key === 'dataset') Object.assign(node.dataset, value);
    else node.setAttribute(key, value);
  });
  children.forEach((child) => node.append(child));
  return node;
}

function setText(selector, text) {
  const node = $(selector);
  if (node) node.textContent = text;
}

function formatWatt(value) {
  return Number.isFinite(value) ? `${value.toFixed(1)} W` : '—';
}

function formatAge(seconds) {
  if (!Number.isFinite(seconds)) return '—';
  if (seconds < 60) return `${Math.round(seconds)} dtk lalu`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} mnt lalu`;
  return `${Math.round(seconds / 3600)} jam lalu`;
}

function parseTime(value) {
  if (!value) return null;
  const parsed = new Date(String(value).replace(' ', 'T'));
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function formatTime(value) {
  const parsed = parseTime(value);
  if (!parsed) return String(value ?? '—');
  return parsed.toLocaleString('id-ID', { dateStyle: 'short', timeStyle: 'medium' });
}

// ── Toast & konfirmasi ──

let toastTimer = null;
function toast(message, kind = 'ok') {
  const node = $('#toast');
  node.textContent = message;
  node.className = `toast toast--${kind}`;
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.hidden = true; }, 4200);
}

function confirmAction(title, text, confirmLabel = 'Lanjutkan') {
  return new Promise((resolve) => {
    const modal = $('#confirm');
    $('#confirm-title').textContent = title;
    $('#confirm-text').textContent = text;
    $('#confirm-ok').textContent = confirmLabel;
    modal.hidden = false;
    $('#confirm-cancel').focus();

    const finish = (result) => {
      modal.hidden = true;
      $('#confirm-ok').removeEventListener('click', onOk);
      $('#confirm-cancel').removeEventListener('click', onCancel);
      document.removeEventListener('keydown', onKey);
      resolve(result);
    };
    const onOk = () => finish(true);
    const onCancel = () => finish(false);
    const onKey = (event) => { if (event.key === 'Escape') finish(false); };

    $('#confirm-ok').addEventListener('click', onOk);
    $('#confirm-cancel').addEventListener('click', onCancel);
    document.addEventListener('keydown', onKey);
  });
}

// ── Autentikasi ──

function showLogin(message = '') {
  $('#app-view').hidden = true;
  $('#login-view').hidden = false;
  const error = $('#login-error');
  if (message) {
    error.textContent = message;
    error.hidden = false;
  } else {
    error.hidden = true;
  }
  $('#api-key').focus();
}

function showApp() {
  $('#login-view').hidden = true;
  $('#app-view').hidden = false;
}

async function handleLogin(event) {
  event.preventDefault();
  const input = $('#api-key');
  const submit = event.target.querySelector('button[type="submit"]');
  submit.disabled = true;
  try {
    await login(input.value.trim());
    input.value = '';
    showApp();
    await startDashboard();
    toast('Berhasil masuk.');
  } catch (error) {
    const message = error instanceof ApiError ? error.message : 'Tidak bisa masuk.';
    $('#login-error').textContent = message;
    $('#login-error').hidden = false;
  } finally {
    submit.disabled = false;
  }
}

async function handleLogout() {
  try {
    await logout();
  } catch { /* diabaikan: tetap keluar dari tampilan */ }
  stopStream();
  showLogin('Anda sudah keluar.');
}

// ── Device cards ──

function buildDeviceCard(name) {
  const meta = DEVICE_META[name] || { icon: '🔌', label: name, hasPower: false };
  const stats = meta.hasPower
    ? [['Daya', 'power'], ['Tegangan', 'voltage'], ['Arus', 'current'], ['Umur data', 'age']]
    : [['Status', 'switch'], ['Koneksi', 'online'], ['Umur data', 'age']];

  const card = el('article', { class: 'device', dataset: { device: name } }, [
    el('header', { class: 'device__head' }, [
      el('h2', { class: 'device__name', text: `${meta.icon} ${meta.label}` }),
      el('span', { class: 'device__state', dataset: { role: 'state' }, text: 'memuat…' }),
    ]),
    el('dl', { class: 'device__stats' },
      stats.map(([label, role]) => el('div', {}, [
        el('dt', { text: label }),
        el('dd', { dataset: { role }, text: '—' }),
      ]))),
    el('div', { class: 'device__actions' }, [
      el('button', { class: 'btn btn--on', type: 'button', dataset: { action: 'on', device: name }, text: 'Nyalakan' }),
      el('button', { class: 'btn btn--off', type: 'button', dataset: { action: 'off', device: name }, text: 'Matikan' }),
    ]),
    el('p', { class: 'device__foot', dataset: { role: 'updated' }, text: '—' }),
  ]);
  return card;
}

function renderDeviceCards() {
  const grid = $('#device-grid');
  grid.replaceChildren();
  state.devices.forEach((name) => grid.append(buildDeviceCard(name)));
}

function renderDeviceState(name, info) {
  const card = $(`[data-device="${name}"]`);
  if (!card) return;

  const online = Boolean(info.online);
  const on = info.switch_on === true;
  card.classList.toggle('is-on', on && online);
  card.classList.toggle('is-offline', !online);

  const stateNode = card.querySelector('[data-role="state"]');
  if (stateNode) {
    stateNode.textContent = !online ? 'offline' : on ? 'menyala' : 'mati';
  }

  const set = (role, text) => {
    const node = card.querySelector(`[data-role="${role}"]`);
    if (node) node.textContent = text;
  };
  set('switch', online ? (on ? 'menyala' : 'mati') : '—');
  set('online', online ? 'terhubung' : 'offline');
  set('power', formatWatt(info.power_w));
  set('voltage', Number.isFinite(info.voltage_v) ? `${info.voltage_v.toFixed(1)} V` : '—');
  set('current', Number.isFinite(info.current_a) ? `${info.current_a.toFixed(2)} A` : '—');
  set('age', formatAge(info.status_age_s));
  set('updated', online ? 'data segar dari cache perangkat' : 'perangkat belum merespons');
}

function renderStrip(info) {
  const air = info.air || {};
  const lampu = info.lampu || {};

  setText('#strip-air', air.online ? (air.switch_on ? 'Menyala' : 'Mati') : 'Offline');
  setText('#strip-air-meta', `${formatWatt(air.power_w)} · ${formatAge(air.status_age_s)}`);
  setText('#strip-lampu', lampu.online ? (lampu.switch_on ? 'Menyala' : 'Mati') : 'Offline');
  setText('#strip-lampu-meta', lampu.online ? 'terhubung' : 'belum merespons');
  setText('#strip-power', formatWatt(air.power_w));
  setText('#strip-power-meta', `arus ${Number.isFinite(air.current_a) ? air.current_a.toFixed(2) : '—'} A · ${Number.isFinite(air.voltage_v) ? air.voltage_v.toFixed(0) : '—'} V`);
}

// ── SSE ──

function setLiveBadge(kind, text) {
  const badge = $('#live-badge');
  badge.className = `badge badge--${kind}`;
  setText('#live-text', text);
}

function startStream() {
  stopStream();
  if (!('EventSource' in window)) {
    setLiveBadge('idle', 'tanpa SSE');
    return;
  }
  const source = new EventSource('/api/stream');
  state.sse = source;

  source.addEventListener('open', () => setLiveBadge('live', 'real-time'));
  source.addEventListener('error', () => setLiveBadge('down', 'terputus, mencoba lagi'));
  source.addEventListener('message', (event) => {
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch {
      return;
    }
    state.lastSnapshotTs = payload.ts || Date.now();
    Object.entries(payload.devices || {}).forEach(([name, info]) => renderDeviceState(name, info));
    renderStrip(payload.devices || {});
    setLiveBadge('live', 'real-time');
  });
}

function stopStream() {
  if (state.sse) {
    state.sse.close();
    state.sse = null;
  }
}

// ── Tabel ──

function emptyRow(columns, text) {
  const row = el('tr');
  const cell = el('td', { class: 'empty', text });
  cell.colSpan = columns;
  row.append(cell);
  return row;
}

function renderPowerTable() {
  const body = $('#power-rows');
  body.replaceChildren();
  if (!state.powerLogs.length) {
    body.append(emptyRow(5, 'Belum ada catatan daya.'));
    return;
  }
  state.powerLogs.slice(0, 50).forEach((row) => {
    body.append(el('tr', {}, [
      el('td', { text: formatTime(row.created_at) }),
      el('td', { text: formatWatt(Number(row.power_w)) }),
      el('td', { text: Number.isFinite(Number(row.voltage_v)) ? `${Number(row.voltage_v).toFixed(1)} V` : '—' }),
      el('td', { text: Number.isFinite(Number(row.current_a)) ? `${Number(row.current_a).toFixed(2)} A` : '—' }),
      el('td', { text: String(row.source ?? '—') }),
    ]));
  });
}

function renderPowerChart() {
  const canvas = $('#power-chart');
  const ranges = { '1h': 3600e3, '24h': 86400e3, '7d': 7 * 86400e3 };
  const cutoff = Date.now() - (ranges[state.range] || ranges['1h']);

  const points = state.powerLogs
    .map((row) => ({ t: parseTime(row.created_at), v: Number(row.power_w) }))
    .filter((point) => point.t && point.t.getTime() >= cutoff && Number.isFinite(point.v))
    .sort((a, b) => a.t - b.t)
    .map((point) => ({ t: point.t.getTime(), v: point.v }));

  const empty = $('#chart-empty');
  empty.hidden = points.length > 0;
  canvas.hidden = points.length === 0;

  const summary = $('#power-summary');
  const setSummary = (role, text) => {
    const node = summary.querySelector(`[data-role="${role}"]`);
    if (node) node.textContent = text;
  };

  if (!points.length) {
    ['now', 'avg', 'max', 'count'].forEach((role) => setSummary(role, '—'));
    return;
  }

  const values = points.map((point) => point.v);
  const avg = values.reduce((total, value) => total + value, 0) / values.length;
  setSummary('now', formatWatt(values[values.length - 1]));
  setSummary('avg', formatWatt(avg));
  setSummary('max', formatWatt(Math.max(...values)));
  setSummary('count', String(points.length));

  drawPowerChart(canvas, points);
}

function renderActivities(filter = '') {
  const body = $('#activity-rows');
  body.replaceChildren();
  const needle = filter.trim().toLowerCase();
  const rows = state.activities.filter((row) => {
    if (!needle) return true;
    return [row.device_name, row.action, row.status, row.user_role, row.message, row.user_id]
      .some((field) => String(field ?? '').toLowerCase().includes(needle));
  });

  if (!rows.length) {
    body.append(emptyRow(7, needle ? 'Tidak ada baris yang cocok.' : 'Belum ada aktivitas.'));
    return;
  }
  rows.slice(0, 100).forEach((row) => {
    body.append(el('tr', {}, [
      el('td', { text: formatTime(row.created_at) }),
      el('td', { text: String(row.user_id ?? '—') }),
      el('td', { text: String(row.user_role ?? '—') }),
      el('td', { text: String(row.device_name ?? '—') }),
      el('td', { text: String(row.action ?? '—') }),
      el('td', { text: String(row.status ?? '—') }),
      el('td', { class: 'cell-wrap', text: String(row.message ?? '') }),
    ]));
  });
}

function renderUsers() {
  const superadmins = $('#superadmin-list');
  const recipients = $('#recipient-list');
  const rows = $('#user-rows');
  superadmins.replaceChildren();
  recipients.replaceChildren();
  rows.replaceChildren();

  const roleName = (role) => ({ 0: 'Publik', 1: 'User', 2: 'Admin', 3: 'Superadmin' }[role] || `Role ${role}`);

  api.get('/api/db/users').then((data) => {
    const env = data.env || {};
    const runtime = data.runtime || [];
    const airRecipients = data.air_recipients || [];

    const envIds = Object.keys(env);
    if (!envIds.length) {
      superadmins.append(el('li', { class: 'chip chip--muted', text: 'Tidak ada Superadmin di ENV' }));
    } else {
      envIds.forEach((id) => superadmins.append(el('li', { class: 'chip', text: id })));
    }

    if (!airRecipients.length) {
      recipients.append(el('li', { class: 'chip chip--muted', text: 'Belum ada penerima notifikasi air' }));
    } else {
      airRecipients.forEach((id) => recipients.append(el('li', { class: 'chip', text: String(id) })));
    }

    if (!runtime.length) {
      rows.append(emptyRow(5, 'Belum ada user runtime. Tambahkan lewat bot Telegram.'));
      return;
    }
    runtime.forEach((user) => {
      rows.append(el('tr', {}, [
        el('td', { text: String(user.user_id) }),
        el('td', { text: roleName(user.role) }),
        el('td', { text: user.added_by_name || (user.added_by ?? '—') }),
        el('td', { text: formatTime(user.created_at) }),
        el('td', { text: formatTime(user.updated_at) }),
      ]));
    });
  }).catch((error) => {
    rows.append(emptyRow(5, `Gagal memuat user: ${error.message}`));
  });
}

async function loadDbStats() {
  const stats = await api.get('/api/db/stats');
  setText('#strip-db', stats.connected ? 'Terhubung' : 'Terputus');
  const total = Number(stats.total_power_logs || 0)
    + Number(stats.total_activity_logs || 0)
    + Number(stats.total_error_logs || 0);
  setText('#strip-db-meta', `${total.toLocaleString('id-ID')} baris log · ${stats.engine || 'sqlite'}`);
  return stats;
}

function renderSystem() {
  Promise.all([
    api.get('/api/health'),
    loadDbStats(),
    api.get('/api/db/errors?limit=50'),
  ]).then(([health, stats, errors]) => {
    const summary = $('#health-summary');
    const set = (role, text) => {
      const node = summary.querySelector(`[data-role="${role}"]`);
      if (node) node.textContent = text;
    };
    set('status', String(health.status ?? '—'));
    set('database', health.database ? 'terhubung' : 'gagal');
    set('devices', health.devices ? 'segar' : 'belum ada data');
    set('engine', String(stats.engine ?? 'sqlite'));
    set('size', `${(Number(stats.size_bytes || 0) / 1024).toFixed(0)} KB`);
    set('retention', `${stats.retention_days ?? '—'} hari`);

    const body = $('#error-rows');
    body.replaceChildren();
    if (!errors.length) {
      body.append(emptyRow(4, 'Tidak ada error tercatat.'));
      return;
    }
    errors.forEach((row) => {
      body.append(el('tr', {}, [
        el('td', { text: formatTime(row.created_at) }),
        el('td', { text: String(row.level ?? '—') }),
        el('td', { text: String(row.logger_name ?? '—') }),
        el('td', { class: 'cell-wrap', text: String(row.message ?? '') }),
      ]));
    });
  }).catch((error) => {
    toast(`Gagal memuat status sistem: ${error.message}`, 'err');
  });
}

// ── Aksi perangkat ──

async function controlDevice(device, action, button) {
  const label = `${DEVICE_META[device]?.label || device}`;
  if (device === 'air' && action === 'off') {
    const ok = await confirmAction(
      'Matikan pompa air?',
      `Perintah akan langsung dikirim ke ${label}. Pastikan tidak ada proses pengisian yang sedang berjalan.`,
      'Matikan',
    );
    if (!ok) return;
  }

  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = 'Mengirim…';
  try {
    const result = await api.post(`/api/devices/${device}/${action}`);
    if (result.success) {
      toast(result.no_op ? result.message : `${label}: ${result.message}`);
    } else {
      toast(`${label} gagal: ${result.message || 'perangkat tidak merespons'}`, 'err');
    }
  } catch (error) {
    const message = error instanceof ApiError && error.status === 401
      ? 'Sesi berakhir, silakan masuk lagi.'
      : error.message;
    toast(`Perintah gagal: ${message}`, 'err');
    if (error instanceof ApiError && error.status === 401) showLogin(message);
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

// ── Tabs ──

function activateTab(panelId) {
  $$('.tab').forEach((tab) => {
    const active = tab.dataset.panel === panelId;
    tab.classList.toggle('is-active', active);
    tab.setAttribute('aria-selected', String(active));
  });
  $$('.panel').forEach((panel) => {
    const active = panel.id === panelId;
    panel.classList.toggle('is-active', active);
    panel.hidden = !active;
  });

  if (panelId === 'panel-power') {
    renderPowerChart();
    renderPowerTable();
  } else if (panelId === 'panel-activity' && !state.activities.length) {
    loadActivities();
  } else if (panelId === 'panel-users') {
    renderUsers();
  } else if (panelId === 'panel-system') {
    renderSystem();
  }
}

// ── Pemuat data ──

async function loadDevices() {
  const data = await api.get('/api/devices');
  state.devices = (data.devices || []).map((device) => device.name);
  renderDeviceCards();
}

async function loadPower() {
  state.powerLogs = await api.get('/api/db/power-logs?limit=200');
  renderPowerChart();
  renderPowerTable();
}

async function loadActivities() {
  state.activities = await api.get('/api/db/activities?limit=100');
  renderActivities($('#activity-search').value);
}

function startClock() {
  const tick = () => {
    const node = $('#clock');
    if (node) node.textContent = new Date().toLocaleTimeString('id-ID', { hour12: false });
  };
  tick();
  clearInterval(state.clockTimer);
  state.clockTimer = setInterval(tick, 1000);
}

async function startDashboard() {
  startClock();
  try {
    await loadDevices();
    await loadPower();
    await loadDbStats();
  } catch (error) {
    toast(`Gagal memuat data awal: ${error.message}`, 'err');
    if (error instanceof ApiError && error.status === 401) {
      showLogin('Sesi berakhir, silakan masuk lagi.');
      return;
    }
  }
  startStream();
}

// ── Event wiring ──

function wireEvents() {
  $('#login-form').addEventListener('submit', handleLogin);
  $('#logout-btn').addEventListener('click', handleLogout);

  $$('.tab').forEach((tab) => {
    tab.addEventListener('click', () => activateTab(tab.dataset.panel));
  });

  $('#device-grid').addEventListener('click', (event) => {
    const button = event.target.closest('button[data-action]');
    if (!button) return;
    controlDevice(button.dataset.device, button.dataset.action, button);
  });

  $$('.segmented__btn').forEach((button) => {
    button.addEventListener('click', () => {
      state.range = button.dataset.range;
      $$('.segmented__btn').forEach((other) => other.classList.toggle('is-active', other === button));
      renderPowerChart();
    });
  });

  $('#refresh-power').addEventListener('click', () => { loadPower().catch((error) => toast(error.message, 'err')); });
  $('#refresh-system').addEventListener('click', renderSystem);
  $('#activity-search').addEventListener('input', (event) => renderActivities(event.target.value));

  $('#cleanup-btn').addEventListener('click', async () => {
    const ok = await confirmAction('Bersihkan log lama?', 'Baris log yang lebih tua dari masa retensi akan dihapus permanen.', 'Bersihkan');
    if (!ok) return;
    try {
      const result = await api.post('/api/db/cleanup');
      toast(result.message || 'Pembersihan selesai.');
      renderSystem();
    } catch (error) {
      toast(`Gagal membersihkan: ${error.message}`, 'err');
    }
  });

  window.addEventListener('resize', () => {
    if (!$('#panel-power').hidden) renderPowerChart();
  });

  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') startStream();
  });
}

// ── Boot ──

(async function init() {
  wireEvents();
  const session = await getSession();
  if (!session.authenticated) {
    showLogin();
    return;
  }
  showApp();
  await startDashboard();
})();
