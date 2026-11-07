// Flash View — alarme sonoro do mapa ao vivo.
//
// O navegador só deixa tocar som depois de um clique do usuário: o botão "Ativar alarme" cria e libera o
// AudioContext, que continua liberado enquanto a página estiver aberta (os reruns de 60 s não recarregam a
// página). O estado fica em window.__fvAlarm para sobreviver se o componente do mapa for remontado.
// Mesma regra do alarme do computador (src/alarme.py): toca quando há flash na área nos últimos 10 min e só
// toca de novo depois de 30 min sem flashes na área. Tempo da observação GLM, não do relógio do PC.

export const ALARM_CONFIG = {
  minFlashes: 1,
  windowMs: 10 * 60000,
  rearmMs: 30 * 60000,
  maxRingMs: 10 * 60000,   // o som para sozinho depois disso; a janela continua aberta
  testMs: 6000,
  noUpdateMs: 5 * 60000,   // sem rerun do site por esse tempo: alarme sem dados
  dataAgeMs: 12 * 60000,   // dado GLM mais novo com mais que isso: fonte atrasada
};

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

function alarm() {
  if (!window.__fvAlarm) {
    window.__fvAlarm = {enabled: false, ctx: null, buffer: null, state: newAlarmState(), area: null,
      signature: null, endMs: 0, lastUpdate: 0, recentCount: 0, lastAlarmMs: null, ring: null,
      panels: new Set(), wakeLock: null, staleWarned: false, message: '', watchdog: null};
  }
  return window.__fvAlarm;
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
  try { r.source.stop(); } catch { /* já parou */ }
  clearInterval(r.titleTimer); clearInterval(r.vibrateTimer); clearTimeout(r.maxTimer);
  document.title = r.oldTitle;
  r.overlay.remove();
  if (navigator.vibrate) navigator.vibrate(0);
}

function silence(a, footText) {
  const r = a.ring;
  if (!r) return;
  try { r.source.stop(); } catch { /* já parou */ }
  clearInterval(r.titleTimer); clearInterval(r.vibrateTimer);
  document.title = r.oldTitle;
  if (navigator.vibrate) navigator.vibrate(0);
  r.box.classList.add('fv-quiet');
  r.foot.textContent = footText;
  r.button.textContent = 'Fechar';
}

function startRing(a, title, text, {test = false} = {}) {
  stopRing(a);
  ensureGlobalStyle();
  const source = a.ctx.createBufferSource();
  const gain = a.ctx.createGain();
  source.buffer = a.buffer; source.loop = true; gain.gain.value = 1;
  source.connect(gain).connect(a.ctx.destination);
  source.start();

  const overlay = document.createElement('div');
  overlay.className = 'fv-alarm-overlay';
  overlay.setAttribute('role', 'alertdialog');
  const box = document.createElement('div'); box.className = 'fv-alarm-box';
  const head = document.createElement('div'); head.className = 'fv-alarm-head';
  head.textContent = test ? '🔊 TESTE DO ALARME' : '⚡ RELÂMPAGO NA SUA ÁREA';
  const t = document.createElement('div'); t.className = 'fv-alarm-title'; t.textContent = title;
  const p = document.createElement('div'); p.className = 'fv-alarm-text'; p.textContent = text;
  const button = document.createElement('button'); button.type = 'button'; button.textContent = 'Parar alarme';
  const foot = document.createElement('div'); foot.className = 'fv-alarm-foot';
  const limit = test ? ALARM_CONFIG.testMs : ALARM_CONFIG.maxRingMs;
  foot.textContent = test ? 'O teste para sozinho em alguns segundos.'
    : `O som para sozinho às ${brasilia(Date.now() + limit)} (Brasília).`;
  box.append(head, t, p, button, foot); overlay.appendChild(box);
  document.body.appendChild(overlay);
  button.addEventListener('click', () => stopRing(a));
  button.focus();

  const oldTitle = document.title;
  let flip = false;
  const titleTimer = setInterval(() => {
    flip = !flip; document.title = flip ? '⚡ ALARME — relâmpago na área' : oldTitle;
  }, 1000);
  const vibrateTimer = navigator.vibrate ? setInterval(() => navigator.vibrate([600, 250, 600]), 2000) : null;
  const maxTimer = setTimeout(() => {
    if (test) stopRing(a);
    else silence(a, `Som desligado às ${brasilia(Date.now())} (tempo máximo). Clique para fechar.`);
  }, limit);
  a.ring = {source, overlay, box, foot, button, oldTitle, titleTimer, vibrateTimer, maxTimer};
  if (!test) notify(title, text, true);
}

function areaFlashes(a) { return Array.isArray(a.area?.flashes) ? a.area.flashes : []; }

// O site manda no máximo os 3.000 flashes mais recentes; se todos estão na janela, o total real é maior.
function countText(a, n) {
  const capped = !!a.area?.truncated && n >= areaFlashes(a).length;
  return (capped ? 'mais de ' : '') + n.toLocaleString('pt-BR');
}

function evaluate(a) {
  if (!a.enabled || !a.area || !a.ctx) return;
  const result = alarmStep(a.state, areaFlashes(a), a.endMs);
  a.state = result.state;
  a.recentCount = result.recentCount;
  for (const ev of result.events) {
    if (ev.kind !== 'alarme') continue;
    a.lastAlarmMs = Date.now();
    const plural = ev.count === 1 ? 'flash' : 'flashes';
    const title = `Relâmpago a ${Math.round(ev.nearestKm)} km (${ev.nearestDir}) do centro da área`;
    const count = countText(a, ev.count);
    const text = `${count.charAt(0).toUpperCase() + count.slice(1)} ${plural} na área (${a.area.label}) nos últimos 10 min. ` +
      `Último às ${brasilia(ev.lastMs)} (Brasília). Fonte: GLM/GOES (NOAA), com ~1–3 min de atraso; ` +
      'não é alerta oficial.';
    startRing(a, title, text);
  }
}

function statusText(a) {
  if (a.message) return a.message;
  if (!a.enabled) {
    return a.area ? 'Toca quando cair relâmpago na área selecionada.'
      : 'Selecione uma área no mapa (✚ Selecionar Área) ou importe um polígono para usar o alarme.';
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
  if (!a.state.armed) {
    return `Tocou às ${brasilia(a.lastAlarmMs || now)}. Toca de novo depois de 30 min sem flashes na área.`;
  }
  const n = a.recentCount;
  return `Vigiando ${a.area.label}: ${countText(a, n)} ${n === 1 ? 'flash' : 'flashes'} nos últimos 10 min.`;
}

function refreshPanels(a) {
  for (const panel of a.panels) {
    const toggle = panel.querySelector('[data-alarm="toggle"]');
    const status = panel.querySelector('.fv-map-alarm-status');
    panel.classList.toggle('fv-alarm-on', a.enabled);
    panel.classList.toggle('fv-alarm-warn', a.enabled && statusText(a).startsWith('⚠️'));
    if (toggle) toggle.textContent = a.enabled ? '🔕 Desativar alarme' : '🔔 Ativar alarme';
    if (status) status.textContent = statusText(a);
  }
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
    a.message = 'Primeiro selecione uma área no mapa (✚ Selecionar Área) ou importe um polígono.';
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
  a.enabled = true; a.message = ''; a.state = newAlarmState(); a.lastAlarmMs = null;
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

// Chamado pelo mapa a cada rerun do site (~60 s) com a área e os flashes dentro dela.
export function alarmUpdate(area, endMs) {
  const a = alarm();
  const signature = area?.signature || null;
  if (signature !== a.signature) {
    a.signature = signature; a.state = newAlarmState(); a.lastAlarmMs = null;
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
  panel.addEventListener('click', onClick);
  refreshPanels(a);
  return () => { panel.removeEventListener('click', onClick); a.panels.delete(panel); };
}
