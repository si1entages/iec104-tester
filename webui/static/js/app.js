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

  /**
   * 调用后端 API。
   *
   * **默认 POST**：本产品除只读查询外全部接口都是 POST，
   * 无参调用（如 /api/slave/stop）也必须 POST，否则 405。
   * （历史缺陷：不传 body 时发 GET → 停止/断开/时钟同步/复位/测试/累计量召
   *   六个按钮在浏览器里全部 405 且无任何提示。）
   *
   * @param path 接口路径
   * @param body JSON 请求体（可省略）
   * @param method 显式指定方法（只读接口传 "GET"）
   */
  async function api(path, body, method) {
    const opt = {
      method: method || "POST",
      headers: { "Content-Type": "application/json" },
    };
    if (body !== undefined) opt.body = JSON.stringify(body);
    const r = await fetch(path, opt);
    const text = await r.text();
    try {
      return JSON.parse(text);
    } catch (_) {
      // 非 JSON（如 405/500 纯文本）：返回统一错误结构，保证调用方能弹提示
      return { ok: false, error: `HTTP ${r.status} ${text.slice(0, 80)}` };
    }
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
    if (data.status) updateStatus(data.status);
    if (data.points) applyPoints(data.points);
    if (data.frames) state.frames = data.frames;
    if (data.events) state.events = data.events;
    // 仅首帧快照带 frames/events/logs；后续刷新快照只带 points/status，
    // 此时不能重建报文流（会覆盖增量追加的内容）
    if (data.frames || data.events) {
      rebuildFeeds();
      rebuildLogs(data.logs || []);
    }
  }

  /** 首帧快照重建日志面板 */
  function rebuildLogs(logs) {
    const el = $("#feed-logs");
    if (!el) return;
    el.innerHTML = (logs || []).map((d) => {
      const t = new Date((d.ts || 0) * 1000).toLocaleTimeString("zh-CN", { hour12: false });
      return `<div class="log ${String(d.level || "INFO").toLowerCase()}" data-level="${d.level || "INFO"}" data-category="${d.category || "system"}">`
        + `${t} <span class="lv">${d.level || "INFO"}</span> `
        + `<span class="muted">[${escapeHtml(d.source || "")}]</span> ${escapeHtml(d.message || "")}</div>`;
    }).join("");
    el.scrollTop = el.scrollHeight;
  }

  /** 点值格式化（表格与增量刷新共用） */
  function formatValue(p) {
    return p.type === "YC" && typeof p.value === "number" ? p.value.toFixed(3) : p.value;
  }

  /**
   * 应用点表数据：结构未变时**只修补变化的单元格**，避免整表重建导致的
   * 滚动位置跳动、按钮焦点丢失（本工具主站端会被 WS 以 ~4Hz 触发刷新）。
   */
  function applyPoints(list) {
    const tb = $("#grid-body");
    const sameShape =
      tb &&
      list.length === state.points.length &&
      list.every((p, i) => p.ioa === state.points[i].ioa && p.type === state.points[i].type);
    if (!sameShape) {
      state.points = list;
      renderPoints();
      return;
    }
    list.forEach((p, i) => {
      const cur = state.points[i];
      const valueChanged = cur.value !== p.value;
      const qualityChanged = (cur.quality || "") !== (p.quality || "");
      if (!valueChanged && !qualityChanged) return;
      cur.value = p.value;
      cur.quality = p.quality;
      const tr = tb.querySelector(`tr[data-idx="${i}"]`);
      if (!tr) return;
      if (valueChanged) {
        const cell = tr.querySelector("td.val");
        if (cell) cell.textContent = formatValue(p);
        // 子站遥信行的操作按钮文案跟值走（置 ON / 置 OFF）
        const btn = tr.querySelector(".row-actions button");
        if (btn && state.role === "slave" && p.type === "YX") {
          btn.textContent = p.value === "ON" ? "置 OFF" : "置 ON";
        }
      }
      if (qualityChanged) {
        const cell = tr.children[5];
        if (cell) cell.textContent = p.quality || "";
      }
    });
  }

  /**
   * 按服务端真实状态同步顶部按钮可用性.
   *
   * 只用点击后的返回码改按钮是不够的：页面刷新后（或引擎由上一次会话/另一个页面启动时）
   * 服务端明明在运行，「断开 / 停止」却停在 HTML 初始的 disabled 上，用户"点不了"，
   * 再点连接只会得到 already running。故每次状态快照都按 started 重新对齐。
   */
  function syncRunButtons(st) {
    const started = st.started != null ? !!st.started : !!st.running;
    const setDisabled = (sel, v) => { const e = $(sel); if (e) e.disabled = v; };
    if (state.role === "slave") {
      setDisabled("#btn-start", started);
      setDisabled("#btn-stop", !started);
      return;
    }
    setDisabled("#btn-conn", started);
    setDisabled("#btn-disc", !started);
    for (const sel of ["#btn-gi", "#btn-ci", "#btn-clock", "#btn-reset", "#btn-test"]) {
      setDisabled(sel, !started);
    }
  }

  /* 构建版本显示：让用户能确认跑的是新版前端（配合服务端 no-cache + ?v= 版本号） */
  function showBuildStamp() {
    if (!window.IEC104_BUILD) return;
    const bar = $(".statusbar");
    if (!bar) return;
    let el = $("#st-build");
    if (!el) {
      el = document.createElement("span");
      el.id = "st-build";
      bar.appendChild(el);
    }
    el.textContent = `build ${window.IEC104_BUILD}`;
  }

  /* 协议状态机取值 → 中文标签（避免中英混排造成歧义） */
  const STATE_LABEL = {
    Running: "运行中",
    Connecting: "连接中",
    Stopped: "已停止",
    Disconnecting: "断开中",
  };

  function updateStatus(st) {
    const set = (id, v) => { const e = $(id); if (e) e.textContent = v; };
    syncRunButtons(st);
    const label = st.running
      ? (STATE_LABEL[st.state] || "运行中")
      : (st.started ? "连接中" : "未连接");
    set("#st-conn", `状态 ${label}`);
    const dot = $("#st-dot");
    if (dot) dot.classList.toggle("on", !!st.running);
    set("#st-traffic", `报文 TX ${st.tx || 0} / RX ${st.rx || 0}`);
    set("#st-seq", `序号 VS/VR ${st.vs ?? "-"}/${st.vr ?? "-"} 窗口 ${st.window || "-"}`);
    set("#st-points", `点数 ${st.points || state.points.length}`);
    const clients = `客户端 ${st.clients ?? 0}`;
    set("#st-clients", clients);          // 子站侧栏卡片
    set("#st-clients-bar", clients);      // 状态栏

    // 主机/端口输入框只在**首个快照**时从服务端配置初始化一次：
    // 页面刷新后输入框会回到 HTML 默认值 2404，首次同步让它们反映真实配置；
    // 但绝不能每次快照都覆盖 —— 否则用户刚改的端口会被状态里残留的旧值
    // 悄悄改回去（实测：状态里残留 port=2404，把用户设置的 24040 顶掉）。
    const hostInput = $("#host");
    const portInput = $("#port");
    const addrInput = $("#addr");
    if (!inputSynced) {
      if (st.host != null && hostInput) hostInput.value = st.host;
      if (st.port != null && portInput) portInput.value = st.port;
      if (st.addr != null && addrInput) addrInput.value = st.addr;
      inputSynced = true;
    }
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
        const val = formatValue(p);
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
    const r = await api("/api/points", undefined, "GET");   // 只读接口
    applyPoints(r.points || []);
  }

  /* ── 实时刷新：收到报文/事件后向服务端要一次快照（协议见 webui/server.py ws_feed 的 "refresh"） ── */

  const REFRESH_MIN_MS = 250;   // 节流：最快 4 次/秒，避免高频报文把 HTTP 打满
  let refreshTimer = null;
  let lastRefreshAt = 0;
  let wsRef = null;
  let inputSynced = false;      // 连接参数输入框是否已完成首次同步

  function requestRefresh() {
    if (refreshTimer || !wsRef || wsRef.readyState !== WebSocket.OPEN) return;
    const wait = Math.max(0, REFRESH_MIN_MS - (Date.now() - lastRefreshAt));
    refreshTimer = setTimeout(() => {
      refreshTimer = null;
      // 注意：本工具是**双窗口联调**——两个页面必须同时实时刷新，
      // 不能按 document.hidden 跳过后台页（否则只有一个页面能看到实时数据）。
      // 节流（250ms）已经足够限制请求频率。
      if (wsRef && wsRef.readyState === WebSocket.OPEN) {
        lastRefreshAt = Date.now();
        wsRef.send("refresh");
      }
    }, wait);
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) requestRefresh();
  });

  // 兜底轮询：推送丢失、或服务端被其它客户端/进程改了状态时，也能在数秒内对齐
  setInterval(() => requestRefresh(), 5000);

  showBuildStamp();

  /* ── 日志面板：级别/类别过滤 + 关键字 ── */
  const logFilter = { levelMin: 0, category: "all", q: "" };
  const LEVEL_NUM = { DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40, CRITICAL: 50 };

  function appendLogItem(el, msg) {
    const d = msg.data || {};
    if (!el) return;
    const lvl = d.level || "INFO";
    if (LEVEL_NUM[lvl] < logFilter.levelMin) return;
    if (logFilter.category !== "all" && d.category !== logFilter.category) return;
    if (logFilter.q && !(d.message || "").toLowerCase().includes(logFilter.q)) return;
    const stick = nearBottom(el);
    const div = document.createElement("div");
    div.className = `log ${lvl.toLowerCase()}`;
    const t = new Date((d.ts || 0) * 1000).toLocaleTimeString("zh-CN", { hour12: false });
    div.innerHTML = `${t} <span class="lv">${lvl}</span> <span class="muted">[${escapeHtml(d.source || "")}]</span> ${escapeHtml(d.message || "")}`;
    el.appendChild(div);
    while (el.childElementCount > 400) el.removeChild(el.firstElementChild);
    if (stick) el.scrollTop = el.scrollHeight;
  }

  function applyLogFilter() {
    $$("#feed-logs div").forEach((div) => {
      const lv = div.dataset.level || "INFO";
      const text = div.textContent || "";
      let show = LEVEL_NUM[lv] >= logFilter.levelMin;
      if (show && logFilter.category !== "all") {
        show = text.includes(`[${logFilter.category}]`);
      }
      if (show && logFilter.q) show = text.toLowerCase().includes(logFilter.q);
      div.style.display = show ? "" : "none";
    });
  }

  function bindLogControls() {
    const lv = $("#log-level"), cat = $("#log-category"), q = $("#log-q");
    if (lv) lv.onchange = () => { logFilter.levelMin = LEVEL_NUM[lv.value] ?? 0; applyLogFilter(); };
    if (cat) cat.onchange = () => { logFilter.category = cat.value; applyLogFilter(); };
    if (q) q.oninput = () => { logFilter.q = q.value.toLowerCase(); applyLogFilter(); };
    const clr = $("#log-clear");
    if (clr) clr.onclick = () => { const el = $("#feed-logs"); if (el) el.innerHTML = ""; };
  }

  /* ── WebSocket ── */
  function connectWs() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws`);
    wsRef = ws;
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.kind === "snapshot") onSnapshot(msg.data);
      else if (msg.kind === "frame") {
        state.frames.push(msg);
        if (state.frames.length > 500) state.frames.shift();
        appendFeedItem($("#feed-frames"), "frame", msg);
        // 数据类报文（自发上送 / 召唤应答）会改变点值与状态栏，需拉一次快照
        requestRefresh();
      } else if (msg.kind === "event") {
        state.events.push(msg);
        if (state.events.length > 500) state.events.shift();
        appendFeedItem($("#feed-events"), "event", msg);
        requestRefresh();
      } else if (msg.kind === "log") {
        // 结构化日志：只进日志面板，不触发状态刷新（不影响点值链路）
        appendLogItem($("#feed-logs"), msg);
      }
    };
    ws.onclose = () => {
      if (wsRef === ws) wsRef = null;
      setTimeout(connectWs, 1500);
    };
    ws.onerror = () => { /* 由 onclose 负责重连 */ };
  }

  function bindTabs() {
    $$(".tabs .tab").forEach((el) => el.addEventListener("click", () => setFilter(el.dataset.t)));
    bindLogControls();
  }

  // $ / $$ 必须同时挂到 window：页面内联脚本直接用 `$("#btn-...")` 绑定事件，
  // 曾因未暴露而在首句抛 ReferenceError，导致两页所有按钮全部失效（静默）。
  window.$ = $;
  window.$$ = $$;
  window.IEC104 = {
    $, $$, api, toast, askValue, bindTabs, connectWs, renderPoints, applyPoints,
    setFilter, refreshPoints, requestRefresh, state, summarizeFrame,
  };
})();
