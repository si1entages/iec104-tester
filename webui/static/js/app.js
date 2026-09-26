/* IEC104 共用前端逻辑 — IIFE 模块化，仅暴露 window.IEC104 */
(() => {
  "use strict";

  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];

  /* ── Toast（aria-live 无障碍播报） ── */
  function toast(msg) {
    let t = $("#toast");
    if (!t) {
      t = document.createElement("div");
      t.id = "toast";
      t.className = "toast";
      t.setAttribute("role", "status");
      t.setAttribute("aria-live", "polite");
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

  /* ── 数值输入弹窗（原生 <dialog>，替代 prompt） ── */
  function buildDialog() {
    const dlg = document.createElement("dialog");
    dlg.id = "ask-dialog";
    dlg.className = "ask";
    dlg.innerHTML = `
      <form method="dialog">
        <h4 id="ask-title"></h4>
        <input id="ask-input" type="number" step="any" class="grow" />
        <div class="ask-actions">
          <button value="cancel" class="btn">取消</button>
          <button value="ok" class="btn primary">确定</button>
        </div>
      </form>`;
    document.body.appendChild(dlg);
    return dlg;
  }

  /** 弹出数值输入框，返回 Promise<number|null>（取消返回 null） */
  function askValue(title, def) {
    return new Promise((resolve) => {
      const dlg = $("#ask-dialog") || buildDialog();
      $("#ask-title", dlg).textContent = title;
      const input = $("#ask-input", dlg);
      input.value = def;
      dlg.onclose = () => {
        const v = dlg.returnValue === "ok" ? parseFloat(input.value) : null;
        resolve(v != null && !isNaN(v) ? v : null);
      };
      dlg.showModal();
      input.select();
    });
  }

  const state = {
    role: "master",
    points: [],
    filter: "ALL",
    frames: [],
    events: [],
  };

  /* ── 快照 / 状态 ── */
  function onSnapshot(data) {
    if (data.points) state.points = data.points;
    if (data.status) updateStatus(data.status);
    if (data.frames) state.frames = data.frames;
    if (data.events) state.events = data.events;
    renderPoints();
    rebuildFeeds();
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

  /* ── 定义表渲染（预计算原始索引，消除 indexOf O(n²)） ── */
  function renderPoints() {
    const tb = $("#grid-body");
    if (!tb) return;
    const rows = [];
    state.points.forEach((p, idx) => {
      if (state.filter === "ALL" || p.type === state.filter) rows.push({ p, idx });
    });

    tb.innerHTML = rows
      .map(({ p, idx }) => {
        const val =
          p.type === "YC" ? (typeof p.value === "number" ? p.value.toFixed(3) : p.value) : p.value;
        return `<tr data-idx="${idx}">
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

    // 操作列（用预计算 idx 直接定位，不再 indexOf）
    rows.forEach(({ p, idx }) => {
      const tr = tb.querySelector(`tr[data-idx="${idx}"]`);
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
        b.onclick = async () => {
          const v = await askValue(`修改 YC ${p.ioa}`, String(p.value));
          if (v != null) changeYc(p.ioa, v);
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
        b.onclick = async () => {
          const v = await askValue(`设点 YC ${p.ioa}`, String(p.value ?? 0));
          if (v != null) setpoint(p.ioa, v);
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

  /* ── 报文/事件流：增量渲染（单节点 append + 上限裁剪） ── */
  const FEED_MAX = 120;

  function nearBottom(el) {
    return el.scrollHeight - el.scrollTop - el.clientHeight < 40;
  }

  function appendFeedItem(el, kind, item) {
    if (!el) return;
    const stick = nearBottom(el);
    const div = document.createElement("div");
    if (kind === "frame") {
      const f = item.data;
      const hex = f.hex || "";
      div.className = f.direction === "tx" ? "tx" : "rx";
      div.innerHTML = `[${f.direction}] ${f.len}B ${summarizeFrame(hex)} ${escapeHtml(hex.slice(0, 72))}`;
    } else {
      div.className = "ev";
      div.innerHTML = `[${item.data.type}] ${escapeHtml(JSON.stringify(item.data.data || {})).slice(0, 120)}`;
    }
    el.appendChild(div);
    while (el.childElementCount > FEED_MAX) el.removeChild(el.firstElementChild);
    if (stick) el.scrollTop = el.scrollHeight; // 仅当用户停在底部时跟随滚动
  }

  /** 快照时全量重建一次 */
  function rebuildFeeds() {
    const fr = $("#feed-frames");
    const ev = $("#feed-events");
    if (fr) {
      fr.innerHTML = state.frames
        .slice(-FEED_MAX)
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
        .slice(-FEED_MAX)
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

  /* ── 操作 API ── */
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
  async function yk(ioa, st) {
    const r = await api("/api/master/yk", { ioa, state: st });
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

  /* ── WebSocket ── */
  function connectWs() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.kind === "snapshot") onSnapshot(msg.data);
      else if (msg.kind === "frame") {
        state.frames.push(msg);
        if (state.frames.length > 500) state.frames.shift();
        appendFeedItem($("#feed-frames"), "frame", msg);
      } else if (msg.kind === "event") {
        state.events.push(msg);
        if (state.events.length > 500) state.events.shift();
        appendFeedItem($("#feed-events"), "event", msg);
      }
    };
    ws.onclose = () => setTimeout(connectWs, 1500);
  }

  function bindTabs() {
    $$(".tabs .tab").forEach((el) => el.addEventListener("click", () => setFilter(el.dataset.t)));
  }

  window.IEC104 = { api, toast, askValue, bindTabs, connectWs, renderPoints, setFilter, refreshPoints, state, summarizeFrame };
})();
