/**
 * QA 探针 — 在 Node 沙箱里真实执行 Web UI 页面脚本（零依赖，不需要浏览器）
 *
 * 背景（实机反馈的缺陷）：
 * 1) `app.js` 把 `$` 封装在 IIFE 内且未暴露到 window，而 master.html / slave.html 的
 *    内联脚本第一句就是 `$("#btn-conn").onclick = ...` → 抛 ReferenceError →
 *    **所有按钮的 onclick 都没绑上**（按钮点了没反应、disabled 的停止/断开不可点）。
 *    这类失效对 Python 端 HTML 字符串断言完全不可见，必须真跑一次脚本。
 * 2) WS 收到 frame/event 后只追加报文流，从不刷新点值 → 主站遥信值要刷页面才变。
 *    后端 `ws_feed` 支持客户端发 "refresh" 回一次快照，前端此前从未发送。
 *
 * 本脚本用最小 DOM 桩执行页面脚本，断言：
 *   A. 内联脚本执行到底（无 ReferenceError）
 *   B. 关键按钮全部挂上 onclick，点击后发出预期的 HTTP 请求
 *   C. 收到 WS frame/event 后会发送 "refresh"（节流后）
 *   D. 收到刷新快照后，表格单元格就地更新为新值（不需刷新页面）
 *
 * 用法: node tests/frontend/qa_webui_dom.mjs
 *
 * 位置约定：本脚本由 ``tests/test_webui.py`` 调用，必须放在**受版本控制的**
 * 目录下（``tests/frontend/``）。此前它位于被 .gitignore 忽略的 ``qa_verify/``，
 * 导致干净克隆 / CI 中脚本缺失、测试必然失败（已在 T04 收尾修复）。
 * 仓库根通过向上查找 ``pyproject.toml`` 得到，不硬编码目录层级。
 */

import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { fileURLToPath } from "node:url";

/** 向上查找含 pyproject.toml 的目录作为仓库根（脚本移动后依然可用） */
function findRepoRoot(startDir) {
  let dir = startDir;
  for (;;) {
    if (fs.existsSync(path.join(dir, "pyproject.toml"))) return dir;
    const parent = path.dirname(dir);
    if (parent === dir) {
      throw new Error(
        `未能在 ${startDir} 的上级目录中找到 pyproject.toml（仓库根），请从仓库内运行本脚本`,
      );
    }
    dir = parent;
  }
}

const ROOT = findRepoRoot(path.dirname(fileURLToPath(import.meta.url)));
const STATIC = path.join(ROOT, "webui", "static");
const APP_JS = path.join(STATIC, "js", "app.js");

const PASS = "PASS";
const FAIL = "FAIL";
const SKIP = "SKIP";
const results = [];

function record(name, ok, detail) {
  results.push({ name, status: ok ? PASS : FAIL, detail });
  console.log(`[${ok ? PASS : FAIL}] ${name}\n      ${detail}`);
}

/** 在线校验依赖外部服务在跑；服务不可达时计为 SKIP（不计入失败） */
function recordSkip(name, detail) {
  results.push({ name, status: SKIP, detail });
  console.log(`[${SKIP}] ${name}\n      ${detail}`);
}

/* ── 最小 DOM 桩：元素按「父路径|选择器」缓存，保证同一节点多次查询拿到同一对象 ── */

function createEnv() {
  const els = new Map();

  function makeEl(prefix) {
    const el = {
      _prefix: prefix,
      _children: new Map(),
      textContent: "",
      innerHTML: "",
      value: "",
      checked: false,
      disabled: false,
      className: "",
      dataset: {},
      style: {},
      files: [],
      onclick: null,
      onchange: null,
      scrollTop: 0,
      scrollHeight: 0,
      clientHeight: 0,
      childElementCount: 0,
      firstElementChild: null,
      classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
      setAttribute() {},
      appendChild() {},
      append() {},
      removeChild() {},
      addEventListener() {},
      click() {
        if (typeof el.onclick === "function") return el.onclick();
        return undefined;
      },
      querySelector(sel) {
        const key = `${prefix}|${sel}`;
        if (!els.has(key)) {
          const child = makeEl(key);
          els.set(key, child);
          el._children.set(sel, child);
        }
        return els.get(key);
      },
      querySelectorAll: () => [],
    };
    return el;
  }

  const get = (key) => {
    if (!els.has(key)) els.set(key, makeEl(key));
    return els.get(key);
  };

  const fetchCalls = [];
  const timers = [];
  const intervals = [];

  const sandbox = {
    console,
    JSON,
    Date,
    Number,
    Math,
    Object,
    Array,
    Promise,
    isNaN,
    parseInt,
    parseFloat,
    String,
    Boolean,
    Error,
    setTimeout: (fn, ms) => {
      timers.push({ fn, ms });
      return timers.length;
    },
    clearTimeout: () => {},
    setInterval: (fn, ms) => {
      intervals.push({ fn, ms });
      return intervals.length;
    },
    clearInterval: () => {},
    document: {
      hidden: false,
      body: makeEl("body"),
      querySelector: (sel) => get(sel),
      querySelectorAll: () => [],
      createElement: (tag) => makeEl(`<${tag}>`),
      addEventListener: () => {},
    },
    location: { protocol: "http:", host: "127.0.0.1:8765" },
    fetch: async (url, opt = {}) => {
      fetchCalls.push({ url, method: opt.method || "GET", body: opt.body });
      const payload = JSON.stringify({ ok: true, points: [], changed: 1 });
      return {
        status: 200,
        text: async () => payload,
        json: async () => JSON.parse(payload),
      };
    },
  };

  sandbox.window = sandbox;

  const sockets = [];
  class FakeWebSocket {
    constructor(url) {
      this.url = url;
      this.readyState = 1; // OPEN
      this.sent = [];
      sockets.push(this);
    }
    send(data) {
      this.sent.push(data);
    }
    close() {}
  }
  FakeWebSocket.OPEN = 1;
  sandbox.WebSocket = FakeWebSocket;

  const ctx = vm.createContext(sandbox);
  return {
    ctx,
    sandbox,
    els,
    get,
    fetchCalls,
    sockets,
    timers,
    flushTimers: () => {
      const pending = timers.splice(0);
      pending.forEach((t) => t.fn());
      return pending.length;
    },
  };
}

/** 用真实 HTML 的初始属性（disabled/value/checked）预置桩元素，保证起点与浏览器一致 */
function seedFromHtml(html, get) {
  for (const m of html.matchAll(/<(button|input)\b([^>]*)>/gi)) {
    const attrs = m[2];
    const id = /\bid="([^"]+)"/.exec(attrs)?.[1];
    if (!id) continue;
    const el = get(`#${id}`);
    if (/(^|\s)disabled(\s|=|$)/i.test(attrs)) el.disabled = true;
    const value = /\bvalue="([^"]*)"/.exec(attrs)?.[1];
    if (value !== undefined) el.value = value;
    if (/(^|\s)checked(\s|=|$)/i.test(attrs)) el.checked = true;
  }
}

function bootPage(page) {
  const html = fs.readFileSync(path.join(STATIC, page), "utf8");
  const env = createEnv();
  seedFromHtml(html, env.get);
  const appSrc = fs.readFileSync(APP_JS, "utf8");
  vm.runInContext(appSrc, env.ctx, { filename: "app.js" });
  const scripts = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)].map((m) => m[1]);
  if (scripts.length === 0) throw new Error(`${page} 未找到内联脚本`);
  scripts.forEach((src, i) => {
    vm.runInContext(src, env.ctx, { filename: `${page}#script${i}` });
  });
  return { ...env, scripts };
}

/* ── 断言 ── */

const MASTER_BUTTONS = [
  "#btn-conn", "#btn-disc", "#btn-local", "#btn-gi", "#btn-ci",
  "#btn-clock", "#btn-reset", "#btn-test", "#btn-gi-qoi", "#btn-read",
  "#btn-file-dir", "#btn-file-sel", "#btn-file-req", "#btn-param",
  "#yk-off", "#yk-on", "#yk-dc-off", "#yk-dc-on", "#step-down", "#step-up",
  "#bo-send", "#cd-send", "#sp-send",
  "#btn-export-yaml", "#btn-export-csv", "#btn-export-ses",
];
const SLAVE_BUTTONS = [
  "#btn-start", "#btn-stop", "#btn-resp", "#btn-sim",
  "#batch-en", "#batch-dis", "#batch-grp",
  "#btn-ym", "#btn-ep", "#btn-ps",
];

async function testHandlersAttached(page, buttons, label) {
  let env;
  try {
    env = bootPage(page);
  } catch (e) {
    record(`${label}: 页面脚本可执行`, false, `内联脚本抛错: ${e.message}`);
    return null;
  }
  const missing = buttons.filter((sel) => typeof env.get(sel).onclick !== "function");
  record(`${label}: 内联脚本执行到底且按钮已绑定 onclick`,
    missing.length === 0,
    missing.length === 0
      ? `${buttons.length} 个按钮全部绑定成功`
      : `未绑定: ${missing.join(", ")}（内联脚本首句 ReferenceError 即为此症状）`);
  record(`${label}: window.$ / window.$$ 已暴露`,
    typeof env.sandbox.$ === "function" && typeof env.sandbox.$$ === "function",
    `typeof window.$=${typeof env.sandbox.$}, typeof window.$$=${typeof env.sandbox.$$}`);
  return env;
}

async function testMasterConnectClicks(env) {
  const ws = env.sockets[env.sockets.length - 1];
  const conn = env.get("#btn-conn");
  await conn.onclick();
  const start = env.fetchCalls.find((c) => c.url === "/api/master/start");
  record("主站[连接]: 点击后 POST /api/master/start（并启用相关按钮）",
    !!start && start.method === "POST" && env.get("#btn-gi").disabled === false,
    `请求=${start ? start.method + " " + start.url : "未发出"}; #btn-gi.disabled=${env.get("#btn-gi").disabled}`);

  env.get("#host").value = "10.0.0.9";
  await env.get("#btn-local").onclick();
  const starts = env.fetchCalls.filter((c) => c.url === "/api/master/start");
  record("主站[连本地]: 把主机置 127.0.0.1 并触发连接",
    env.get("#host").value === "127.0.0.1" && starts.length === 2,
    `host=${env.get("#host").value}; /api/master/start 调用次数=${starts.length}`);

  // 断开：必须真正调用接口，并且立刻就状态对齐（发 refresh）
  const sentBefore = ws.sent.length;
  await env.get("#btn-disc").onclick();
  env.flushTimers();
  record("主站[断开]: 点击后调用 /api/master/stop 并请求状态对齐",
    env.fetchCalls.some((c) => c.url === "/api/master/stop")
    && ws.sent.slice(sentBefore).includes("refresh"),
    `stop 请求=${env.fetchCalls.some((c) => c.url === "/api/master/stop")}; `
    + `新增 ws 发送=${JSON.stringify(ws.sent.slice(sentBefore))}`);
}

async function testSlaveStartClicks(env) {
  const ws = env.sockets[env.sockets.length - 1];
  await env.get("#btn-start").onclick();
  const start = env.fetchCalls.find((c) => c.url === "/api/slave/start");
  record("子站[启动监听]: 点击后 POST /api/slave/start 且按钮状态互换",
    !!start && env.get("#btn-start").disabled === true && env.get("#btn-stop").disabled === false,
    `请求=${start ? "已发出" : "未发出"}; start.disabled=${env.get("#btn-start").disabled}, stop.disabled=${env.get("#btn-stop").disabled}`);

  const sentBefore = ws.sent.length;
  await env.get("#btn-stop").onclick();
  env.flushTimers();
  record("子站[停止]: 点击后调用 /api/slave/stop 并请求状态对齐",
    env.fetchCalls.some((c) => c.url === "/api/slave/stop")
    && env.get("#btn-start").disabled === false && env.get("#btn-stop").disabled === true
    && ws.sent.slice(sentBefore).includes("refresh"),
    `stop 请求=${env.fetchCalls.some((c) => c.url === "/api/slave/stop")}; `
    + `新增 ws 发送=${JSON.stringify(ws.sent.slice(sentBefore))}`);
}

function testLiveRefresh(env) {
  const ws = env.sockets[env.sockets.length - 1];
  if (!ws) {
    record("WS 实时刷新: 收到报文后请求刷新", false, "未创建 WebSocket");
    return;
  }
  // 服务端首帧快照（含 frames/events）
  ws.onmessage({ data: JSON.stringify({ kind: "snapshot", data: { points: [], status: {} } }) });

  ws.onmessage({
    data: JSON.stringify({
      kind: "frame",
      data: { direction: "rx", len: 20, hex: "680e00000000450103000100" },
    }),
  });
  env.flushTimers();   // 触发节流定时器
  record("WS 实时刷新: 收到 frame 后发送 \"refresh\"（不再需要刷新页面）",
    ws.sent.includes("refresh"),
    `ws.sent=${JSON.stringify(ws.sent)}`);
}

/**
 * 运行状态 ↔ 按钮可用性同步（实机反馈：刷新页面后「断开 / 停止」点不了）
 *
 * @param pairs [选择器, 服务端已启动时是否应禁用]
 * @param cases [场景名, 状态快照, 是否已启动]
 */
function testRunStateSyncsButtons(page, label, pairs, cases) {
  const env = bootPage(page);
  const ws = env.sockets[env.sockets.length - 1];
  const detail = [];
  let ok = true;

  for (const [name, status, started] of cases) {
    ws.onmessage({ data: JSON.stringify({ kind: "snapshot", data: { points: [], status } }) });
    pairs.forEach(([sel, disabledWhenStarted], i) => {
      const got = env.get(sel).disabled;
      const want = started ? disabledWhenStarted : !disabledWhenStarted;
      if (got !== want) ok = false;
      detail.push(`${name} ${sel}=${got}${got === want ? "" : `(期望${want})`}`);
      void i;
    });
  }

  record(`${label}: 按钮可用状态跟服务端状态同步（刷新页面后 断开/停止 仍可点）`,
    ok, detail.join("; "));
}

/**
 * 方法防线：除只读接口外，所有 fetch 必须是 POST。
 * 历史缺陷：api() 不传 body 时发 GET → 停止/断开/时钟同步/复位/测试/累计量召
 * 六个按钮在浏览器里全部 405（Python 侧测试都用显式 POST，完全发现不了）。
 */
const READ_ONLY_PATHS = new Set(["/api/status", "/api/points", "/api/recent"]);

function testAllMutationsArePost(env, label) {
  const bad = env.fetchCalls
    .filter((c) => !READ_ONLY_PATHS.has(c.url))
    .filter((c) => c.method !== "POST")
    .map((c) => `${c.method} ${c.url}`);
  record(`${label}: 全部 API 调用均为 POST（只读除外）`,
    bad.length === 0,
    bad.length === 0
      ? `共 ${env.fetchCalls.length} 次调用，方法全部正确`
      : `非法方法: ${bad.join("; ")}`);
}

function testSnapshotPatchesCell() {
  const env = bootPage("master.html");
  const ws = env.sockets[env.sockets.length - 1];
  const points = [
    { ioa: 2001, type: "YX", name: "YX_2001", group: 1, value: "OFF", quality: "" },
    { ioa: 4001, type: "YC", name: "YC_4001", group: 1, value: 1.5, quality: "" },
  ];
  ws.onmessage({ data: JSON.stringify({ kind: "snapshot", data: { points, status: { running: true } } }) });

  const grid = env.get("#grid-body");
  const rendered = grid.innerHTML;
  const cell = env.get('#grid-body|tr[data-idx="0"]|td.val');

  // 刷新快照（仅 points+status）：遥信变 ON、遥测变 2.25
  const updated = [
    { ioa: 2001, type: "YX", name: "YX_2001", group: 1, value: "ON", quality: "" },
    { ioa: 4001, type: "YC", name: "YC_4001", group: 1, value: 2.25, quality: "" },
  ];
  ws.onmessage({ data: JSON.stringify({ kind: "snapshot", data: { points: updated, status: {} } }) });

  const patched = cell.textContent;
  const ycCell = env.get('#grid-body|tr[data-idx="1"]|td.val').textContent;
  const rerendered = grid.innerHTML !== rendered;
  record("刷新快照就地修补单元格（遥信 →ON、遥测 →2.250），且不整表重建",
    rendered.includes("OFF") && rendered.includes("1.500")
    && patched === "ON" && ycCell === "2.250" && !rerendered,
    `首帧渲染含 OFF/1.500=${rendered.includes("OFF") && rendered.includes("1.500")}; `
    + `修补后 YX=${patched}, YC=${ycCell}; 整表重建=${rerendered}`);
}

/**
 * 端到端：拉真实服务的 /api/status，喂给页面逻辑，断言按钮可用性与服务端一致
 * （正好覆盖实机场景：引擎仍在运行、用户刷新了页面 → 断开/停止必须可点）
 */
async function testLiveStatusDrivesButtons(page, label, baseUrl, pairs) {
  let status;
  try {
    const resp = await fetch(`${baseUrl}/api/status`);
    status = await resp.json();
  } catch (e) {
    recordSkip(`${label}: 用真实 /api/status 校验按钮`,
      `服务未运行（${baseUrl}），跳过在线校验: ${e.message}`);
    return;
  }
  const env = bootPage(page);
  const ws = env.sockets[env.sockets.length - 1];
  ws.onmessage({ data: JSON.stringify({ kind: "snapshot", data: { points: [], status } }) });

  const started = !!status.started;
  const got = pairs.map(([sel]) => env.get(sel).disabled);
  const bad = pairs.filter(([sel, disabledWhenStarted]) =>
    env.get(sel).disabled !== (started ? disabledWhenStarted : !disabledWhenStarted));

  record(`${label}: 真实 /api/status 驱动的按钮状态与后端一致`,
    bad.length === 0,
    `后端 started=${status.started} running=${status.running}; disabled=${JSON.stringify(got)}`
    + (bad.length ? `; 不符: ${bad.map(([s]) => s).join(", ")}` : ""));
}

/**
 * 静态一致性：CSS 必须覆盖页面/脚本里用到的所有 class，且语法配平
 * （改版重写样式表时最容易漏掉某个 class，样式静默失效）
 */
function testCssCoversUsedClasses() {
  const css = fs.readFileSync(path.join(STATIC, "css/app.css"), "utf8");
  const open = (css.match(/\{/g) || []).length;
  const close = (css.match(/\}/g) || []).length;
  if (open !== close) {
    record("CSS 语法配平", false, `花括号不配平: { ×${open}, } ×${close}`);
    return;
  }

  const used = new Set();
  for (const page of ["master.html", "slave.html"]) {
    const html = fs.readFileSync(path.join(STATIC, page), "utf8");
    for (const m of html.matchAll(/class="([^"]+)"/g)) m[1].split(/\s+/).forEach((c) => c && used.add(c));
  }
  const app = fs.readFileSync(APP_JS, "utf8");
  for (const re of [/className\s*=\s*"([^"]+)"/g, /classList\.(?:add|toggle)\("([^"]+)"/g]) {
    for (const m of app.matchAll(re)) m[1].split(/\s+/).forEach((c) => c && used.add(c));
  }

  const missing = [...used].filter((c) => !new RegExp(`\\.${c}(?![\\w-])`).test(css));
  record("CSS 覆盖页面/脚本用到的全部 class", missing.length === 0,
    missing.length === 0 ? `共 ${used.size} 个 class 均有样式` : `缺样式: ${missing.join(", ")}`);
}

/* ── 主流程 ── */

console.log("Web UI 页面脚本沙箱验证（Node，无浏览器依赖）\n");

const masterEnv = await testHandlersAttached("master.html", MASTER_BUTTONS, "主站页");
if (masterEnv) {
  await testMasterConnectClicks(masterEnv);
  testLiveRefresh(masterEnv);
}

const slaveEnv = await testHandlersAttached("slave.html", SLAVE_BUTTONS, "子站页");
if (slaveEnv) await testSlaveStartClicks(slaveEnv);
if (masterEnv) testAllMutationsArePost(masterEnv, "主站页");
if (slaveEnv) testAllMutationsArePost(slaveEnv, "子站页");

// 运行状态 ↔ 按钮可用性同步（实机反馈：刷新页面后「断开 / 停止」点不了）
testRunStateSyncsButtons(
  "master.html", "主站页",
  [["#btn-conn", true], ["#btn-disc", false], ["#btn-gi", false]],
  [
    ["运行中", { started: true, running: true, state: "Running" }, true],
    ["连接中", { started: true, running: false, state: "Connecting" }, true],
    ["已停止", { started: false, running: false, state: "Stopped" }, false],
  ],
);

/* 重连等待期（会话存活、连接被断）状态标签必须显示「重连中」而非「已停止」
 * —— 实机反馈：真机频繁断开时页面总显示"已停止"，用户误以为会话结束 */
function testReconnectingLabel() {
  const env = bootPage("master.html");
  const ws = env.sockets[env.sockets.length - 1];
  ws.onmessage({ data: JSON.stringify({ kind: "snapshot", data: {
    points: [], status: { started: true, running: false, state: "Stopped" },
  } }) });
  const text = env.get("#st-conn").textContent;
  record("主站页: 断线自动重连等待期显示「重连中」",
    text.includes("重连中"),
    `状态栏文本 = "${text}"（期望含「重连中」）`);
}
testReconnectingLabel();
testRunStateSyncsButtons(
  "slave.html", "子站页",
  [["#btn-start", true], ["#btn-stop", false]],
  [
    ["监听中", { started: true, running: true }, true],
    ["已停止", { started: false, running: false }, false],
  ],
);

testSnapshotPatchesCell();
testCssCoversUsedClasses();

// 端到端：用**真实服务的 /api/status** 驱动前端逻辑，验证"刷新页面后仍能点断开/停止"
await testLiveStatusDrivesButtons(
  "master.html", "主站页", "http://127.0.0.1:8765",
  [["#btn-conn", true], ["#btn-disc", false]],
);
await testLiveStatusDrivesButtons(
  "slave.html", "子站页", "http://127.0.0.1:8766",
  [["#btn-start", true], ["#btn-stop", false]],
);

console.log("\n===== 汇总 =====");
const failed = results.filter((r) => r.status === FAIL);
results.forEach((r) => console.log(`  ${r.status}  ${r.name}`));
console.log(`共 ${results.length} 项，通过 ${results.length - failed.length}，失败 ${failed.length}`);
process.exit(failed.length === 0 ? 0 : 1);
