"""QA 独立验证 — 真实 Web UI 双端联调（HTTP API，无 mock）.

流程：
  1. 清空代理环境变量（Windows 下 urllib 否则连接被拒）
  2. 确认端口 8765/8766/2404 空闲
  3. 启动子站(8766)/主站(8765) 进程（app.py --mode ... --no-browser）
  4. 两端 POST /api/points/yaml 注入含 sbo:true/false 的点表
  5. 子站 POST /api/slave/start，主站 POST /api/master/start
  6. 用 /api/master/yk 只发执行（不带 select），读 /api/recent 解码报文
  7. 断言选择帧 S/E=1、执行帧 S/E=0、子站 ACTCON/ACTTERM

用法：
  python tests/e2e/qa_webui_e2e.py            # 假设服务已手动启动
  python tests/e2e/qa_webui_e2e.py --spawn    # 由本脚本启动/回收服务

注意：脚本会占用 2404 / 8765 / 8766 端口，**不要与 pytest 并行运行**
（tests/test_multi_station.py 等会绑定端口，并行时互相抢端口导致假失败）。
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# ── 关键：屏蔽代理，否则 Windows 下 urllib 会走系统代理导致连接被拒 ──
for _k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY",
           "all_proxy", "ALL_PROXY", "no_proxy", "NO_PROXY"):
    os.environ.pop(_k, None)
_proxy_handler = urllib.request.ProxyHandler({})
_opener = urllib.request.build_opener(_proxy_handler)

MASTER = "http://127.0.0.1:8765"
SLAVE = "http://127.0.0.1:8766"

PASS, FAIL = "PASS", "FAIL"
_results: list[tuple[str, str, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    _results.append((name, PASS if ok else FAIL, detail))
    print(f"[{PASS if ok else FAIL}] {name}\n      {detail}")


def post(base: str, path: str, body: dict | None = None) -> dict:
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(base + path, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    with _opener.open(req, timeout=10) as r:
        return json.loads(r.read().decode())


def get(base: str, path: str) -> dict:
    with _opener.open(base + path, timeout=10) as r:
        return json.loads(r.read().decode())


def post_raw(base: str, path: str, text: str) -> dict:
    req = urllib.request.Request(base + path, data=text.encode(),
                                 headers={"Content-Type": "text/yaml"}, method="POST")
    with _opener.open(req, timeout=10) as r:
        return json.loads(r.read().decode())


def wait_http(base: str, timeout: float = 15.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        try:
            get(base, "/api/status")
            return True
        except Exception:
            time.sleep(0.2)
    return False


def _decode_frame_hex(hex_str: str) -> dict:
    """解析 /api/recent 中 frame.data.hex（无空格十六进制）."""
    raw = bytes.fromhex(hex_str)
    out = {"type": None, "cot": None, "pn": None, "type_id": None,
           "ioa": None, "select": None, "raw": hex_str}
    if len(raw) < 6:
        return out
    cf0 = raw[2]
    if (cf0 & 0x01) == 0:
        out["type"] = "I"
    elif (cf0 & 0x03) == 0x01:
        out["type"] = "S"
    else:
        out["type"] = "U"
    if out["type"] == "I" and len(raw) > 6:
        sys.path.insert(0, str(ROOT))
        from core.protocol.asdu import ASDU
        try:
            a = ASDU.decode(raw[6:])
            out["cot"] = a.cot
            out["pn"] = a.pn
            out["type_id"] = int(a.type_id)
            if a.objects:
                obj = a.objects[0]
                out["ioa"] = obj.ioa
                out["select"] = bool(getattr(obj.data, "select", False))
        except Exception as e:  # noqa: BLE001
            out["error"] = str(e)
    return out


def recent_command_frames(base: str, direction: str = "tx") -> list[dict]:
    r = get(base, "/api/recent")
    frames = r.get("frames", [])
    out = []
    for fr in frames:
        d = fr.get("data", fr)
        if d.get("direction") != direction:
            continue
        dec = _decode_frame_hex(d.get("hex", ""))
        if dec["type"] == "I" and dec["type_id"] in (
            45, 46, 49, 48, 50, 51, 58, 59, 61, 100, 101, 103,
        ):
            out.append(dec)
    return out


def spawn_services() -> list[subprocess.Popen]:
    py = str(ROOT / "venv" / "Scripts" / "python.exe")
    env = dict(os.environ)
    for k in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY"):
        env.pop(k, None)
    procs = [
        subprocess.Popen([py, "app.py", "--mode", "slave", "--no-browser"],
                         cwd=str(ROOT), env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
        subprocess.Popen([py, "app.py", "--mode", "master", "--no-browser"],
                         cwd=str(ROOT), env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL),
    ]
    return procs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spawn", action="store_true", help="由脚本启动并回收服务")
    args = ap.parse_args()

    procs: list[subprocess.Popen] = []
    try:
        if args.spawn:
            procs = spawn_services()
        if not wait_http(SLAVE) or not wait_http(MASTER):
            record("0. 服务就绪", False, "无法连接 8765/8766（请确认服务已启动）")
            return 1
        record("0. 服务就绪", True, "master:8765 / slave:8766 均可访问 /api/status")

        # 注入点表
        yaml_text = (ROOT / "tests" / "e2e" / "points_sbo_true.yaml").read_text(encoding="utf-8")
        r_master = post_raw(MASTER, "/api/points/yaml", yaml_text)
        r_slave = post_raw(SLAVE, "/api/points/yaml", yaml_text)
        record("1. 注入自定义点表(sbo:true/false)",
               bool(r_master.get("ok")) and bool(r_slave.get("ok")),
               f"master={r_master} slave={r_slave}")

        # 启动引擎
        rs = post(SLAVE, "/api/slave/start", {"host": "0.0.0.0", "port": 2404, "addr": 1})
        rm = post(MASTER, "/api/master/start", {"host": "127.0.0.1", "port": 2404, "addr": 1})
        record("2. 启动子站/主站引擎",
               bool(rs.get("ok")) and bool(rm.get("ok")),
               f"slave={rs} master={rm}")
        time.sleep(2.0)

        # 场景 1: sbo=true 点，只发执行（不带 select）-> 主站自动两段式
        time.sleep(0.5)
        n_before = len(recent_command_frames(MASTER, "tx"))
        ryk = post(MASTER, "/api/master/yk", {"ioa": 2001, "state": 1})
        time.sleep(1.5)
        frames = recent_command_frames(MASTER, "tx")[n_before:]
        selects = [f for f in frames if f["select"] and f["ioa"] == 2001]
        execs = [f for f in frames if not f["select"] and f["ioa"] == 2001]
        ok1 = ryk.get("ok") and len(selects) == 1 and len(execs) == 1
        record("3. [UI]sbo=true 只发执行 -> 自动补选择(SE=1)+执行(SE=0)",
               ok1,
               f"yk响应={ryk}; 帧={[(f['type_id'], f['ioa'], f['select']) for f in frames]}")

        # 子站侧应答
        sl_frames = recent_command_frames(SLAVE, "tx")
        sl_2001 = [f for f in sl_frames if f["ioa"] == 2001]
        actcon_ok = any(f["cot"] == 7 and not f["pn"] for f in sl_2001)
        actterm_ok = any(f["cot"] == 10 for f in sl_2001)
        record("4. [UI]子站对 sbo=true 点回 ACTCON+ACTTERM",
               actcon_ok and actterm_ok,
               f"子站应答={[(f['cot'], f['pn']) for f in sl_2001]}")

        # 场景 2: sbo=false 点，只发执行 -> 无选择帧
        n2 = len(recent_command_frames(MASTER, "tx"))
        ryk2 = post(MASTER, "/api/master/yk", {"ioa": 2002, "state": 1})
        time.sleep(1.2)
        frames2 = recent_command_frames(MASTER, "tx")[n2:]
        sel2 = [f for f in frames2 if f["select"] and f["ioa"] == 2002]
        exe2 = [f for f in frames2 if not f["select"] and f["ioa"] == 2002]
        record("5. [UI]sbo=false 只发执行 -> 无选择帧, 执行帧×1",
               ryk2.get("ok") and len(sel2) == 0 and len(exe2) == 1,
               f"yk响应={ryk2}; 帧={[(f['ioa'], f['select']) for f in frames2]}")

        # 场景 3: 显式 select=True 旧语义（应只发选择帧）
        n3 = len(recent_command_frames(MASTER, "tx"))
        ryk3 = post(MASTER, "/api/master/yk", {"ioa": 2001, "state": 1, "select": True})
        time.sleep(1.0)
        frames3 = recent_command_frames(MASTER, "tx")[n3:]
        sel3 = [f for f in frames3 if f["select"] and f["ioa"] == 2001]
        exe3 = [f for f in frames3 if not f["select"] and f["ioa"] == 2001]
        record("6. [UI]显式 select=True -> 仅选择帧（旧语义不变）",
               ryk3.get("ok") and len(sel3) == 1 and len(exe3) == 0,
               f"yk响应={ryk3}; 帧={[(f['ioa'], f['select']) for f in frames3]}")

        # 场景 4: 设点 - 纯 YC 点(4001，不在YK表) -> 直发执行
        n4 = len(recent_command_frames(MASTER, "tx"))
        rsp = post(MASTER, "/api/master/setpoint", {"ioa": 4001, "value": 123.45})
        time.sleep(1.0)
        frames4 = recent_command_frames(MASTER, "tx")[n4:]
        sel4 = [f for f in frames4 if f["select"] and f["ioa"] == 4001]
        exe4 = [f for f in frames4 if not f["select"] and f["ioa"] == 4001]
        record("7. [UI]设点(纯YC 4001) -> 直发执行帧",
               rsp.get("ok") and len(sel4) == 0 and len(exe4) == 1,
               f"setpoint响应={rsp}; 帧={[(f['type_id'], f['ioa'], f['select']) for f in frames4]}")

        # 场景 5: 错误 COT 注入 - 子站页开启 wrong_cot，命令应答 COT 整体 +1
        rr = post(SLAVE, "/api/slave/response", {
            "delays": {"gi": 0, "command": 0, "data": 0},
            "errors": {"drop_frames": False, "drop_rate": 0, "corrupt": False,
                       "no_response": False, "wrong_cot": True},
        })
        time.sleep(0.3)
        n5 = len(recent_command_frames(SLAVE, "tx"))
        ryk5 = post(MASTER, "/api/master/yk", {"ioa": 2002, "state": 1})
        time.sleep(1.2)
        ack5 = recent_command_frames(SLAVE, "tx")[n5:]
        ack5 = [f for f in ack5 if f["ioa"] == 2002]
        cots5 = sorted({f["cot"] for f in ack5})
        record("8. [UI]开启错误COT注入 -> 子站应答 COT 错位(+1: 8/11)",
               bool(rr.get("ok")) and bool(ryk5.get("ok")) and cots5 == [8, 11],
               f"响应配置={rr}; 子站应答 COT={cots5} (期望 [8, 11] = ACTCON+1/ACTTERM+1)")

        # 场景 6: 关闭错误 COT 注入 -> 恢复标准 COT (7/10)
        rr2 = post(SLAVE, "/api/slave/response", {
            "errors": {"wrong_cot": False},
        })
        time.sleep(0.3)
        n6 = len(recent_command_frames(SLAVE, "tx"))
        ryk6 = post(MASTER, "/api/master/yk", {"ioa": 2002, "state": 0})
        time.sleep(1.2)
        ack6 = [f for f in recent_command_frames(SLAVE, "tx")[n6:] if f["ioa"] == 2002]
        cots6 = sorted({f["cot"] for f in ack6})
        record("9. [UI]关闭错误COT注入 -> 恢复标准 COT (7/10)",
               bool(rr2.get("ok")) and bool(ryk6.get("ok")) and cots6 == [7, 10],
               f"响应配置={rr2}; 子站应答 COT={cots6} (期望 [7, 10])")

    finally:
        print("\n===== 汇总 =====")
        passed = sum(1 for _, s, _ in _results if s == PASS)
        for name, status, _ in _results:
            print(f"  {status}  {name}")
        print(f"共 {len(_results)} 项，通过 {passed}，失败 {len(_results) - passed}")
        if procs:
            for p in procs:
                p.terminate()
            time.sleep(1.0)
            for p in procs:
                if p.poll() is None:
                    p.kill()
    return 0 if all(s == PASS for _, s, _ in _results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
