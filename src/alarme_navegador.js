// Flash View — alarme sonoro do mapa ao vivo.
//
// O navegador só deixa tocar som depois de um clique do usuário: o botão "Ativar alarme" cria e libera o
// AudioContext, que continua liberado enquanto a página estiver aberta (os reruns de 60 s não recarregam a
// página). O estado fica em window.__fvAlarm para sobreviver se o componente do mapa for remontado.
// Mesma regra do alarme do computador (src/alarme.py): toca quando há flash na área nos últimos 10 min e só
// toca de novo depois de 30 min sem flashes na área. Tempo da observação GLM, não do relógio do PC.
// Anéis em volta da área, como na Sala do Céu Nowcasting (distância até a BORDA da área): até 20 km toca a
// sirene, até 50 km mostra um aviso com bipe e até 100 km só um aviso discreto. Cada anel tem a mesma regra.

export const ALARM_CONFIG = {
  minFlashes: 1,
  windowMs: 10 * 60000,
  rearmMs: 30 * 60000,
  maxRingMs: 10 * 60000,   // o som para sozinho depois disso; a janela continua aberta
  testMs: 6000,
  noUpdateMs: 5 * 60000,   // sem rerun do site por esse tempo: alarme sem dados
  dataAgeMs: 12 * 60000,   // dado GLM mais novo com mais que isso: fonte atrasada
  rings: [20, 50, 100],    // km da borda: sirene, aviso com bipe, aviso discreto (nesta ordem)
  noticeMs: 15 * 60000,    // quanto tempo o aviso discreto fica no painel
};
const RING_STORE = 'fv-alarm-rings';

const DIRECTIONS = ['N', 'NE', 'L', 'SE', 'S', 'SO', 'O', 'NO'];
export function directionLabel(deg) {
  const d = ((Number(deg) % 360) + 360) % 360;
  return DIRECTIONS[Math.floor((d + 22.5) / 45) % 8];
}

export function newAlarmState() { return {armed: true, lastHit: null}; }

// flashes: [[ms, dist_km, rumo_graus], ...] dentro da área (últimos 30 min). endMs: fim da última observação.
export function alarmStep(state, flashes, endMs, cfg = ALARM_CONFIG) {
  const s = {...state};
  const valid = (flashes || []).filter(f => Array.isArray(f) && Number.isFinite(Number(f[0])));
  let firstNew = null, newest = null;
  for (const f of valid) {
    const t = Number(f[0]);
    if (s.lastHit === null || t > s.lastHit) {
      firstNew = firstNew === null ? t : Math.min(firstNew, t);
      newest = newest === null ? t : Math.max(newest, t);
    }
  }
  const events = [];
  // Rearma antes de somar os flashes novos: conta o tempo calmo até o primeiro deles.
  const quietUntil = firstNew === null ? endMs : firstNew;
  if (!s.armed && s.lastHit !== null && quietUntil - s.lastHit >= cfg.rearmMs) {
    s.armed = true;
    events.push({kind: 'rearmado'});
  }
  if (newest !== null) s.lastHit = newest;
  const recent = valid.filter(f => {
    const age = endMs - Number(f[0]);
    return age >= -60000 && age < cfg.windowMs;
  });
  if (s.armed && recent.length >= cfg.minFlashes) {
    let nearest = recent[0], lastMs = Number(recent[0][0]);
    for (const f of recent) {
      if (Number(f[1]) < Number(nearest[1])) nearest = f;
      lastMs = Math.max(lastMs, Number(f[0]));
    }
    s.armed = false;
    events.push({kind: 'alarme', count: recent.length, nearestKm: Number(nearest[1]),
      nearestDir: directionLabel(nearest[2]), lastMs});
  }
  return {state: s, events, recentCount: recent.length};
}

// Linhas do site: [ms, km do centro, rumo, km da borda (0 = dentro da área)]. Sem a 4ª coluna, conta como dentro.
export const insideRows = rows => (rows || []).filter(f => Array.isArray(f) && !(Number(f[3]) > 0));

// Um alarmStep por anel ligado, com a distância até a borda no lugar da distância do centro. Os flashes de dentro
// da área também contam: o anel não rearma enquanto a tempestade está sobre a área, e não toca de novo quando ela
// sai. Só aparece o anel mais perto que disparou, e nenhum quando já há flash dentro da área (``insideNow``):
// aí quem avisa é o alarme da área.
export function ringStep(states, rows, endMs, enabled, insideNow, cfg = ALARM_CONFIG) {
  const next = {...states}, events = [];
  let shown = false;
  for (const r of cfg.rings) {
    if (!enabled?.[r]) { next[r] = newAlarmState(); continue; }
    const hits = (rows || []).filter(f => Array.isArray(f) && Number(f[3]) <= r)
      .map(f => [f[0], Number(f[3]), f[2]]);
    const res = alarmStep(next[r] || newAlarmState(), hits, endMs, cfg);
    next[r] = res.state;
    for (const ev of res.events) {
      if (ev.kind !== 'alarme' || insideNow || shown) continue;
      shown = true;
      events.push({...ev, ring: r});
    }
  }
  return {states: next, events};
}

// Flashes nos últimos 10 min em cada anel, só os de fora da área (para o painel).
export function ringCounts(rows, endMs, cfg = ALARM_CONFIG) {
  const out = {};
  for (const r of cfg.rings) out[r] = 0;
  for (const f of rows || []) {
    const km = Number(f?.[3]), age = endMs - Number(f?.[0]);
    if (!(km > 0) || age < -60000 || age >= cfg.windowMs) continue;
    for (const r of cfg.rings) if (km <= r) out[r] += 1;
  }
  return out;
}

// Um ciclo de 1,5 s: bipes agudos alternados (1000/1500 Hz), quase quadrados, e uma pausa. Tocado em loop.
export function sirenSamples(rate) {
  const beep = Math.round(0.18 * rate), gap = Math.round(0.07 * rate), pause = Math.round(0.5 * rate);
  const out = new Float32Array(4 * (beep + gap) + pause);
  let pos = 0;
  for (const freq of [1000, 1500, 1000, 1500]) {
    for (let n = 0; n < beep; n++) {
      const t = n / rate, edge = Math.min(1, Math.min(n, beep - 1 - n) / (0.01 * rate));
      out[pos + n] = 0.95 * edge * Math.tanh(4 * Math.sin(2 * Math.PI * freq * t)) / Math.tanh(4);
    }
    pos += beep + gap;
  }
  return out;
}

const brasilia = ms => new Date(ms).toLocaleTimeString('pt-BR',
  {hour: '2-digit', minute: '2-digit', timeZone: 'America/Sao_Paulo'});

// Anéis ligados: lembrados neste navegador (se o armazenamento estiver liberado); todos ligados na primeira vez.
function loadRings() {
  const on = {};
  for (const r of ALARM_CONFIG.rings) on[r] = true;
  try {
    const saved = JSON.parse(window.localStorage.getItem(RING_STORE) || 'null');
    if (saved && typeof saved === 'object') for (const r of ALARM_CONFIG.rings) if (r in saved) on[r] = !!saved[r];
  } catch { /* armazenamento bloqueado: fica o padrão */ }
  return on;
}

function saveRings(on) {
  try { window.localStorage.setItem(RING_STORE, JSON.stringify(on)); } catch { /* opcional */ }
}

function alarm() {
  if (!window.__fvAlarm) {
    window.__fvAlarm = {enabled: false, ctx: null, buffer: null, state: newAlarmState(), area: null,
      signature: null, endMs: 0, lastUpdate: 0, recentCount: 0, lastAlarmMs: null, ring: null,
      panels: new Set(), wakeLock: null, staleWarned: false, message: '', watchdog: null,
      rings: loadRings(), ringStates: {}, notice: null, listeners: new Set()};
  }
  return window.__fvAlarm;
}

// O mapa desenha os anéis ligados e acompanha o alarme (ligado ou não) por aqui.
export function alarmRingView() {
  const a = alarm();
  return {enabled: ALARM_CONFIG.rings.filter(r => a.rings[r]), on: a.enabled};
}

export function onAlarmChange(fn) {
  const a = alarm();
  a.listeners.add(fn);
  return () => a.listeners.delete(fn);
}

function ensureGlobalStyle() {
  if (document.getElementById('fv-alarm-style')) return;
  const st = document.createElement('style');
  st.id = 'fv-alarm-style';
  st.textContent = `
@keyframes fvAlarmBlink{0%,49%{background:#c62828}50%,100%{background:#7f0000}}
.fv-alarm-overlay{position:fixed;inset:0;z-index:2147483000;display:flex;align-items:center;justify-content:center;
  background:rgba(40,0,0,.55);font-family:"Segoe UI",system-ui,sans-serif;}
.fv-alarm-box{width:min(760px,calc(100vw - 32px));box-sizing:border-box;padding:26px 30px;border-radius:14px;color:#fff;
  animation:fvAlarmBlink 1.2s infinite;box-shadow:0 18px 60px rgba(0,0,0,.6);}
.fv-alarm-box.fv-quiet{animation:none;background:#7f0000;}
.fv-alarm-box.fv-amber{animation:none;background:#8a4b00;}
.fv-alarm-box.fv-amber button{color:#8a4b00;}
.fv-alarm-head{font-size:clamp(24px,5vw,38px);font-weight:800;letter-spacing:.5px;}
.fv-alarm-title{font-size:clamp(17px,3vw,22px);font-weight:700;margin:12px 0 6px;}
.fv-alarm-text{font-size:15px;line-height:1.45;}
.fv-alarm-box button{margin-top:20px;font:700 20px "Segoe UI",system-ui,sans-serif;color:#7f0000;background:#fff;
  border:0;border-radius:10px;padding:12px 28px;cursor:pointer;}
.fv-alarm-foot{margin-top:12px;font-size:12px;color:#ffd7d7;}`;
  document.head.appendChild(st);
}

async function ensureAudio(a) {
  const Ctx = window.AudioContext || window.webkitAudioContext;
  if (!Ctx) throw new Error('Este navegador não toca áudio.');
  if (!a.ctx) {
    a.ctx = new Ctx();
    const data = sirenSamples(a.ctx.sampleRate);
    a.buffer = a.ctx.createBuffer(1, data.length, a.ctx.sampleRate);
    a.buffer.copyToChannel(data, 0);
  }
  if (a.ctx.state !== 'running') await a.ctx.resume();
}

function chirp(a) {
  // Dois bipes curtos: confirma que o som está liberado e o volume está audível.
  const t0 = a.ctx.currentTime + 0.02;
  [[0, 1000], [0.16, 1500]].forEach(([dt, f]) => {
    const o = a.ctx.createOscillator(), g = a.ctx.createGain();
    o.type = 'square'; o.frequency.value = f; g.gain.value = 0.25;
    o.connect(g).connect(a.ctx.destination); o.start(t0 + dt); o.stop(t0 + dt + 0.11);
  });
}

function chime(a) {
  // Dois toques suaves (aviso de 50 km): chama a atenção sem a sirene.
  try {
    const t0 = a.ctx.currentTime + 0.02;
    [[0, 880], [0.22, 1175]].forEach(([dt, f]) => {
      const o = a.ctx.createOscillator(), g = a.ctx.createGain();
      o.type = 'triangle'; o.frequency.value = f;
      g.gain.setValueAtTime(0.0001, t0 + dt);
      g.gain.exponentialRampToValueAtTime(0.4, t0 + dt + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + dt + 0.2);
      o.connect(g).connect(a.ctx.destination); o.start(t0 + dt); o.stop(t0 + dt + 0.22);
    });
  } catch { /* som opcional */ }
}

async function requestWakeLock(a) {
  try {
    if (navigator.wakeLock && !a.wakeLock && document.visibilityState === 'visible') {
      a.wakeLock = await navigator.wakeLock.request('screen');
      a.wakeLock.addEventListener('release', () => { a.wakeLock = null; });
    }
  } catch { a.wakeLock = null; }
}

function notify(title, body, sticky) {
  try {
    if ('Notification' in window && Notification.permission === 'granted') {
      new Notification(title, {body, tag: 'flashview-alarme', requireInteraction: !!sticky});
    }
  } catch { /* notificações são opcionais */ }
}

function stopRing(a) {
  const r = a.ring;
  if (!r) return;
  a.ring = null;
  try { r.source?.stop(); } catch { /* já parou */ }
  clearInterval(r.titleTimer); clearInterval(r.vibrateTimer); clearTimeout(r.maxTimer);
  document.title = r.oldTitle;
  r.overlay.remove();
  if (navigator.vibrate) navigator.vibrate(0);
}

function silence(a, footText) {
  const r = a.ring;
  if (!r) return;
  try { r.source?.stop(); } catch { /* já parou */ }
  clearInterval(r.titleTimer); clearInterval(r.vibrateTimer);
  document.title = r.oldTitle;
  if (navigator.vibrate) navigator.vibrate(0);
  r.box.classList.add('fv-quiet');
  r.foot.textContent = footText;
  r.button.textContent = 'Fechar';
}

// Sirene em loop com a janela vermelha piscando; com ``notice``, só dois toques e uma janela âmbar (aviso de 50 km).
function startRing(a, title, text, {test = false, head: headText = null, notice = false} = {}) {
  stopRing(a);
  ensureGlobalStyle();
  let source = null;
  if (notice) {
    chime(a);
  } else {
    source = a.ctx.createBufferSource();
    const gain = a.ctx.createGain();
    source.buffer = a.buffer; source.loop = true; gain.gain.value = 1;
    source.connect(gain).connect(a.ctx.destination);
    source.start();
  }

  const overlay = document.createElement('div');
  overlay.className = 'fv-alarm-overlay';
  overlay.setAttribute('role', 'alertdialog');
  const box = document.createElement('div'); box.className = notice ? 'fv-alarm-box fv-amber' : 'fv-alarm-box';
  const head = document.createElement('div'); head.className = 'fv-alarm-head';
  head.textContent = headText || (test ? '🔊 TESTE DO ALARME' : '⚡ RELÂMPAGO NA SUA ÁREA');
  const t = document.createElement('div'); t.className = 'fv-alarm-title'; t.textContent = title;
  const p = document.createElement('div'); p.className = 'fv-alarm-text'; p.textContent = text;
  const button = document.createElement('button'); button.type = 'button';
  button.textContent = notice ? 'Fechar' : 'Parar alarme';
  const foot = document.createElement('div'); foot.className = 'fv-alarm-foot';
  const limit = test ? ALARM_CONFIG.testMs : ALARM_CONFIG.maxRingMs;
  foot.textContent = notice ? 'Aviso de aproximação, sem sirene. A sirene toca se cair relâmpago a menos de 20 km ou dentro da área.'
    : test ? 'O teste para sozinho em alguns segundos.'
    : `O som para sozinho às ${brasilia(Date.now() + limit)} (Brasília).`;
  box.append(head, t, p, button, foot); overlay.appendChild(box);
  document.body.appendChild(overlay);
  button.addEventListener('click', () => stopRing(a));
  button.focus();

  const oldTitle = document.title;
  let flip = false;
  const blinkTitle = notice ? '⚠️ Relâmpago perto da área' : '⚡ ALARME — relâmpago na área';
  const titleTimer = setInterval(() => { flip = !flip; document.title = flip ? blinkTitle : oldTitle; }, 1000);
  let vibrateTimer = null;
  if (navigator.vibrate) {
    if (notice) navigator.vibrate([300, 150, 300]);
    else vibrateTimer = setInterval(() => navigator.vibrate([600, 250, 600]), 2000);
  }
  const maxTimer = notice ? null : setTimeout(() => {
    if (test) stopRing(a);
    else silence(a, `Som desligado às ${brasilia(Date.now())} (tempo máximo). Clique para fechar.`);
  }, limit);
  a.ring = {source, overlay, box, foot, button, oldTitle, titleTimer, vibrateTimer, maxTimer};
  if (!test) notify(title, text, !notice);
}

function areaFlashes(a) { return Array.isArray(a.area?.flashes) ? a.area.flashes : []; }

// O site manda no máximo os 3.000 flashes mais recentes de dentro (e de fora); se todos estão na janela, o total
// real é maior.
function countText(a, n, near = false) {
  const rows = areaFlashes(a);
  const sent = near ? rows.length - insideRows(rows).length : insideRows(rows).length;
  const capped = !!(near ? a.area?.nearTruncated : a.area?.truncated) && n >= sent;
  return (capped ? 'mais de ' : '') + n.toLocaleString('pt-BR');
}

const capital = s => s.charAt(0).toUpperCase() + s.slice(1);
const kmText = km => (km < 1 ? 'menos de 1' : Math.round(km).toLocaleString('pt-BR'));
const SOURCE_NOTE = 'Fonte: GLM/GOES (NOAA), com ~1–3 min de atraso; não é alerta oficial.';

function enabledRings(a) { return ALARM_CONFIG.rings.filter(r => a.rings[r]); }

// Anel 1 (20 km): sirene, como dentro da área. Anel 2 (50 km): janela âmbar com bipe. Os outros: aviso discreto.
function fireRing(a, ev) {
  const level = ALARM_CONFIG.rings.indexOf(ev.ring);
  const plural = ev.count === 1 ? 'flash' : 'flashes';
  const title = `Relâmpago a ${kmText(ev.nearestKm)} km da área (${ev.nearestDir})`;
  const text = `${capital(countText(a, ev.count, true))} ${plural} a até ${ev.ring} km da área (${a.area.label}) nos ` +
    `últimos 10 min. Último às ${brasilia(ev.lastMs)} (Brasília). Distância medida até a borda da área. ${SOURCE_NOTE}`;
  if (level === 0) {
    a.lastAlarmMs = Date.now();
    startRing(a, title, text, {head: `⚡ RELÂMPAGO A MENOS DE ${ev.ring} KM`});
  } else if (level === 1) {
    startRing(a, title, text, {head: `⚠️ RELÂMPAGO A MENOS DE ${ev.ring} KM`, notice: true});
  } else {
    a.notice = {text: `ℹ️ ${title} às ${brasilia(ev.lastMs)}.`, until: Date.now() + ALARM_CONFIG.noticeMs};
    notify(title, text, false);
  }
}

function evaluate(a) {
  if (!a.enabled || !a.area || !a.ctx) return;
  const rows = areaFlashes(a);
  const result = alarmStep(a.state, insideRows(rows), a.endMs);
  a.state = result.state;
  a.recentCount = result.recentCount;
  let fired = false;
  for (const ev of result.events) {
    if (ev.kind !== 'alarme') continue;
    fired = true;
    a.lastAlarmMs = Date.now();
    const plural = ev.count === 1 ? 'flash' : 'flashes';
    const title = `Relâmpago a ${Math.round(ev.nearestKm)} km (${ev.nearestDir}) ${a.area.reference || 'do centro da área'}`;
    const text = `${capital(countText(a, ev.count))} ${plural} na área nos últimos 10 min (${a.area.label}). ` +
      `Último às ${brasilia(ev.lastMs)} (Brasília). ${SOURCE_NOTE}`;
    startRing(a, title, text);
  }
  const rings = ringStep(a.ringStates, rows, a.endMs, a.rings, fired || result.recentCount > 0);
  a.ringStates = rings.states;
  for (const ev of rings.events) fireRing(a, ev);
}

function ringsLine(a) {
  const on = enabledRings(a);
  if (!on.length) return '';
  const counts = ringCounts(areaFlashes(a), a.endMs);
  return ' Em volta (10 min): ' + on.map(r => `até ${r} km ${counts[r].toLocaleString('pt-BR')}`).join(' · ') + '.';
}

function statusText(a) {
  if (a.message) return a.message;
  if (!a.enabled) {
    const on = enabledRings(a);
    const around = on.length ? ` e avisa a até ${on[on.length - 1]} km dela` : '';
    return a.area ? `Toca quando cair relâmpago na área (${a.area.label})${around}.`
      : 'Escolha uma área acima do mapa (Pontual, Retângulo, Estados, Municípios ou Arquivo) para usar o alarme.';
  }
  if (!a.area) return 'Alarme pausado: selecione uma área.';
  if (a.ctx && a.ctx.state !== 'running') return 'O navegador bloqueou o som: clique em Desativar e ative de novo.';
  const now = Date.now();
  if (a.lastUpdate && now - a.lastUpdate > ALARM_CONFIG.noUpdateMs) {
    return `⚠️ Sem atualização do site há ${Math.round((now - a.lastUpdate) / 60000)} min: o alarme não está recebendo dados.`;
  }
  if (a.endMs && now - a.endMs > ALARM_CONFIG.dataAgeMs) {
    return `⚠️ Dados GLM atrasados ${Math.round((now - a.endMs) / 60000)} min: o alarme fica cego até voltarem.`;
  }
  const notice = a.notice && now < a.notice.until ? a.notice.text + ' ' : '';
  if (!a.state.armed) {
    return `${notice}Tocou às ${brasilia(a.lastAlarmMs || now)}. Toca de novo depois de 30 min sem flashes na área.` +
      ringsLine(a);
  }
  const n = a.recentCount;
  return `${notice}Vigiando ${a.area.label}: ${countText(a, n)} ${n === 1 ? 'flash' : 'flashes'} na área nos ` +
    `últimos 10 min.${ringsLine(a)}`;
}

function refreshPanels(a) {
  for (const panel of a.panels) {
    const toggle = panel.querySelector('[data-alarm="toggle"]');
    const status = panel.querySelector('.fv-map-alarm-status');
    panel.classList.toggle('fv-alarm-on', a.enabled);
    panel.classList.toggle('fv-alarm-warn', a.enabled && statusText(a).startsWith('⚠️'));
    if (toggle) toggle.textContent = a.enabled ? '🔕 Desativar alarme' : '🔔 Ativar alarme';
    if (status) status.textContent = statusText(a);
    for (const box of panel.querySelectorAll('input[data-ring]')) box.checked = !!a.rings[box.dataset.ring];
  }
  for (const fn of a.listeners) { try { fn(); } catch { /* o mapa pode ter sido desmontado */ } }
}

function watchdog(a) {
  // Verifica a cada 30 s se os dados continuam chegando. Avisa uma vez por queda.
  if (a.watchdog) return;
  a.watchdog = setInterval(() => {
    if (!a.enabled) return;
    const text = statusText(a);
    const stale = text.startsWith('⚠️');
    if (stale && !a.staleWarned) { a.staleWarned = true; notify('Flash View: alarme sem dados', text, false); }
    if (!stale) a.staleWarned = false;
    refreshPanels(a);
  }, 30000);
  document.addEventListener('visibilitychange', () => {
    if (a.enabled && document.visibilityState === 'visible') requestWakeLock(a);
  });
}

async function enable(a) {
  if (!a.area) {
    a.message = 'Primeiro escolha uma área acima do mapa: Pontual, Retângulo, Estados, Municípios ou Arquivo.';
    refreshPanels(a);
    setTimeout(() => { a.message = ''; refreshPanels(a); }, 6000);
    return;
  }
  try {
    await ensureAudio(a);
  } catch (err) {
    a.message = `Não foi possível liberar o som: ${err.message}`;
    refreshPanels(a);
    return;
  }
  chirp(a);
  try { if ('Notification' in window && Notification.permission === 'default') Notification.requestPermission(); }
  catch { /* opcional */ }
  a.enabled = true; a.message = ''; a.state = newAlarmState(); a.ringStates = {}; a.notice = null;
  a.lastAlarmMs = null;
  requestWakeLock(a);
  watchdog(a);
  evaluate(a);
  refreshPanels(a);
}

function disable(a) {
  a.enabled = false;
  stopRing(a);
  if (a.wakeLock) { a.wakeLock.release().catch(() => {}); a.wakeLock = null; }
  refreshPanels(a);
}

async function testSound(a) {
  try { await ensureAudio(a); } catch (err) {
    a.message = `Não foi possível liberar o som: ${err.message}`; refreshPanels(a); return;
  }
  startRing(a, 'É assim que o alarme vai tocar', 'Confira se o volume está alto o bastante para acordar você.',
    {test: true});
}

// Chamado pelo mapa a cada rerun do site (~60 s) com a área e os flashes dentro dela e em volta.
export function alarmUpdate(area, endMs) {
  const a = alarm();
  const signature = area?.signature || null;
  if (signature !== a.signature) {
    a.signature = signature; a.state = newAlarmState(); a.ringStates = {}; a.notice = null; a.lastAlarmMs = null;
  }
  a.area = area || null;
  a.endMs = Number(endMs) || 0;
  a.lastUpdate = Date.now();
  evaluate(a);
  refreshPanels(a);
}

export function bindAlarmPanel(panel) {
  const a = alarm();
  a.panels.add(panel);
  const onClick = e => {
    const b = e.target.closest('button[data-alarm]');
    if (!b) return;
    if (b.dataset.alarm === 'toggle') { if (a.enabled) disable(a); else enable(a); }
    else if (b.dataset.alarm === 'test') testSound(a);
  };
  // Caixas dos anéis: ligar ou desligar um anel recomeça a contagem dele.
  const onChange = e => {
    const box = e.target.closest('input[data-ring]');
    if (!box) return;
    a.rings[box.dataset.ring] = box.checked;
    a.ringStates[box.dataset.ring] = newAlarmState();
    saveRings(a.rings);
    evaluate(a);
    refreshPanels(a);
  };
  panel.addEventListener('click', onClick);
  panel.addEventListener('change', onChange);
  refreshPanels(a);
  return () => {
    panel.removeEventListener('click', onClick); panel.removeEventListener('change', onChange);
    a.panels.delete(panel);
  };
}
