/* HTTP API 路径与客户端 — 与 webui/api_contract.md 对齐 */
export const API = {
  status: "/api/status",
  points: "/api/points",
  recent: "/api/recent",
  master: {
    start: "/api/master/start",
    stop: "/api/master/stop",
    gi: "/api/master/gi",
    clock: "/api/master/clock",
    ci: "/api/master/ci",
    reset: "/api/master/reset",
    test: "/api/master/test",
    read: "/api/master/read",
    param: "/api/master/param",
    file: "/api/master/file",
    yk: "/api/master/yk",
    setpoint: "/api/master/setpoint",
  },
  slave: {
    start: "/api/slave/start",
    stop: "/api/slave/stop",
    yx: "/api/slave/yx",
    yc: "/api/slave/yc",
    response: "/api/slave/response",
    sim: "/api/slave/sim",
  },
  pointsYaml: "/api/points/yaml",
  pointsBatch: "/api/points/batch",
  exportCsv: "/api/export/points.csv",
  exportSession: "/api/export/session.json",
  ws: "/ws",
};

export async function api(path, body) {
  const opt = body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : {};
  const r = await fetch(path, opt);
  return r.json();
}

if (typeof window !== "undefined") {
  window.IEC104_API = API;
  window.IEC104_fetchJson = api;
}
