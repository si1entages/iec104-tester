/* 共用前端逻辑 */
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];

function toast(msg) {
  let t = $("#toast");
  if (!t) {
    t = document.createElement("div");
    t.id = "toast";
    t.className = "toast";
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.classList.add("show");
  setTimeout(() => t.classList.remove("show"), 2200);
}

async function api(path, body) {
  const opt = body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : {};
  const r = await fetch(path, opt);
  return r.json();
}

const state = {
  role: "master",
  points: [],
  filter: "ALL",
  frames: [],
  events: [],
};

function onSnapshot(data) {
  if (data.points) state.points = data.points;
  if (data.status) updateStatus(data.status);
  if (data.frames) state.frames = data.frames;
  if (data.events) state.events = data.events;
  renderPoints();
  renderFeeds();
}

function updateStatus(st) {
  const set = (id, v) => { const e = $(id); if (e) e.textContent = v; };
  set("#st-conn", st.running ? (st.state || "运行中") : "未连接");
  const dot = $("#st-dot");
  if (dot) dot.classList.toggle("on", !!st.running);
  set("#st-traffic", `TX ${st.tx || 0} / RX ${st.rx || 0}`);
  set("#st-seq", `VS/VR ${st.vs ?? "-"}/${st.vr ?? "-"}  窗 ${st.window || "-"}`);
  set("#st-clients", st.clients != null ? `客户端 ${st.clients}` : "");
  set("#st-points", `点 ${st.points || state.points.length}`);
}

function setFilter(t) {
  state.filter = t;
  $$(".tabs .tab").forEach((el) => el.classList.toggle("active", el.dataset.t === t));
  renderPoints();
}

function visiblePoints() {
  return state.filter === "ALL"
    ? state.points
    : state.points.filter((p) => p.type === state.filter);
}

function renderPoints() {
  const tb = $("#grid-body");
  if (!tb) return;
  const rows = visiblePoints();
  tb.innerHTML = rows
    .map((p, i) => {
      const val =
        p.type === "YC" ? (typeof p.value === "number" ? p.value.toFixed(3) : p.value) : p.value;
      return `<tr data-idx="${state.points.indexOf(p)}">
        <td class="num">${p.ioa}</td>
        <td><span class="tag ${p.type}">${p.type}</span></td>
        <td>${escapeHtml(p.name || "")}</td>
        <td class="num">${p.group}</td>
        <td class="num val">${val}</td>
        <td class="muted">${p.quality || ""}</td>
        <td class="row-actions"></td>
      </tr>`;
    })
    .join("");
  // 操作列
  rows.forEach((p) => {
    const tr = $(`#grid-body tr[data-idx="${state.points.indexOf(p)}"]`);
    if (!tr) return;
    const cell = tr.querySelector(".row-actions");
    if (state.role === "slave" && p.type === "YX") {
      const b = document.createElement("button");
      b.className = "btn";
      b.textContent = p.value === "ON" ? "置 OFF" : "置 ON";
      b.onclick = () => toggleYx(p.ioa, p.value !== "ON");
      cell.appendChild(b);
    } else if (state.role === "slave" && p.type === "YC") {
      const b = document.createElement("button");
      b.className = "btn";
      b.textContent = "改值";
      b.onclick = () => {
        const v = prompt("新值", String(p.value));
        if (v != null && v !== "") changeYc(p.ioa, parseFloat(v));
      };
      cell.appendChild(b);
    } else if (state.role === "master" && p.type === "YK") {
      const b1 = document.createElement("button");
      b1.className = "btn";
      b1.textContent = "分";
      b1.onclick = () => yk(p.ioa, 0);
      const b2 = document.createElement("button");
      b2.className = "btn primary";
      b2.textContent = "合";
      b2.onclick = () => yk(p.ioa, 1);
      cell.append(b1, b2);
    } else if (state.role === "master" && p.type === "YC") {
      const b = document.createElement("button");
      b.className = "btn";
      b.textContent = "设点";
      b.onclick = () => {
        const v = prompt("设点值", String(p.value ?? 0));
        if (v != null && v !== "") setpoint(p.ioa, parseFloat(v));
      };
      cell.appendChild(b);
    }
  });
}

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
  );
}

function renderFeeds() {
  const fr = $("#feed-frames");
  const ev = $("#feed-events");
  if (fr) {
    fr.innerHTML = state.frames
      .slice(-120)
      .map((f) => {
        const hex = f.data.hex || "";
        return `<div class="${f.data.direction === "tx" ? "tx" : "rx"}">[${
          f.data.direction
        }] ${f.data.len}B ${summarizeFrame(hex)} ${escapeHtml(hex.slice(0, 72))}</div>`;
      })
      .join("");
    fr.scrollTop = fr.scrollHeight;
  }
  if (ev) {
    ev.innerHTML = state.events
      .slice(-120)
      .map((e) => `<div class="ev">[${e.data.type}] ${escapeHtml(JSON.stringify(e.data.data || {})).slice(0, 120)}</div>`)
      .join("");
    ev.scrollTop = ev.scrollHeight;
  }
}

/** 简短协议摘要：U/S/I + ASDU TypeID */
function summarizeFrame(hex) {
  if (!hex || hex.length < 12) return "";
  const b0 = parseInt(hex.slice(0, 2), 16);
  const ctrl = parseInt(hex.slice(4, 6), 16);
  let apci = "?";
  if ((ctrl & 0x03) === 0x03) {
    const map = { 0x07: "START", 0x0B: "STARTCON", 0x13: "STOP", 0x23: "STOPCON", 0x43: "TEST", 0x83: "TESTCON" };
    apci = "U:" + (map[ctrl & 0xF3] || ctrl.toString(16));
  } else if ((ctrl & 0x01) === 0x01) {
    apci = "S";
  } else {
    apci = "I";
    const type = parseInt(hex.slice(12, 14), 16);
    if (!isNaN(type)) apci += " T" + type;
  }
  return `<span class="muted">[${apci}]</span>`;
}

async function toggleYx(ioa, value) {
  const r = await api("/api/slave/yx", { ioa, value });
  if (!r.ok) toast(r.error || "失败");
  else toast(`YX ${ioa} → ${value ? "ON" : "OFF"}`);
  refreshPoints();
}
async function changeYc(ioa, value) {
  const r = await api("/api/slave/yc", { ioa, value });
  if (!r.ok) toast(r.error || "失败");
  else toast(`YC ${ioa} → ${value}`);
  refreshPoints();
}
async function yk(ioa, state) {
  const r = await api("/api/master/yk", { ioa, state });
  toast(r.ok ? "命令已发" : r.error || "失败");
}
async function setpoint(ioa, value) {
  const r = await api("/api/master/setpoint", { ioa, value });
  toast(r.ok ? "设点已发" : r.error || "失败");
}

async function refreshPoints() {
  const r = await api("/api/points");
  state.points = r.points || [];
  renderPoints();
}

function connectWs() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  ws.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.kind === "snapshot") onSnapshot(msg.data);
    else if (msg.kind === "frame") {
      state.frames.push(msg);
      if (state.frames.length > 500) state.frames.shift();
      renderFeeds();
    } else if (msg.kind === "event") {
      state.events.push(msg);
      if (state.events.length > 500) state.events.shift();
      renderFeeds();
    }
  };
  ws.onclose = () => setTimeout(connectWs, 1500);
}

function bindTabs() {
  $$(".tabs .tab").forEach((el) => el.addEventListener("click", () => setFilter(el.dataset.t)));
}

window.IEC104 = { api, toast, bindTabs, connectWs, renderPoints, setFilter, refreshPoints, state, summarizeFrame };
