// App shell: hash router, top bar, bottom nav, toasts, refresh logic.

import { api, ApiError } from './api.js';
import { syncClock, gameNow, countdown, remainingMs } from './clock.js';
import { fmtNum, fmtTime } from './format.js';
import { onChanged } from './ws.js';
import { h, clear } from './dom.js';

const RES_KEYS = ['wood', 'stone', 'iron', 'food'];
const TOAST_MS = 4000;
const WS_DEBOUNCE_MS = 300;
const COUNTDOWN_REFRESH_MS = 1500;
const TYPING_RETRY_MS = 1000;
const PLACEHOLDER_TEXT = 'หน้านี้ยังไม่พร้อมใช้งาน';

// Route table: path segments (with :param placeholders) -> view module name.
const ROUTES = [
  { pattern: ['new'], view: 'newgame' },
  { pattern: [], view: 'village' },
  { pattern: ['v', ':id'], view: 'village' },
  { pattern: ['v', ':id', 'center'], view: 'center' },
  { pattern: ['center'], view: 'center' },
  { pattern: ['map'], view: 'map' },
  { pattern: ['reports'], view: 'reports' },
  { pattern: ['reports', ':id'], view: 'reports' },
  { pattern: ['ranking'], view: 'ranking' },
  { pattern: ['rally', ':vid'], view: 'rally' },
  { pattern: ['help'], view: 'help' },
  { pattern: ['login'], view: 'login' },
  { pattern: ['join'], view: 'join' },
  { pattern: ['alliance'], view: 'alliance' },
];

// Views that work without a loaded game state (login, join and new-world forms).
const STANDALONE_VIEWS = new Set(['login', 'join', 'newgame']);

// ---- DOM refs ----
const viewEl = document.getElementById('view');
const clockEl = document.getElementById('clock');
const pauseBtn = document.getElementById('pause-btn');
const villageSelect = document.getElementById('village-select');
const navLinks = Array.from(document.querySelectorAll('#bottomnav .nav-link'));
const accountBox = document.getElementById('account-box');
const accountName = document.getElementById('account-name');
const logoutBtn = document.getElementById('logout-btn');
const allianceLink = document.getElementById('nav-alliance');
const toastEl = document.getElementById('toast');
const resEls = Object.fromEntries(RES_KEYS.map((k) => [k, document.getElementById(`res-${k}`)]));

// ---- App state ----
let meta = null;
let me = null; // GET /auth/me: { auth_required, account, player }
let started = false;
let state = null;
let village = null;
let villageId = null;
let villageFetchedAtMs = 0;

let currentCleanup = null;
let renderToken = 0;
let inflight = false;
let queuedRefresh = false;
let toastTimer = null;
let wsTimer = null;
let countdownTimer = null;

// ---- Router ----

// Parse location.hash into { view, params, query, path } or null when unknown.
function parseRoute() {
  const raw = (location.hash || '#/').replace(/^#/, '');
  const [pathPart, queryPart] = raw.split('?');
  const query = new URLSearchParams(queryPart || '');
  const segs = pathPart.split('/').filter(Boolean);
  for (const route of ROUTES) {
    if (route.pattern.length !== segs.length) continue;
    const params = {};
    let ok = true;
    for (let i = 0; i < segs.length; i++) {
      const p = route.pattern[i];
      if (p.startsWith(':')) params[p.slice(1)] = segs[i];
      else if (p !== segs[i]) {
        ok = false;
        break;
      }
    }
    if (ok) return { view: route.view, params, query, path: pathPart };
  }
  return null;
}

// Fetch the village for the current route when it changed.
async function ensureVillage() {
  if (!state || state.villages.length === 0) {
    villageId = null;
    village = null;
    return;
  }
  const route = parseRoute();
  const wanted = route ? route.params.id ?? route.params.vid : null;
  const targetId = wanted != null ? Number(wanted) : (villageId ?? state.villages[0].id);
  if (targetId !== villageId || village == null) {
    villageId = targetId;
    village = await api.get(`/villages/${targetId}`);
    villageFetchedAtMs = gameNow().getTime();
  }
}

// Render the view module for the current hash route.
async function renderRoute() {
  const token = ++renderToken;
  const route = parseRoute();
  if (!route) {
    navigate('#/');
    return;
  }
  if (me && me.auth_required && !me.account && route.view !== 'login') {
    navigate('#/login');
    return;
  }
  if (currentCleanup) {
    try {
      currentCleanup();
    } catch (err) {
      console.error('view cleanup failed', err);
    }
    currentCleanup = null;
  }
  try {
    if (STANDALONE_VIEWS.has(route.view)) {
      village = null;
      villageId = null;
    } else {
      await ensureVillage();
    }
  } catch (err) {
    if (err instanceof ApiError) toast(err.message, true);
    return;
  }
  if (token !== renderToken) return;
  // Village pages need a loaded village; a later refresh() re-renders once it exists.
  if ((route.view === 'village' || route.view === 'center') && village == null) return;
  let mod;
  try {
    mod = await import(`./views/${route.view}.js`);
  } catch {
    clear(viewEl);
    viewEl.append(h('div', { class: 'panel' }, PLACEHOLDER_TEXT));
    return;
  }
  if (token !== renderToken) return;
  clear(viewEl);
  try {
    const cleanup = await mod.render(viewEl, ctx, { ...route.params, query: route.query });
    currentCleanup = typeof cleanup === 'function' ? cleanup : null;
  } catch (err) {
    if (err instanceof ApiError) toast(err.message, true);
    else console.error('view render failed', err);
  }
  updateNav();
}

// ---- ctx ----

const ctx = {
  get meta() {
    return meta;
  },
  get me() {
    return me;
  },
  get state() {
    return state;
  },
  get village() {
    return village;
  },
  get villageId() {
    return villageId;
  },
  toast,
  refresh,
  navigate,
  start: () => init(),
};

// ---- Toast ----

function toast(message, isError = false) {
  toastEl.textContent = message;
  toastEl.classList.toggle('toast-error', !!isError);
  toastEl.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toastEl.hidden = true;
  }, TOAST_MS);
}

// ---- Refresh (inflight flag + one queued follow-up) ----

function userIsTyping() {
  const ae = document.activeElement;
  return (
    ae && viewEl.contains(ae) && ['INPUT', 'SELECT', 'TEXTAREA'].includes(ae.tagName)
  );
}

// Render now, or shortly after if the user is typing in #view.
function renderWhenIdle() {
  if (userIsTyping()) {
    setTimeout(renderWhenIdle, TYPING_RETRY_MS);
    return;
  }
  renderRoute();
}

async function refresh() {
  if (inflight) {
    queuedRefresh = true;
    return;
  }
  inflight = true;
  try {
    state = await api.get('/state');
    syncClock(state.game_now);
    if (villageId != null) {
      village = await api.get(`/villages/${villageId}`);
      villageFetchedAtMs = gameNow().getTime();
    }
    updateTopbar();
    renderWhenIdle();
  } catch (err) {
    if (err instanceof ApiError) toast(err.message, true);
  } finally {
    inflight = false;
    if (queuedRefresh) {
      queuedRefresh = false;
      refresh();
    }
  }
}

// ---- Top bar ----

// Tick the four resource values once per second.
function tickResources() {
  if (!state || !village) return;
  const hours = (gameNow().getTime() - villageFetchedAtMs) / 3600000;
  for (const k of RES_KEYS) {
    const value = (village.resources[k] ?? 0) + (village.rates[k] ?? 0) * hours;
    const capped = Math.min(Math.max(value, 0), village.capacity[k] ?? 0);
    resEls[k].textContent = fmtNum(capped);
  }
  resEls.food.classList.toggle('negative', (village.rates.food ?? 0) < 0);
}

// Tick the clock display once per second.
function tickClock() {
  clockEl.textContent = state ? fmtTime(gameNow().toISOString()) : '';
}

function updatePauseBtn() {
  document.getElementById('pause-label').textContent = state && state.paused ? 'เล่นต่อ' : 'หยุด';
  document
    .getElementById('pause-use')
    .setAttribute('href', `img/icons.svg#i-${state && state.paused ? 'play' : 'pause'}`);
}

function updateVillageSelect() {
  clear(villageSelect);
  if (!state || state.villages.length <= 1) {
    villageSelect.hidden = true;
    return;
  }
  villageSelect.hidden = false;
  for (const v of state.villages) {
    villageSelect.append(h('option', { value: String(v.id), selected: v.id === villageId }, v.name));
  }
}

// Update pause button, village select and bottom nav.
function updateTopbar() {
  updateAccountUi();
  updatePauseBtn();
  updateVillageSelect();
  updateNav();
  tickResources();
  tickClock();
}

async function onTogglePause() {
  if (!state) return;
  try {
    state = state.paused ? await api.post('/admin/resume') : await api.post('/admin/pause');
    syncClock(state.game_now);
    updatePauseBtn();
    tickClock();
  } catch (err) {
    if (err instanceof ApiError) toast(err.message, true);
  }
}

// ---- Bottom nav ----

function navTarget(i, id) {
  switch (i) {
    case 0:
      return `v/${id}`;
    case 1:
      return `v/${id}/center`;
    case 2:
      return 'map';
    case 3:
      return 'reports';
    case 4:
      return 'ranking';
    case 5:
      return 'alliance';
    default:
      return '';
  }
}

function navMatches(i, path, id) {
  switch (i) {
    case 0:
      return path === '' || path === `v/${id}`;
    case 1:
      return path === 'center' || path === `v/${id}/center`;
    case 2:
      return path === 'map';
    case 3:
      return path === 'reports' || path.startsWith('reports/');
    case 4:
      return path === 'ranking';
    case 5:
      return path === 'alliance';
    default:
      return false;
  }
}

// Set the 'รายงาน' nav link (index 3) label, adding the unread count when > 0.
function updateReportsBadge() {
  const link = navLinks[3];
  if (!link) return;
  const n = state?.unread_reports ?? 0;
  link.querySelector('.nav-label').textContent = n > 0 ? `รายงาน (${n})` : 'รายงาน';
}

function updateNav() {
  const route = parseRoute();
  const path = route ? route.path : '';
  navLinks.forEach((link, i) => {
    if (villageId != null) link.href = `#/${navTarget(i, villageId)}`;
    link.classList.toggle('active', villageId != null && navMatches(i, path, villageId));
  });
  updateReportsBadge();
}

// ---- Countdowns ----

// Update every .countdown element; schedule one debounced refresh when any hits 0.
function tickCountdowns() {
  for (const el of viewEl.querySelectorAll('.countdown[data-countdown]')) {
    const iso = el.dataset.countdown;
    el.textContent = countdown(iso);
    if (remainingMs(iso) === 0 && countdownTimer === null) {
      countdownTimer = setTimeout(() => {
        countdownTimer = null;
        refresh();
      }, COUNTDOWN_REFRESH_MS);
    }
  }
}

// ---- Navigation / websocket ----

function navigate(hash) {
  location.hash = hash;
}

// A report was opened: refetch state and refresh only the badge/top bar.
window.addEventListener('reports-read', async () => {
  try {
    state = await api.get('/state');
    syncClock(state.game_now);
    updateTopbar();
  } catch (err) {
    if (err instanceof ApiError) toast(err.message, true);
  }
});

onChanged((msg) => {
  if (msg.village_id !== null && msg.village_id !== villageId) return;
  clearTimeout(wsTimer);
  wsTimer = setTimeout(() => refresh(), WS_DEBOUNCE_MS);
});

// ---- Init ----

// Show the account box, the alliance tab and the pause button according to the login mode.
function updateAccountUi() {
  const auth = !!(me && me.auth_required);
  accountBox.hidden = !(auth && me.account);
  accountName.textContent = me && me.account ? me.account.username : '';
  allianceLink.hidden = !(auth && me.account && state);
  // Only admins may pause in multiplayer mode.
  pauseBtn.hidden = auth && !(me.account && me.account.is_admin);
}

// Load /auth/me; on failure assume single-player mode.
async function loadMe() {
  try {
    me = await api.get('/auth/me');
  } catch {
    me = { auth_required: false, account: null, player: null };
  }
  updateAccountUi();
}

async function init() {
  if (!started) {
    started = true;
    setInterval(tickResources, 1000);
    setInterval(tickClock, 1000);
    setInterval(tickCountdowns, 1000);
  }
  try {
    meta = await api.get('/meta');
  } catch (err) {
    if (err instanceof ApiError) toast(err.message, true);
    return;
  }
  await loadMe();
  if (me.auth_required && !me.account) {
    state = null;
    if (location.hash !== '#/login') navigate('#/login');
    else renderRoute();
    return;
  }
  try {
    state = await api.get('/state');
  } catch (err) {
    state = null;
    if (err instanceof ApiError && err.status === 404) {
      // No player yet: join the running world, or (admin / single-player) create one.
      const joining = me.auth_required && err.code === 'NO_PLAYER';
      const target = joining || (me.auth_required && !me.account.is_admin) ? '#/join' : '#/new';
      if (location.hash !== target) navigate(target);
      else renderRoute();
      return;
    }
    if (err instanceof ApiError && err.status === 401) return;
    if (err instanceof ApiError) toast(err.message, true);
    return;
  }
  syncClock(state.game_now);
  updateTopbar();
  await renderRoute();
}

// Session expired or missing: back to the login page.
window.addEventListener('auth-required', () => {
  if (me && me.auth_required) {
    me.account = null;
    updateAccountUi();
  }
  state = null;
  if (location.hash !== '#/login') navigate('#/login');
});

logoutBtn.addEventListener('click', async () => {
  try {
    await api.post('/auth/logout');
  } catch {
    // Ignore: the cookie is cleared or already invalid.
  }
  state = null;
  village = null;
  villageId = null;
  await loadMe();
  navigate('#/login');
});

pauseBtn.addEventListener('click', onTogglePause);
villageSelect.addEventListener('change', () => navigate(`#/v/${villageSelect.value}`));
window.addEventListener('hashchange', () => renderRoute());

init();
