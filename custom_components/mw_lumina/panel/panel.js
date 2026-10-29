/* MW Lúmina — painel visual (Fase 1)
   Fala com o Home Assistant via WebSocket (auth via localStorage do front-end HA). */

"use strict";

/* ------------------------------------------------------------------ */
/* utilidades                                                          */
/* ------------------------------------------------------------------ */

const $ = (sel, el = document) => el.querySelector(sel);
const el = (tag, attrs = {}, children = []) => {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k === "html") node.innerHTML = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== null && v !== false && v !== undefined) node.setAttribute(k, v);
  }
  for (const child of children) if (child) node.append(child);
  return node;
};

function kelvinToRGB(kelvin) {
  const t = Math.max(1000, Math.min(40000, kelvin)) / 100;
  let r, g, b;
  if (t <= 66) {
    r = 255;
    g = 99.4708025861 * Math.log(t) - 161.1195681661;
  } else {
    r = 329.698727446 * Math.pow(t - 60, -0.1332047592);
    g = 288.1221695283 * Math.pow(t - 60, -0.0755148492);
  }
  if (t >= 66) b = 255;
  else if (t <= 19) b = 0;
  else b = 138.5177312231 * Math.log(t - 10) - 305.0447927307;
  const c = (x) => `0${Math.max(0, Math.min(255, Math.round(x))).toString(16)}`.slice(-2);
  return `#${c(r)}${c(g)}${c(b)}`;
}

function kelvinGradient(kelvin) {
  const k2 = Math.max(1800, Math.min(5600, kelvin * 0.9 + 300));
  return `linear-gradient(120deg, ${kelvinToRGB(kelvin)}, ${kelvinToRGB(k2)})`;
}

const DIAS = ["S", "T", "Q", "Q", "S", "S", "D"]; // seg..dom
const DIAS_FULL = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"];

/* ------------------------------------------------------------------ */
/* cliente WebSocket                                                   */
/* ------------------------------------------------------------------ */

class HAConnection {
  constructor() {
    this.seq = 0;
    this.pending = new Map();
    this.socket = null;
  }

  connect() {
    return new Promise((resolve, reject) => {
      const auth = this.readAuth();
      if (!auth || !auth.access_token) {
        reject(new Error("Token de autenticação do HA não encontrado no localStorage."));
        return;
      }
      this.token = auth.access_token;
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/api/websocket`);
      this.socket = ws;
      ws.addEventListener("open", () => {
        ws.send(JSON.stringify({ type: "auth", access_token: this.token }));
      });
      ws.addEventListener("message", (ev) => {
        const data = JSON.parse(ev.data);
        if (data.type === "auth_ok") return resolve();
        if (data.type === "auth_invalid" || data.type === "auth_required") {
          return reject(new Error("Autenticação HA recusada — recarregue o painel do HA."));
        }
        if (data.id && this.pending.has(data.id)) {
          const { resolve: res, reject: rej } = this.pending.get(data.id);
          this.pending.delete(data.id);
          if (data.type === "result" && data.success) res(data.result);
          else rej(new Error(data.error instanceof Object ? data.error.message : "erro WS"));
        }
      });
      ws.addEventListener("error", () => reject(new Error("Falha de conexão com o HA.")));
    });
  }

  readAuth() {
    try {
      const raw = localStorage.getItem("auth") || localStorage.getItem("hassTokens");
      if (!raw) return null;
      return JSON.parse(raw);
    } catch {
      return null;
    }
  }

  send(type, payload = {}) {
    return new Promise((resolve, reject) => {
      const id = ++this.seq;
      this.pending.set(id, { resolve, reject });
      this.socket.send(JSON.stringify({ id, type, ...payload }));
    });
  }
}

/* ------------------------------------------------------------------ */
/* aplicação                                                           */
/* ------------------------------------------------------------------ */

const state = {
  conn: null,
  config: null,
  runtime: null,
  scenes: {},
  tab: "inicio",
  roomPreview: {}, // {room_key: {kelvin, brightness}}
};

async function boot() {
  const app = $("#app");
  const conn = new HAConnection();
  try {
    await conn.connect();
  } catch (err) {
    app.innerHTML = "";
    app.append(
      el("div", { class: "error-screen" },
        el("div", { style: "font-size:2rem;color:var(--amber)" }, "☾"),
        el("h2", {}, "Painel do Lúmina não conseguiu falar com o HA"),
        el("p", { style: "max-width:420px;font-size:.85rem;color:var(--text-2)" }, err.message),
        el("p", {}, el("a", { href: "/config/integrations", target: "_parent" }, "Abrir Configurações do HA")),
      ));
    return;
  }
  state.conn = conn;
  await refresh();
  renderShell();
  setInterval(async () => {
    try { await refreshRuntime(); } catch { /* silencioso */ }
  }, 15000);
}

async function refresh() {
  const res = await state.conn.send("lumina/config_get");
  state.config = res.config;
  state.runtime = res.state;
  state.scenes = res.predefined_scenes;
}

async function refreshRuntime() {
  const res = await state.conn.send("lumina/state_get");
  state.runtime = res.state;
  renderActiveTab();
}

function toast(message, kind = "") {
  const t = el("div", { class: `toast ${kind}` }, message);
  let holder = $(".toasts");
  if (!holder) {
    holder = el("div", { class: "toasts" });
    document.body.append(holder);
  }
  holder.append(t);
  setTimeout(() => t.remove(), 4200);
}

async function savePatch(patch, message = "Configuração salva") {
  try {
    await state.conn.send("lumina/config_save", { patch });
    await refresh();
    renderActiveTab();
    toast(message, "ok");
  } catch (err) {
    toast(`Erro: ${err.message}`, "err");
  }
}

async function applyScene(sceneId, room = null) {
  await state.conn.send("lumina/scene_apply", { scene: sceneId, room, minutes: 90 });
  await refreshRuntime();
  toast(room ? `Cena ${sceneId} → ${room}` : `Cena ${sceneId} → casa toda`, "ok");
}

/* ------------------------------------------------------------------ */
/* shell                                                               */
/* ------------------------------------------------------------------ */

const TABS = [
  { id: "inicio", label: "Início", icon: "mdi:home-heart" },
  { id: "ambientes", label: "Ambientes", icon: "mdi:floor-plan" },
  { id: "luzes", label: "Luzes", icon: "mdi:lightbulb-group" },
  { id: "cenas", label: "Cenas", icon: "mdi:palette" },
  { id: "sistema", label: "Sistema", icon: "mdi:cog" },
];

function renderShell() {
  const app = $("#app");
  app.innerHTML = "";
  const shell = el("div", { class: "shell" },
    el("header", { class: "topbar" },
      el("div", { class: "brand" },
        el("div", { class: "brand-glyph" }, "☾"),
        el("div", {},
          el("h1", {}, "MW Lúmina"),
          el("div", { class: "tagline" }, "a luz que se adapta a você — motor circadiano local, offline-first"),
        ),
      ),
      el("div", { class: "spacer" }),
      el("div", { id: "top-chips" }),
    ),
    el("nav", { class: "tabs" },
      ...TABS.map((t) =>
        el("button", {
          class: `tab ${state.tab === t.id ? "active" : ""}`,
          "data-tab": t.id,
          "aria-label": t.label,
          onclick: () => { state.tab = t.id; renderShell(); },
        },
          el("i", { class: `mdi ${t.icon}`, style: "margin-right:7px" }), t.label),
      ),
    ),
    el("main", { id: "content" }),
  );
  app.append(shell);
  renderTopChips();
  renderActiveTab();
}

function renderTopChips() {
  const holder = $("#top-chips");
  if (!holder || !state.runtime) return;
  const elev = state.runtime.elevation ?? 0;
  holder.innerHTML = "";
  holder.append(
    el("div", { class: "chip" },
      el("i", { class: elev > 0 ? "mdi mdi-white-balance-sunny" : "mdi mdi-weather-night", style: `color:${elev > 0 ? "var(--amber)" : "var(--cyan)"}` }),
      el("span", {}, `Sol ${elev > 0 ? "+" : ""}${elev.toFixed(1)}°`),
    ),
    el("div", { class: "chip" },
      el("span", { class: "dot" }),
      el("span", {}, `${Object.keys(state.config.rooms || {}).length} ambientes`),
    ),
  );
}

function renderActiveTab() {
  renderTopChips();
  const content = $("#content");
  content.innerHTML = "";
  switch (state.tab) {
    case "inicio": renderInicio(content); break;
    case "ambientes": renderAmbientes(content); break;
    case "luzes": renderLuzes(content); break;
    case "cenas": renderCenas(content); break;
    case "sistema": renderSistema(content); break;
  }
}

/* ------------------------------------------------------------------ */
/* aba: Início                                                         */
/* ------------------------------------------------------------------ */

function renderInicio(root) {
  const now = new Date();
  const hour = now.getHours() + now.getMinutes() / 60;

  /* arco solar */
  const card = el("div", { class: "card" },
    el("h2", {}, "A curva do Sol da sua casa"),
    el("div", { class: "sub" }, "elevação solar nas últimas e próximas 24 h — a base do motor circadiano"),
  );
  const canvas = el("canvas", { id: "sun-canvas", width: 620, height: 168 });
  card.append(canvas);
  const profile = state.runtime?.sun_profile || [];
  if (profile.length) {
    drawSunCurve(canvas, profile, hour);
  }

  const statCard = el("div", { class: "card" },
    el("h2", {}, "Agora"),
  );
  const elev = state.runtime?.elevation ?? 0;
  const ambient = state.runtime?.ambient || {};
  const grid = el("div", { class: "status-grid" });
  const addStat = (key, value, opts = {}) => {
    const stat = el("div", { class: "stat" },
      el("div", { class: "k" }, key),
      el("div", { class: "v", html: value }),
    );
    if (opts.swatch) stat.append(el("span", { class: "swatch", style: `background:${kelvinGradient(opts.kelvin)}` }));
    grid.append(stat);
  };
  addStat("Sol", `${elev > 0 ? "+" : ""}${elev.toFixed(1)}° ${elev > 15 ? "dia pleno" : elev > 0 ? "crepúsculo dourado" : elev > -6 ? "crepúsculo" : "noite"}`);
  addStat("Temperatura", ambient.temp != null ? `${ambient.temp.toFixed(0)}°C` : "—, sem sensor");
  addStat("Umidade", ambient.humidity != null ? `${ambient.humidity.toFixed(0)}%` : "—, sem sensor");
  addStat("Clima", ambient.condition ? `${ambient.condition}${ambient.cloud_coverage != null ? ` · ${ambient.cloud_coverage.toFixed(0)}% nuvens` : ""}` : "—, sem clima");
  statCard.append(grid);
  if (!ambient.temp && !ambient.condition) {
    statCard.append(
      el("div", { class: "soon", style: "margin-top:12px" },
        el("i", { class: "mdi" }), "Configure sensores de temperatura, umidade e clima na aba Sistema para modular a luz.",
      ));
  }

  root.append(el("div", { class: "hero" }, card, statCard));

  /* deck de cenas */
  const deckCard = el("div", { class: "card", style: "margin-bottom:20px" },
    el("h2", {}, "Cenários predefinidos"),
    el("div", { class: "sub" }, "clique para aplicar na casa toda (ou escolha o ambiente abaixo)"),
    renderSceneDeck(null),
  );
  root.append(deckCard);

  /* mini cards de ambientes */
  const rooms = state.config.rooms || {};
  const targets = state.runtime?.targets || {};
  const roomsCard = el("div", { class: "card" },
    el("h2", {}, "Ambientes agora"),
    el("div", { class: "sub" }, "alvo que o Lúmina organizou para cada ambiente neste instante"),
  );
  const gridR = el("div", { class: "room-grid" });
  for (const [key, room] of Object.entries(rooms)) {
    const manual = (state.runtime?.rooms_manual || []).includes(key);
    const scene = (state.runtime?.scenes_active || {})[key];
    const leds = targets[key] ? Object.values(targets[key]) : [];
    const kelvin = leds.length ? leds[0].kelvin : null;
    const brightness = leds.length ? leds[0].brightness : null;
    const modePillEl = manual
      ? el("span", { class: "mode-pill manual" }, "manual")
      : scene
        ? el("span", { class: "mode-pill scene" }, `cena ${scene.id}`)
        : el("span", { class: "mode-pill auto" }, "auto");
    gridR.append(
      el("div", { class: "card room-card" },
        el("div", { class: "room-head" },
          el("span", { class: "name" }, room.name),
          el("div", { class: "spacer" }),
          modePillEl,
        ),
        kelvin == null
          ? el("div", { class: "empty-note", style: "padding:16px" }, "todas as luzes apagadas — o Lúmina não acorda luzes desligadas")
          : el("div", { class: "room-target" },
              el("div", { class: "kelvin-big", html: `${kelvin}<small> °K</small>` }),
              el("div", { class: "k-preview", style: `background:${kelvinGradient(kelvin)}` }),
              el("div", { style: "color:var(--text-2);font-size:.8rem" }, `${brightness}% de brilho`),
            ),
        el("div", { class: "room-lights" },
          ...room.lights.map((entityId) => {
            const lt = targets[key]?.[entityId];
            const st = runtimeLightState(entityId);
            return el("div", { class: `light-row ${st === "on" ? "on" : ""}` },
              el("span", { class: "state-dot" }),
              el("span", {}, lightLabel(entityId)),
              el("div", { class: "spacer" }),
              lt ? el("span", { class: "k" }, `${lt.kelvin}K · ${lt.brightness}%`) : el("span", { class: "k" }),
            );
          }),
        ),
        el("div", { class: "room-scenes" },
          ...["por_do_sol", "cinema", "trabalho", "descanso"].map((sid) =>
            el("button", { class: "scene-chip", onclick: () => applyScene(sid, key) }, state.scenes[sid]?.name || sid),
          ),
        ),
        el("div", { class: "room-actions" },
          el("button", { class: "btn tiny", onclick: () => { state.tab = "ambientes"; state.editRoom = key; renderShell(); } }, "Configurar"),
          manual
            ? el("button", { class: "btn tiny primary", onclick: () => setModeAuto(key) }, "Voltar ao Auto")
            : null,
        ),
      ));
  }
  roomsCard.append(gridR);
  root.append(roomsCard);
}

function drawSunCurve(canvas, profile, nowHour) {
  const ctx = canvas.getContext("2d");
  const W = canvas.width, H = canvas.height;
  const pad = 24;
  ctx.clearRect(0, 0, W, H);

  const elevs = profile.map((p) => p.elevation);
  const minE = Math.min(...elevs), maxE = Math.max(...elevs);
  const toY = (e) => H - pad - ((e - minE) / Math.max(maxE - minE, 1)) * (H - 2 * pad);
  const toX = (i) => pad + (i / (profile.length - 1)) * (W - 2 * pad);
  const n = profile.length;
  const startX = pad + ((nowHour - 24) / 24) * (W - 2 * pad);

  /* faixa horizonte */
  ctx.beginPath();
  ctx.fillStyle = "rgba(255,122,144,0.06)";
  ctx.fillRect(0, toY(0), W, H - toY(0));

  /* curva */
  const grad = ctx.createLinearGradient(0, 0, W, 0);
  grad.addColorStop(0, "rgba(110,231,255,0.0)");
  grad.addColorStop(0.15, "rgba(110,231,255,0.8)");
  grad.addColorStop(0.55, "rgba(255,180,84,0.95)");
  grad.addColorStop(0.9, "rgba(180,140,255,0.8)");
  grad.addColorStop(1, "rgba(180,140,255,0.0)");
  ctx.beginPath();
  profile.forEach((p, i) => {
    const x = toX(i), y = toY(elevs[i]);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = grad;
  ctx.lineWidth = 2.5;
  ctx.lineJoin = "round";
  ctx.stroke();

  /* preenchimento sob a curva */
  ctx.lineTo(toX(n - 1), H - pad);
  ctx.lineTo(toX(0), H - pad);
  ctx.closePath();
  ctx.fillStyle = "rgba(255,180,84,0.07)";
  ctx.fill();

  /* marcador "agora" */
  if (startX >= pad && startX <= W - pad) {
    const idx = Math.round(((nowHour - 24) / 24) * (n - 1));
    const e = profile[Math.max(0, Math.min(n - 1, idx))]?.elevation ?? 0;
    ctx.beginPath();
    ctx.arc(startX, toY(e), 5.5, 0, Math.PI * 2);
    ctx.fillStyle = "#ffb454";
    ctx.fill();
    ctx.strokeStyle = "rgba(255,255,255,0.85)";
    ctx.lineWidth = 1.5;
    ctx.stroke();
    ctx.font = "600 11px Inter, sans-serif";
    ctx.fillStyle = "rgba(234,242,255,0.9)";
    ctx.fillText("agora", startX - 12, toY(e) - 12);
  }

  /* horizonte */
  ctx.beginPath();
  ctx.setLineDash([4, 4]);
  ctx.moveTo(pad, toY(0));
  ctx.lineTo(W - pad, toY(0));
  ctx.strokeStyle = "rgba(148,178,255,0.4)";
  ctx.lineWidth = 1;
  ctx.stroke();
  ctx.setLineDash([]);
}

function runtimeLightState(entityId) {
  return state.lightStates?.[entityId]?.state ?? null;
}

function lightLabel(entityId) {
  const nice = entityId.replace(/^light\./, "").replace(/_/g, " ");
  return nice.charAt(0).toUpperCase() + nice.slice(1);
}

async function setModeAuto(roomKey) {
  await state.conn.send("lumina/mode_set", { room: roomKey, mode: "auto" });
  await refreshRuntime();
  toast(`${roomKey} voltou ao modo automático`, "ok");
}

/* ------------------------------------------------------------------ */
/* deck de cenas (usado em Início e Cenas)                             */
/* ------------------------------------------------------------------ */

function renderSceneDeck(roomKey) {
  const deck = el("div", { class: "scene-deck" });
  for (const [sid, scene] of Object.entries(state.scenes)) {
    deck.append(
      el("div", { class: "scene-card", onclick: () => applyScene(sid, roomKey) },
        el("div", { class: "badge" }, "aplicar"),
        el("i", { class: `mdi ${scene.icon} icon`, style: `color:${kelvinToRGB(scene.kelvin)}` }),
        el("div", { class: "preview", style: `background:${kelvinGradient(scene.kelvin)};opacity:${0.35 + scene.brightness / 130}` }),
        el("div", { class: "name" }, scene.name),
        el("div", { class: "desc" }, scene.description),
      ));
  }
  return deck;
}

/* ------------------------------------------------------------------ */
/* aba: Ambientes                                                      */
/* ------------------------------------------------------------------ */

function renderAmbientes(root) {
  const rooms = state.config.rooms || {};
  const roomKeys = Object.keys(rooms);

  root.append(el("div", { class: "rooms-toolbar" },
    el("h2", {}, "Ambientes"),
    el("div", { class: "spacer" }),
    el("button", { class: "btn primary", onclick: openAddRoom },
      el("i", { class: "mdi mdi-plus", style: "margin-right:6px" }), "Adicionar ambiente"),
  ));

  if (!roomKeys.length) {
    root.append(el("div", { class: "empty-note" },
      "Nenhum ambiente ainda. Clique em “Adicionar ambiente” para descobrir as luzes da casa.",
    ));
    return;
  }

  const grid = el("div", { class: "room-grid" });
  for (const key of roomKeys) {
    const room = rooms[key];
    const manual = (state.runtime?.rooms_manual || []).includes(key);
    const scene = (state.runtime?.scenes_active || {})[key];
    const targets = state.runtime?.targets?.[key] || {};

    const head = el("div", { class: "room-head" },
      el("span", { class: "name" }, room.name),
      el("div", { class: "spacer" }),
      manual
        ? el("span", { class: "mode-pill manual" }, "manual")
        : scene
          ? el("span", { class: "mode-pill scene" }, `cena ${scene.id}`)
          : el("span", { class: "mode-pill auto" }, "auto"),
    );

    const lightsRows = room.lights.map((entityId) => {
      const lt = targets[entityId];
      const st = state.lightStates?.[entityId]?.state;
      return el("div", { class: `light-row ${st === "on" ? "on" : ""}` },
        el("span", { class: "state-dot" }),
        el("span", {}, lightLabel(entityId)),
        el("div", { class: "spacer" }),
        lt ? el("span", { class: "k" }, `${lt.kelvin}K · ${lt.brightness}%`) : el("span", { class: "k" }),
      );
    });

    const previewRow = el("div", { class: "room-actions" },
      el("div", { style: "display:flex;gap:10px;align-items:center;width:100%" },
        el("span", { class: "inherit-flag" }, "Testar:"),
        el("input", { type: "range", min: 1800, max: 5600, step: 50, value: state.roomPreview[key]?.kelvin || 3000, "data-room": key, "data-field": "kelvin", style: "flex:1", oninput: (ev) => previewChange(key, ev) }),
        el("input", { type: "range", min: 1, max: 100, step: 1, value: state.roomPreview[key]?.brightness || 60, "data-room": key, "data-field": "brightness", "aria-label": "brilho", style: "width:90px", oninput: (ev) => previewChange(key, ev) }),
        el("button", { class: "btn tiny", onclick: () => sendPreview(key, 60) }, "aplicar 60 s"),
      ),
    );

    const scenesRow = el("div", { class: "room-scenes" },
      ...Object.entries(state.scenes).slice(0, 8).map(([sid, s]) =>
        el("button", { class: "scene-chip", onclick: () => applyScene(sid, key) }, s.name),
      ),
      scene
        ? el("button", { class: "scene-chip", style: "border-color:var(--red);color:var(--red)", onclick: async () => { await state.conn.send("lumina/scene_clear", { room: key }); await refreshRuntime(); renderActiveTab(); } }, "encerrar cena")
        : null,
    );

    const actions = el("div", { class: "room-actions" },
      el("button", { class: "btn tiny", onclick: () => openEditRoom(key) }, "Agenda & detalhes"),
      el("button", { class: "btn tiny", onclick: () => setRoomMode(key, manual ? "auto" : "manual") }, manual ? "Voltar ao Auto" : "Manual"),
      el("button", { class: "btn tiny danger", onclick: () => removeRoom(key) }, "Remover"),
    );

    grid.append(el("div", { class: "card room-card" }, head, el("div", { class: "room-lights" }, ...lightsRows), previewRow, scenesRow, actions));
  }
  root.append(grid);
}

async function previewChange(roomKey, ev) {
  const field = ev.target.dataset.field;
  const val = Number(ev.target.value);
  const prev = state.roomPreview[roomKey] || { kelvin: 3000, brightness: 60 };
  if (field === "kelvin") {
    const kSlider = $(`input[data-room="${roomKey}"][data-field="kelvin"]`);
    kSlider.style.background = kelvinGradient(val);
  }
  state.roomPreview[roomKey] = { ...prev, [field]: val };
}

async function sendPreview(roomKey, seconds) {
  const prev = state.roomPreview[roomKey] || { kelvin: 3000, brightness: 60 };
  await state.conn.send("lumina/preview", { room: roomKey, kelvin: prev.kelvin, brightness: prev.brightness, seconds });
  toast(`Pré-visualização em ${roomKey}: ${prev.kelvin}K · ${prev.brightness}% por ${seconds}s`, "ok");
}

async function setRoomMode(roomKey, mode) {
  await state.conn.send("lumina/mode_set", { room: roomKey, mode });
  await refreshRuntime();
  toast(`${roomKey}: modo ${mode}`, "ok");
}

async function removeRoom(roomKey) {
  if (!confirm(`Remover o ambiente ${roomKey}? (as luzes continuarão no HA)`)) return;
  await savePatch({ rooms: { [roomKey]: null } }, "Ambiente removido");
}

/* ------------------------------------------------------------------ */
/* editor de ambiente (blocos, luzes)                                   */
/* ------------------------------------------------------------------ */

function buildDayEditor(days) {
  const isNew = !block || !wrap;
  if (!block) {
    block = {
      id: `bloco_${Date.now().toString(36)}`,
      name: "",
      days: [0, 1, 2, 3, 4],
      start: "20:00",
      end: "23:00",
      kind: "circadian",
      kelvin_shift: -200,
      brightness_mult: 0.8,
    };
  }
  const form = el("form", { class: "form-grid" });
  const nameInput = el("input", { type: "text", value: block.name || "", placeholder: "Nome do bloco (ex.: Noite descendo)" });
  const startInput = el("input", { type: "time", value: block.start || "20:00" });
  const endInput = el("input", { type: "time", value: block.end || "23:00" });
  const kindSelect = el("select", {},
    el("option", { value: "circadian" }, "Circadian (segue o sol, com ajustes)"),
    el("option", { value: "fixed" }, "Fixo (Kelvin e brilho fixos)"),
    el("option", { value: "scene" }, "Cena (ativa uma cena)"),
  );
  kindSelect.value = block.kind || "circadian";
  const shiftInput = el("input", { type: "number", value: block.kelvin_shift ?? -200, step: 50, min: -1000, max: 1000 });
  const multInput = el("input", { type: "number", value: block.brightness_mult ?? 0.8, step: 0.05, min: 0.05, max: 2 });
  const fixedKelvin = el("input", { type: "number", value: block.kelvin ?? 2700, step: 50, min: 1500, max: 6500 });
  const fixedBright = el("input", { type: "number", value: block.brightness ?? 50, min: 1, max: 100 });
  const sceneSelect = el("select", {},
    ...Object.entries(state.scenes).map(([sid, s]) => el("option", { value: sid }, s.name)),
  );
  sceneSelect.value = block.scene || "cinema";

  const kindExtras = () => {    form.querySelectorAll("[data-extra]").forEach((n) => n.remove());
    if (kindSelect.value === "circadian") {
      form.append(
        el("div", { class: "field", "data-extra": "1" }, el("label", {}, "Shift Kelvin (− frio → mais quente)"), shiftInput),
        el("div", { class: "field", "data-extra": "1" }, el("label", {}, "Multiplicador de brilho"), multInput),
      );
    } else if (kindSelect.value === "fixed") {
      form.append(
        el("div", { class: "field", "data-extra": "1" }, el("label", {}, "Kelvin fixo"), fixedKelvin),
        el("div", { class: "field", "data-extra": "1" }, el("label", {}, "Brilho fixo (%)"), fixedBright),
      );
    } else {
      form.append(el("div", { class: "field", "data-extra": "1" }, el("label", {}, "Cena do bloco"), sceneSelect));
    }
  };
  kindSelect.addEventListener("change", kindExtras);
  kindExtras();

  form.append(
    el("div", { class: "field" }, el("label", {}, "Nome"), nameInput),
    el("div", { class: "field" }, el("label", {}, "Dias da semana"), buildDayEditor(block.days)),
    el("div", { class: "field" }, el("label", {}, "Início"), startInput),
    el("div", { class: "field" }, el("label", {}, "Fim (pode virar a madrugada)"), endInput),
    el("div", { class: "field" }, el("label", {}, "Tipo"), kindSelect),
  );

  openModal(el("div", {},
    el("h3", {}, block.name ? "Editar bloco" : "Novo bloco de horário"),
    form,
    el("div", { class: "actions" },
      el("button", { class: "btn ghost", type: "button", onclick: closeModal }, "Cancelar"),
      el("button", { class: "btn primary", type: "button", onclick: () => {
        const dayEditor = form.querySelector("[data-days]");
        const daysOn = [...dayEditor.querySelectorAll(".on")].map((c) => Number(c.dataset.day));
        const newBlock = {
          id: block.id,
          name: nameInput.value || block.id,
          days: daysOn.length ? daysOn : [0, 1, 2, 3, 4, 5, 6],
          start: startInput.value || "20:00",
          end: endInput.value || "23:00",
          kind: kindSelect.value,
        };
        if (kindSelect.value === "circadian") {
          newBlock.kelvin_shift = Number(shiftInput.value);
          newBlock.brightness_mult = Number(multInput.value);
        } else if (kindSelect.value === "fixed") {
          newBlock.kelvin = Number(fixedKelvin.value);
          newBlock.brightness = Number(fixedBright.value);
        } else {
          newBlock.scene = sceneSelect.value;
        }
        state._blockDraft = newBlock;
        commitBlockModal(roomKey, block, newBlock);
        closeModal();
      } }, "Salvar bloco"),
    ),
  ));
}

function buildDayEditor(days) {
  const holder = el("div", { class: "day-chips", "data-days": "1" });
  const on = new Set(days && days.length ? days : [0, 1, 2, 3, 4, 5, 6]);
  DIAS.forEach((d, i) => {
    holder.append(el("span", {
      class: `day-chip ${on.has(i) ? "on" : ""}`,
      "data-day": i,
      onclick: (ev) => ev.target.classList.toggle("on"),
    }, d));
  });
  return holder;
}

async function commitBlockModal(roomKey, oldBlock, newBlock) {
  const targetId = (oldBlock && oldBlock.id) || newBlock.id;
  if (roomKey === "__house__") {
    return houseSchedulePatch(() => {
      const blocks = state.config.house.schedule.blocks;
      const i = blocks.findIndex((b) => b.id === targetId);
      if (i >= 0) blocks[i] = newBlock; else blocks.push(newBlock);
    });
  }
  return savePatch(
    { rooms: { [roomKey]: { schedule: { blocks: upsertBlock(state.config.rooms[roomKey].schedule.blocks, oldBlock, newBlock) } } } },
    "Bloco salvo",
  );
}

function upsertBlock(blocks, oldBlock, newBlock) {
  const list = [...(blocks || [])];
  const existing = oldBlock && oldBlock.id
    ? list.findIndex((b) => b.id === oldBlock.id)
    : -1;
  if (existing >= 0) list[existing] = newBlock;
  else list.push(newBlock);
  return list;
}

async function houseSchedulePatch(mutator) {
  const house = JSON.parse(JSON.stringify(state.config.house));
  house.schedule = house.schedule || { blocks: [] };
  house.schedule.blocks = house.schedule.blocks || [];
  mutator(house);
  await savePatch({ house }, "Agenda da casa salva");
}

function openEditRoom(roomKey) {
  const room = state.config.rooms[roomKey];
  const blocks = [...(room.schedule?.blocks || [])];
  const nameInput = el("input", { type: "text", value: room.name || roomKey });
  const kMin = el("input", { type: "number", value: room.clip?.kelvin_min ?? "", placeholder: "automático" });
  const kMax = el("input", { type: "number", value: room.clip?.kelvin_max ?? "", placeholder: "automático" });
  const bMax = el("input", { type: "number", value: room.clip?.brightness_max ?? "", placeholder: "100" });

  const lightPick = el("div", { class: "day-chips", style: "gap:6px" });
  state_entityList().then((lights) => {
    const chosen = new Set(room.lights);
    lightPick.innerHTML = "";
    lights.forEach((l) => {
      const chip = el("span", {
        class: `day-chip ${chosen.has(l.entity_id) ? "on" : ""}`,
        style: "width:auto;padding:0 10px;height:26px;font-size:.7rem",
        "data-entity": l.entity_id,
        onclick: (ev) => ev.target.classList.toggle("on"),
      }, l.name || lightLabel(l.entity_id));
      lightPick.append(chip);
    });
    addRoomBtn(); // input de luz livre
  });
  function addRoomBtn() {
    if (lightPick.querySelector(".add-light")) return;
    lightPick.append(el("span", {
      class: "day-chip add-light",
      style: "width:auto;padding:0 10px;height:26px;color:var(--amber)",
      onclick: () => {
        const id = prompt("entity_id da luz (ex.: light.escritorio_luzes_do_escritorio):");
        if (id) lightPick.append(el("span", {
          class: "day-chip on",
          style: "width:auto;padding:0 10px;height:26px;font-size:.7rem",
          "data-entity": id,
          onclick: (ev) => ev.target.classList.toggle("on"),
        }, lightLabel(id)));
      },
    }, "+ luz"));
  }

  const blockList = el("div", { class: "block-list" });
  [...blocks].forEach((block) => blockList.append(renderBlockRow(roomKey, block, block.id)));

  openModal(el("div", {},
    el("h3", {}, `Ambiente · ${room.name}`),
    el("div", { class: "form-grid" },
      el("div", { class: "field" }, el("label", {}, "Nome do ambiente"), nameInput),
      el("div", { class: "field" }, el("label", {}, "Chave (id)"), el("input", { value: roomKey, disabled: true })),
    ),
    el("div", { class: "field", style: "margin-top:12px" },
      el("label", {}, `Luzes deste ambiente (${room.lights.length})`),
      lightPick,
    ),
    el("div", { class: "form-grid", style: "margin-top:12px" },
      el("div", { class: "field" }, el("label", {}, "Clip Kelvin mín (°K)"), kMin),
      el("div", { class: "field" }, el("label", {}, "Clip Kelvin máx (°K)"), kMax),
      el("div", { class: "field" }, el("label", {}, "Clip brilho máx (%)"), bMax),
    ),
    el("div", { class: "section-title" }, "Blocos de horário deste ambiente"),
    blockList,
    el("div", { style: "margin-top:10px" },
      el("button", { class: "btn", onclick: () => editBlockModal(roomKey, null, null) },
        el("i", { class: "mdi mdi-plus", style: "margin-right:4px" }), "Novo bloco"),
    ),
    el("div", { class: "actions" },
      el("button", { class: "btn ghost", onclick: closeModal }, "Fechar"),
      el("button", { class: "btn primary", onclick: async () => {
        const chosen = [...lightPick.querySelectorAll(".on[data-entity]")].map((c) => c.dataset.entity);
        const patch = { rooms: { [roomKey]: { name: nameInput.value || roomKey } } };
        // full replace da lista de luzes e blocos
        patch.rooms[roomKey].lights = chosen.length ? chosen : room.lights;
        patch.rooms[roomKey].schedule = { blocks: room.schedule?.blocks || [] };
        const clip = {};
        if (kMin.value !== "") clip.kelvin_min = Number(kMin.value);
        if (kMax.value !== "") clip.kelvin_max = Number(kMax.value);
        if (bMax.value !== "") clip.brightness_max = Number(bMax.value);
        patch.rooms[roomKey].clip = clip;
        await savePatch(patch, "Ambiente atualizado");
        closeModal();
      } }, "Salvar ambiente"),
    ),
  ));
}

function renderBlockRow(roomKey, block, id) {
  const days = (block.days || []);
  return el("div", { class: "block-item" },
    el("i", { class: `mdi ${block.kind === "scene" ? "mdi-movie-open-outline" : "mdi-clock-outline"}`, style: "color:var(--amber)" }),
    el("div", { class: "meta" },
      el("b", {}, block.name || block.id || "bloco"),
      el("small", {}, `${block.start}→${block.end} · ${block.kind}`),
      el("div", { class: "day-chips" },
        ...DIAS.map((d, i) => el("span", { class: `day-chip ${days.includes(i) ? "on" : ""}`, style: "width:20px;height:20px;font-size:.6rem" }, d)),
      ),
    ),
    el("div", { style: "display:flex;gap:6px" },
      el("button", { class: "btn tiny", onclick: () => editBlockModal(roomKey, block, null) }, "editar"),
      el("button", { class: "btn tiny danger", onclick: async () => {
        const blocks = (room_key_blocks(roomKey) || []).filter((b) => b.id !== block.id);
        if (roomKey === "__house__") return houseSchedulePatch((house) => { house.schedule.blocks = blocks; });
        await savePatch({ rooms: { [roomKey]: { schedule: { blocks } } } }, "Bloco removido");
      } }, "remover"),
    ),
  );
}

function room_key_blocks(roomKey) {
  return roomKey === "__house__"
    ? state.config.house.schedule?.blocks
    : state.config.rooms?.[roomKey]?.schedule?.blocks;
}

/* ------------------------------------------------------------------ */
/* adicionar ambiente                                                  */
/* ------------------------------------------------------------------ */

async function openAddRoom() {
  let areaList = [];
  try {
    const res = await state.conn.send("lumina/discover");
    areaList = res.areas;
    state.lightsAll = res.lights;
  } catch (err) {
    toast(`Erro: ${err.message}`, "err");
    return;
  }
  const areaSelect = el("select", {},
    ...areaList.map((a) => el("option", { value: a.id }, a.name)),
  );
  const nameInput = el("input", { type: "text", placeholder: "Nome (ex.: Escritório)" });
  const pick = el("div", { class: "day-chips", style: "gap:6px;margin-top:8px" });

  const refreshPick = () => {
    pick.innerHTML = "";
    const area = areaSelect.value;
    const lights = (state.lightsAll || []).filter((l) => l.area_id === area);
    if (!lights.length) {
      pick.append(el("span", { style: "color:var(--text-2);font-size:.8rem" }, "sem luzes nesta área — escolha outra ou adicione manualmente depois"));
    }
    lights.forEach((l) => {
      pick.append(el("span", {
        class: "day-chip on",
        style: "width:auto;padding:0 10px;height:26px;font-size:.7rem",
        "data-entity": l.entity_id,
        onclick: (ev) => ev.target.classList.toggle("on"),
      }, `${lightLabel(l.entity_id)}${l.min_kelvin ? " · " + l.min_kelvin + "–" + l.max_kelvin + "K" : ""}`));
    });
  };
  areaSelect.addEventListener("change", refreshPick);
  refreshPick();

  openModal(el("div", {},
    el("h3", {}, "Adicionar ambiente"),
    el("div", { class: "form-grid" },
      el("div", { class: "field" }, el("label", {}, "Área do Home Assistant"), areaSelect),
      el("div", { class: "field" }, el("label", {}, "Nome"), nameInput),
    ),
    el("div", { class: "field", style: "margin-top:10px" }, el("label", {}, "Luzes"), pick),
    el("div", { class: "actions" },
      el("button", { class: "btn ghost", onclick: closeModal }, "Cancelar"),
      el("button", { class: "btn primary", onclick: async () => {
        const areaId = areaSelect.value;
        const areaName = nameInput.value || areaList.find((a) => a.id === areaId)?.name || areaId;
        const key = nameInput.value
          ? nameInput.value.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-zA-Z0-9]+/g, "_").toLowerCase().replace(/^_+|_+$/g, "")
          : areaId;
        const entityList = [...pick.querySelectorAll(".on[data-entity]")].map((c) => c.dataset.entity);
        if (!entityList.length) {
          toast("Escolha ao menos uma luz", "err");
          return;
        }
        await savePatch({ rooms: { [key]: { name: areaName, area_id: areaId, lights: entityList, kind: "inherit", schedule: { blocks: [] }, clip: {} } } }, `Ambiente ${areaName} criado`);
        closeModal();
      } }, "Criar ambiente"),
    ),
  ));
}

async function state_entityList() {
  if (!state.lightsAll) {
    const res = await state.conn.send("lumina/discover");
    state.lightsAll = res.lights;
  }
  return state.lightsAll;
}

/* ------------------------------------------------------------------ */
/* aba: Luzes (matriz)                                                 */
/* ------------------------------------------------------------------ */

function renderLuzes(root) {
  const lightsCfg = state.config.lights || {};
  const rooms = state.config.rooms || {};
  const lightToRoom = {};
  for (const [key, room] of Object.entries(rooms)) {
    (room.lights || []).forEach((l) => { lightToRoom[l] = key; });
  }

  root.append(el("div", { class: "rooms-toolbar" },
    el("h2", {}, "Matriz de luzes"),
    el("div", { class: "spacer" }),
    el("button", { class: "btn primary", onclick: () => openLightEditor(null) }, "Adicionar luz"),
  ));

  const matrix = el("div", { class: "matrix" });
  const ids = new Set([...Object.keys(lightsCfg), ...Object.keys(lightToRoom)]);
  if (!ids.size) {
    root.append(el("div", { class: "empty-note" }, "Nenhuma luz configurada individualmente — as luzes seguem o ambiente."));
    return;
  }
  for (const entityId of ids) {
    const cfg = lightsCfg[entityId] || {};
    const roomKey = lightToRoom[entityId] || "—";
    matrix.append(el("div", { class: "matrix-row" },
      el("div", { class: "entity" },
        lightLabel(entityId),
        el("small", {}, entityId),
      ),
      roomKey !== "—"
        ? el("span", { class: "room-tag" }, rooms[roomKey]?.name || roomKey)
        : el("span", { class: "room-tag", style: "opacity:.5" }, "sem ambiente"),
      cfg.clip && Object.keys(cfg.clip).length
        ? el("span", { class: "inherit-flag" }, `clipes: ${Object.entries(cfg.clip).map(([k, v]) => `${k}=${v}`).join(" · ")}`)
        : el("span", { class: "inherit-flag" }, "herdando do ambiente"),
      el("button", { class: "btn tiny", onclick: () => openLightEditor(entityId) }, "editar"),
    ));
  }
  root.append(matrix);
}

function openLightEditor(entityId) {
  const isNew = !entityId;
  const cfg = isNew ? {} : (state.config.lights?.[entityId] || {});
  const idInput = el("input", { type: "text", value: entityId || "", placeholder: "light.escritorio_coluninhas" });
  const kMin = el("input", { type: "number", value: cfg.clip?.kelvin_min ?? "", placeholder: "2000" });
  const kMax = el("input", { type: "number", value: cfg.clip?.kelvin_max ?? "", placeholder: "5600" });
  const bMax = el("input", { type: "number", value: cfg.clip?.brightness_max ?? "", placeholder: "80" });

  openModal(el("div", {},
    el("h3", {}, isNew ? "Adicionar luz individual" : `Luz · ${lightLabel(entityId)}`),
    el("div", { class: "form-grid" },
      el("div", { class: "field" }, el("label", {}, "entity_id"), idInput),
    ),
    el("div", { class: "form-grid", style: "margin-top:12px" },
      el("div", { class: "field" }, el("label", {}, "Clip Kelvin mín"), kMin),
      el("div", { class: "field" }, el("label", {}, "Clip Kelvin máx"), kMax),
      el("div", { class: "field" }, el("label", {}, "Clip brilho máx (%)"), bMax),
    ),
    el("p", { style: "color:var(--text-2);font-size:.76rem;margin-top:10px" },
      "Clipes individuais vencem ambiente e casa: use quando uma luz tem hardware limitado ou papel especial."),
    el("div", { class: "actions" },
      el("button", { class: "btn ghost", onclick: closeModal }, "Cancelar"),
      isNew
        ? el("button", { class: "btn primary", onclick: async () => {
            const id = idInput.value.trim();
            if (!id || !id.startsWith("light.")) { toast("entity_id deve começar com light.", "err"); return; }
            const patch = { lights: { [id]: {} } };
            const clip = {};
            if (kMin.value !== "") clip.kelvin_min = Number(kMin.value);
            if (kMax.value !== "") clip.kelvin_max = Number(kMax.value);
            if (bMax.value !== "") clip.brightness_max = Number(bMax.value);
            if (Object.keys(clip).length) patch.lights[id].clip = clip;
            await savePatch(patch, `Luz ${id} adicionada`);
            closeModal();
          } }, "Adicionar")
        : el("button", { class: "btn primary", onclick: async () => {
            const clip = {};
            const patchLights = { [entityId]: {} };
            if (kMin.value !== "") clip.kelvin_min = Number(kMin.value);
            if (kMax.value !== "") clip.kelvin_max = Number(kMax.value);
            if (bMax.value !== "") clip.brightness_max = Number(bMax.value);
            if (Object.keys(clip).length) patchLights[entityId].clip = clip;
            await savePatch({ lights: patchLights }, "Luz atualizada");
            closeModal();
          } }, "Salvar"),
    ),
  ));
}

/* ------------------------------------------------------------------ */
/* aba: Cenas                                                          */
/* ------------------------------------------------------------------ */

function renderCenas(root) {
  root.append(el("div", { class: "rooms-toolbar" },
    el("h2", {}, "Cenários"),
    el("div", { class: "spacer" }),
    el("button", { class: "btn primary", onclick: () => openSceneEditor(null) }, "Criar cena"),
  ));
  root.append(el("div", { class: "card" },
    el("h2", {}, "Predefinidas"),
    el("div", { class: "sub" }, "as 11 cenas do motor — clicar aplica na casa toda"),
    renderSceneDeck(null),
  ));
  const custom = state.config.scenes || {};
  if (Object.keys(custom).length) {
    root.append(el("div", { class: "card", style: "margin-top:16px" },
      el("h2", {}, "Suas cenas"),
      el("div", { class: "sub" }, "cenas criadas por você"),
      renderSceneDeckCustom(custom),
    ));
  }
}

function renderSceneDeckCustom(custom) {
  const deck = el("div", { class: "scene-deck" });
  for (const [sid, scene] of Object.entries(custom)) {
    deck.append(el("div", { class: "scene-card", onclick: () => applyScene(sid, null) },
      el("div", { class: "badge" }, "aplicar"),
      el("i", { class: `mdi ${scene.icon || "mdi:lightbulb-on"} icon`, style: `color:${kelvinToRGB(scene.kelvin)}` }),
      el("div", { class: "preview", style: `background:${kelvinGradient(scene.kelvin)};opacity:${0.35 + scene.brightness / 130}` }),
      el("div", { class: "name" }, scene.name || sid),
      el("div", { class: "desc" }, scene.description || ""),
      el("div", { style: "margin-top:8px;display:flex;gap:6px" },
        el("button", { class: "btn tiny", onclick: (ev) => { ev.stopPropagation(); openSceneEditor(sid); } }, "editar"),
        el("button", { class: "btn tiny danger", onclick: async (ev) => {
          ev.stopPropagation();
          await savePatch({ scenes: { [sid]: null } }, "Cena removida");
        } }, "remover"),
      ),
    ));
  }
  return deck;
}

function openSceneEditor(sceneId) {
  const isNew = !sceneId;
  const custom = state.config.scenes || [];
  const scene = isNew
    ? { name: "", icon: "mdi:lightbulb-on", kelvin: 2700, brightness: 50, description: "", transition: 3 }
    : custom[sceneId];
  const nameInput = el("input", { type: "text", value: scene.name || "" });
  const descInput = el("input", { type: "text", value: scene.description || "" });
  const kInput = el("input", { type: "range", min: 1700, max: 5600, step: 50, value: scene.kelvin || 2700 });
  const bInput = el("input", { type: "range", min: 1, max: 100, step: 1, value: scene.brightness || 50 });
  const swatch = el("div", { style: `height:46px;border-radius:12px;background:${kelvinGradient(scene.kelvin)}` });
  const readout = el("div", { style: "display:flex;justify-content:space-between;font-size:.8rem;color:var(--text-1)" },
    el("span", { html: `Kelvin: <b>${scene.kelvin}</b>` }),
    el("span", { html: `Brilho: <b>${scene.brightness}%</b>` }),
  );
  kInput.addEventListener("input", () => {
    swatch.style.background = kelvinGradient(Number(kInput.value));
    readout.children[0].innerHTML = `Kelvin: <b>${kInput.value}</b>`;
  });
  bInput.addEventListener("input", () => {
    readout.children[1].innerHTML = `Brilho: <b>${bInput.value}%</b>`;
  });

  openModal(el("div", {},
    el("h3", {}, isNew ? "Criar cena customizada" : "Editar cena"),
    swatch,
    el("div", { class: "form-grid", style: "margin-top:14px" },
      el("div", { class: "field" }, el("label", {}, "Nome"), nameInput),
      el("div", { class: "field" }, el("label", {}, "Descrição curta"), descInput),
      el("div", { class: "slider-block" }, el("label", {}, "Kelvin (°K)"), kInput),
    el("div", { class: "slider-block" }, el("label", {}, "Brilho (%)"), bInput),
    ),
    readout,
    el("div", { class: "actions" },
      el("button", { class: "btn ghost", onclick: closeModal }, "Cancelar"),
      el("button", { class: "btn primary", onclick: async () => {
        const name = nameInput.value.trim();
        if (!name) { toast("Dê um nome à cena", "err"); return; }
        const id = isNew
          ? name.normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/[^a-zA-Z0-9]+/g, "_").toLowerCase().replace(/^_+|_+$/g, "") || `cena_${Date.now().toString(36)}`
          : sceneId;
        await savePatch({ scenes: { [id]: {
          name,
          description: descInput.value,
          kelvin: Number(kInput.value),
          brightness: Number(bInput.value),
          icon: scene.icon || "mdi:lightbulb-on",
          transition: 3,
        } } }, `Cena ${name} salva`);
        closeModal();
      } }, "Salvar cena"),
    ),
  ));
}

/* ------------------------------------------------------------------ */
/* aba: Sistema                                                        */
/* ------------------------------------------------------------------ */

function renderSistema(root) {
  const house = state.config.house || {};
  const nameInput = el("input", { type: "text", value: house.name || "" });
  const tempInput = el("input", { type: "text", value: house.ambient?.temp_sensor || "", placeholder: "sensor.temperatura" });
  const humInput = el("input", { type: "text", value: house.ambient?.humidity_sensor || "", placeholder: "sensor.umidade" });
  const weatherInput = el("input", { type: "text", value: house.ambient?.weather_entity || "", placeholder: "weather.casa" });
  const lockEnabled = el("input", { type: "checkbox", checked: !!house.night_lock?.enabled });
  const lockStart = el("input", { type: "time", value: house.night_lock?.start || "23:45" });
  const lockEnd = el("input", { type: "time", value: house.night_lock?.end || "06:00" });

  root.append(
    el("div", { class: "card", style: "margin-bottom:16px" },
      el("h2", {}, "Casa"),
      el("div", { class: "sub" }, "identidade e sensores que modulam a curva circadiana"),
      el("div", { class: "form-grid" },
        el("div", { class: "field" }, el("label", {}, "Nome da casa"), nameInput),
        el("div", { class: "field" }, el("label", {}, "Sensor de temperatura (opcional)"), tempInput),
        el("div", { class: "field" }, el("label", {}, "Sensor de umidade (opcional)"), humInput),
        el("div", { class: "field" }, el("label", {}, "Entidade de clima (opcional)"), weatherInput),
      ),
    ),
    el("div", { class: "card", style: "margin-bottom:16px" },
      el("h2", {}, "Proteção noturna"),
      el("div", { class: "sub" }, "na janela de sono, limita luz a ≤2200K e ≤15% — vence cena e agenda"),
      el("div", { class: "form-grid" },
        el("div", { class: "field" }, el("label", {}, "Ativa"), lockEnabled),
        el("div", { class: "field" }, el("label", {}, "Início"), lockStart),
        el("div", { class: "field" }, el("label", {}, "Fim (pode cruzar a meia-noite)"), lockEnd),
      ),
    ),
    el("div", { style: "display:flex;gap:10px;margin-bottom:20px" },
      el("button", { class: "btn primary", onclick: async () => {
        const patch = { house: {
          name: nameInput.value || "Minha Casa",
          ambient: { temp_sensor: tempInput.value || null, humidity_sensor: humInput.value || null, weather_entity: weatherInput.value || null },
          night_lock: { enabled: lockEnabled.checked, start: lockStart.value, end: lockEnd.value },
        } };
        await savePatch(patch, "Casa atualizada");
      } }, "Salvar sistema"),
      el("button", { class: "btn", onclick: async () => {
        await savePatch({ house: { schedule: { blocks: null } } }, "Agenda da casa limpa (circadiano puro)");
      } }, "Resetar agenda da casa"),
    ),
    el("div", { class: "card", style: "margin-bottom:16px" },
      el("h2", {}, "Agenda da casa"),
      el("div", { class: "sub" }, "blocos que valem para todos os ambientes (ambiente e luz podem sobrepor)"),
      el("div", { class: "block-list" },
        ...((house.schedule?.blocks) || []).map((b) => renderBlockRow("__house__", b, b.id)),
      ),
      el("div", { style: "margin-top:10px" },
        el("button", { class: "btn", onclick: () => editBlockModal("__house__", null, null) },
          el("i", { class: "mdi mdi-plus", style: "margin-right:4px" }), "Novo bloco da casa"),
      ),
    ),
    el("div", { class: "card", style: "margin-bottom:16px" },
      el("h2", {}, "Fase 2 — IA e Câmeras (em construção)"),
      el("div", { class: "soon" },
        el("i", { class: "mdi mdi-eye-outline" }),
        el("span", {}, "O motor já está desenhado para o Lúmina “olhar” a casa (shortcuts de presença, contraluz) e reajustar com IA local + nuvem. Fase 2 em breve — nada aqui fica obsoleto."),
      ),
    ),
    el("div", { class: "card" },
      el("h2", {}, "Diagnóstico"),
      el("div", { class: "sub" }, "exportar/importar a configuração (JSON) e ver o estado vivo"),
      el("div", { style: "display:flex;gap:10px;margin-bottom:10px" },
        el("button", { class: "btn tiny", onclick: () => {
          copyText(JSON.stringify(state.config, null, 2));
          toast("Config copiada para o clipboard", "ok");
        } }, "Copiar config JSON"),
        el("button", { class: "btn tiny", onclick: openImportModal }, "Importar config JSON"),
        el("button", { class: "btn tiny", onclick: () => {
          copyText(JSON.stringify(state.runtime, null, 2));
          toast("Estado vivo copiado", "ok");
        } }, "Copiar estado vivo"),
      ),
    ),
  );
}

async function openImportModal() {
  const textarea = el("textarea", { placeholder: "Cole o JSON exportado…" });
  openModal(el("div", {},
    el("h3", {}, "Importar configuração"),
    textarea,
    el("div", { class: "actions" },
      el("button", { class: "btn ghost", onclick: closeModal }, "Cancelar"),
      el("button", { class: "btn primary", onclick: async () => {
        try {
          const json = JSON.parse(textarea.value);
          await state.conn.send("lumina/config_save", { patch: json });
          await refresh();
          closeModal();
          renderActiveTab();
          toast("Configuração importada", "ok");
        } catch (err) {
          toast(`JSON inválido: ${err.message}`, "err");
        }
      } }, "Importar"),
    ),
  ));
}

function openModal(content) {
  closeModal();
  const backdrop = el("div", { class: "modal-backdrop", onclick: (ev) => { if (ev.target === backdrop) closeModal(); } },
    el("div", { class: "modal" }, content));
  document.body.append(backdrop);
}

function closeModal() {
  document.querySelectorAll(".modal-backdrop").forEach((m) => m.remove());
}

function copyText(text) {
  navigator.clipboard.writeText(text).catch(() => {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.append(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  });
}

boot();
