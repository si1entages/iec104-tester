"""QA 全流程验收 — 模拟真实使用：从零开始，走完主站/子站两页能做的全部操作.

与 qa_joint_debug.py（协议逐帧核对）互补：本脚本按**用户操作顺序**覆盖产品全表面，
每一步都用真实 HTTP/WS/TCP，并可对各阶段截图（Chrome 无头）作为可视化证据。

阶段：
  0. 复位：停两端、清注入、注入联调点表
  1. 启动：子站监听 → 主站连接（STARTDT）
  2. 系统命令：站召唤 / 组召唤 / 累计量召唤 / 时钟同步 / 复位 / 测试 / 读
  3. 控制命令：遥控(SBO) / 遥控(直发) / 设点 + 被控点联动上送
  4. 参数与文件：4 类参数命令 / 文件目录·选择·召唤
  5. 数据模拟：手动置位 + 自动变化开关
  6. 响应注入矩阵：GI延迟 / 命令延迟 / 丢帧 / 损坏 / 不响应 / 错误COT
  7. 点表管理：批量启停·改组 / YAML·CSV·会话导出
  8. 多客户端：第二个主站同时连接子站
  9. 前端：WS 实时刷新链路（页面无需手动刷新）
 10. 关停与重连

用法：
  python app.py --mode slave  --no-browser --port 24040
  python app.py --mode master --no-browser --host 127.0.0.1 --port 24040
  python tests/e2e/qa_full_flow.py [--shots]
"""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # tests/e2e：共享 qa_common

# 复用共享的 HTTP/解码/断言工具（qa_common 自包含，可在干净克隆中独立运行）
from qa_common import (  # noqa: E402
    MASTER,
    PASS,
    SLAVE,
    _results,
    delta,
    get,
    mark,
    post,
    post_raw,
    record,
    yx_values,
)

SHOTS_DIR = Path.home() / "AppData" / "Local" / "Temp" / "iec104_shots"
IEC_PORT = 24040
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


def shot(name: str) -> None:
    """用本机 Chrome 无头模式截图（页面真实渲染，含脚本执行后的 DOM）."""
    if not Path(CHROME).exists():
        return
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    for page, url in (("master", MASTER), ("slave", SLAVE)):
        subprocess.run(
            [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
             "--window-size=1680,1000", "--virtual-time-budget=4000",
             f"--screenshot={SHOTS_DIR / f'{name}_{page}.png'}", url + "/"],
            capture_output=True, timeout=60,
        )


def cot_of(frames: list[dict]) -> list[int]:
    """去重后的 COT 集合（用于"包含哪些原因"类断言）."""
    return sorted({f["cot"] for f in frames})


def cot_seq(frames: list[dict]) -> list[int]:
    """按报文顺序列出 COT（用于断言应答序列，如 SBO 的 [7,7,10]）.

    注意别拿 ``cot_of`` 的结果去比 [7,7,10]：去重后就是 [7,10]，会假失败。
    """
    return [f["cot"] for f in frames]


# ── 阶段实现 ──────────────────────────────────────────────────────

def stage0_reset() -> None:
    post(SLAVE, "/api/slave/stop")
    post(MASTER, "/api/master/stop")
    time.sleep(0.5)
    post(SLAVE, "/api/slave/response", {"delays": {"gi": 0, "command": 0, "data": 0},
                                        "errors": {"no_response": False, "drop_frames": False,
                                                   "drop_rate": 0, "corrupt": False,
                                                   "wrong_cot": False}})
    yaml_text = (ROOT / "tests" / "e2e" / "points_joint.yaml").read_text(encoding="utf-8")
    rm = post_raw(MASTER, "/api/points/yaml", yaml_text)
    rs = post_raw(SLAVE, "/api/points/yaml", yaml_text)
    ms = get(MASTER, "/api/status")
    ss = get(SLAVE, "/api/status")
    record("0. 从零复位（两端已停、注入清零、点表就位）",
           bool(rm.get("ok")) and bool(rs.get("ok"))
           and not ms.get("started") and not ss.get("started"),
           f"master.started={ms.get('started')} slave.started={ss.get('started')}; "
           f"点表={rm.get('points')}/{rs.get('points')} 点")


def stage1_start() -> None:
    rs = post(SLAVE, "/api/slave/start", {"host": "0.0.0.0", "port": IEC_PORT, "addr": 1})
    rm = post(MASTER, "/api/master/start", {"host": "127.0.0.1", "port": IEC_PORT,
                                            "addr": 1, "reconnect": True})
    time.sleep(2.0)
    ms, ss = get(MASTER, "/api/status"), get(SLAVE, "/api/status")
    record("1. 子站「启动监听」+ 主站「连接」（STARTDT 完成）",
           bool(rs.get("ok")) and bool(rm.get("ok"))
           and ms.get("state") == "Running" and ss.get("clients") == 1
           and ms.get("started") and ss.get("started"),
           f"master.state={ms.get('state')} started={ms.get('started')}; "
           f"slave.clients={ss.get('clients')} started={ss.get('started')}")


def stage2_system_commands() -> None:
    ok, detail = True, []

    # 站召唤
    mark(MASTER, "rx")
    post(MASTER, "/api/master/gi", {"qoi": 20})
    time.sleep(1.2)
    ic = [f for f in delta(MASTER, "rx") if f["type_id"] == 100]
    ok &= 7 in cot_of(ic) and 10 in cot_of(ic)
    detail.append(f"站召唤COT={cot_of(ic)}")

    # 组召唤 QOI=1 → 21
    mark(MASTER, "rx")
    post(MASTER, "/api/master/gi", {"qoi": 1})
    time.sleep(1.2)
    yx = [f for f in delta(MASTER, "rx") if f["type_id"] == 1]
    ok &= cot_of(yx) == [21]
    detail.append(f"组召唤COT={cot_of(yx)}")

    # 累计量召唤
    mark(MASTER, "rx")
    post(MASTER, "/api/master/ci")
    time.sleep(1.2)
    it = [f for f in delta(MASTER, "rx") if f["type_id"] == 15]
    ok &= 37 in cot_of(it)
    detail.append(f"累计量COT={cot_of(it)}")

    # 时钟同步
    mark(SLAVE, "tx")
    post(MASTER, "/api/master/clock")
    time.sleep(0.8)
    cs = [f for f in delta(SLAVE, "tx") if f["type_id"] == 103]
    ok &= cot_of(cs) == [7]
    detail.append(f"时钟同步COT={cot_of(cs)}")

    # 复位进程 / 测试命令
    mark(SLAVE, "tx")
    r1 = post(MASTER, "/api/master/reset")
    time.sleep(0.6)
    rp = [f for f in delta(SLAVE, "tx") if f["type_id"] == 105]
    r2 = post(MASTER, "/api/master/test")
    time.sleep(0.6)
    ts = [f for f in delta(SLAVE, "tx") if f["type_id"] == 104]
    ok &= bool(rp) and bool(r1.get("ok")) and bool(r2.get("ok"))
    detail.append(f"复位应答={cot_of(rp)} 测试应答={cot_of(ts)}")

    # 读命令（标准要求：回送被读点当前值，COT=5）
    mark(SLAVE, "tx")
    r3 = post(MASTER, "/api/master/read", {"ioa": 1})
    time.sleep(0.8)
    rd = [f for f in delta(SLAVE, "tx") if f["cot"] == 5 and 1 in f["ioas"]]
    ok &= bool(r3.get("ok")) and bool(rd)
    detail.append(f"读命令应答={[(f['type_id'], f['cot']) for f in rd]}")

    record("2. 系统命令全量：站/组/累计量召唤 + 时钟同步 + 复位 + 测试 + 读", ok, "; ".join(detail))


def stage3_control_commands() -> None:
    ok, detail = True, []

    # 遥控 SBO（自动两段式：选择确认 + 执行确认 + 激活终止）
    mark(SLAVE, "tx")
    mark(MASTER, "tx")
    r = post(MASTER, "/api/master/yk", {"ioa": 2001, "state": 1})
    time.sleep(1.2)
    ack = [f for f in delta(SLAVE, "tx") if f["type_id"] == 45]
    sent = [f for f in delta(MASTER, "tx") if f["type_id"] == 45]
    ok &= (bool(r.get("ok")) and cot_seq(ack) == [7, 7, 10] and len(sent) == 2
           and [f["select"] for f in sent] == [True, False])
    detail.append(f"遥控SBO 主站发出={len(sent)}帧(S/E={[f['select'] for f in sent]}) "
                  f"子站应答COT={cot_seq(ack)}")

    # 遥控直发 + 联动变位
    mark(MASTER, "rx")
    r = post(MASTER, "/api/master/yk", {"ioa": 2002, "state": 1})
    time.sleep(1.2)
    spont = [f for f in delta(MASTER, "rx") if f["cot"] == 3 and 2002 in f["ioas"]]
    ok &= bool(r.get("ok")) and bool(spont) and yx_values(MASTER).get(2002) == "ON"
    detail.append(f"直发+联动 自发帧={[(f['type_id'], f['cot']) for f in spont]} "
                  f"主站YX2002={yx_values(MASTER).get(2002)}")

    # 设点 + 遥测联动
    mark(MASTER, "rx")
    r = post(MASTER, "/api/master/setpoint", {"ioa": 4001, "value": 42.5})
    time.sleep(1.2)
    yc_sp = [f for f in delta(MASTER, "rx") if f["cot"] == 3 and 4001 in f["ioas"]]
    yc = {p["ioa"]: p["value"] for p in get(MASTER, "/api/points")["points"] if p["type"] == "YC"}
    ok &= bool(r.get("ok")) and bool(yc_sp) and abs(float(yc.get(4001, 0)) - 42.5) < 1e-3
    detail.append(f"设点 自发帧={[(f['type_id'], f['cot']) for f in yc_sp]} YC4001={yc.get(4001)}")

    record("3. 控制命令：遥控(SBO 两段式/直发) + 设点，且被控点联动上送", ok, "; ".join(detail))


def stage4_param_file() -> None:
    ok, detail = True, []
    for kind in ("float", "normalized", "scaled", "activation"):
        mark(SLAVE, "tx")
        r = post(MASTER, "/api/master/param", {"kind": kind, "ioa": 1, "value": 1.5,
                                               "qualifier": 1})
        time.sleep(0.6)
        resp = [f for f in delta(SLAVE, "tx") if f["type_id"] in (110, 111, 112, 113)]
        ok &= bool(r.get("ok")) and bool(resp)
        detail.append(f"{kind}→{cot_of(resp)}")

    # 文件传输：目录 / 选择 / 召唤
    mark(SLAVE, "tx")
    r1 = post(MASTER, "/api/master/file", {"action": "directory", "ioa": 0})
    time.sleep(0.8)
    r2 = post(MASTER, "/api/master/file", {"action": "select", "ioa": 0, "file_name": 1})
    time.sleep(0.8)
    r3 = post(MASTER, "/api/master/file", {"action": "request", "ioa": 0, "file_name": 1})
    time.sleep(1.0)
    fdir = [f for f in delta(SLAVE, "tx") if f["type_id"] in (120, 121, 122, 123, 124, 125)]
    ok &= bool(r1.get("ok")) and bool(r2.get("ok")) and bool(r3.get("ok"))
    detail.append(f"文件帧={[(f['type_id'], f['cot']) for f in fdir]}")

    record("4. 参数命令（4 类）与文件传输（目录/选择/召唤）", ok, "; ".join(detail))


def stage5_simulation() -> None:
    ok, detail = True, []

    r1 = post(SLAVE, "/api/slave/yc", {"ioa": 4001, "value": 7.25})
    time.sleep(0.6)
    yc = {p["ioa"]: p["value"] for p in get(MASTER, "/api/points")["points"] if p["type"] == "YC"}
    ok &= bool(r1.get("ok")) and abs(float(yc.get(4001, 0)) - 7.25) < 1e-3
    detail.append(f"手动置 YC4001=7.25 → 主站 {yc.get(4001)}")

    r2 = post(SLAVE, "/api/slave/sim", {"enabled": True, "yx_interval": 0.5, "yc_interval": 0.5})
    time.sleep(2.0)
    sim = get(SLAVE, "/api/status").get("simulation")
    r3 = post(SLAVE, "/api/slave/sim", {"enabled": False})
    time.sleep(0.5)
    ok &= bool(r2.get("ok")) and sim is True and bool(r3.get("ok"))
    detail.append(f"自动变化开={sim} 关={r3.get('ok')}")

    record("5. 数据模拟：手动置位 + 自动变化开关", ok, "; ".join(detail))


def stage6_injection() -> None:
    ok, detail = True, []

    # GI 延迟：响应时间应 ≥0.8s
    post(SLAVE, "/api/slave/response", {"delays": {"gi": 0.8}})
    time.sleep(0.3)
    t0 = time.time()
    post(MASTER, "/api/master/gi", {"qoi": 20})
    time.sleep(1.6)
    gi_cost = time.time() - t0
    post(SLAVE, "/api/slave/response", {"delays": {"gi": 0}})
    ok &= gi_cost >= 0.8
    detail.append(f"GI延迟实测={gi_cost:.2f}s")

    # 不响应：GI 后主站不应收到召唤数据
    post(SLAVE, "/api/slave/response", {"errors": {"no_response": True}})
    time.sleep(0.3)
    mark(MASTER, "rx")
    post(MASTER, "/api/master/gi", {"qoi": 20})
    time.sleep(1.5)
    silent = [f for f in delta(MASTER, "rx") if f["type_id"] in (1, 13, 100)]
    ok &= not silent
    detail.append(f"不响应帧数={len(silent)}")
    post(SLAVE, "/api/slave/response", {"errors": {"no_response": False}})

    # 损坏帧：仍发出帧，但内容被改写（主站应能容错不崩）
    post(SLAVE, "/api/slave/response", {"errors": {"corrupt": True}})
    time.sleep(0.3)
    mark(SLAVE, "tx")
    post(MASTER, "/api/master/gi", {"qoi": 20})
    time.sleep(1.5)
    corrupted_sent = delta(SLAVE, "tx")
    post(SLAVE, "/api/slave/response", {"errors": {"corrupt": False}})
    ms = get(MASTER, "/api/status")
    ok &= bool(corrupted_sent) and ms.get("state") == "Running"
    detail.append(f"损坏帧模式下子站仍发出={len(corrupted_sent)}帧，主站 state={ms.get('state')}")

    # 丢帧：全丢 → 子站一帧都不发
    post(SLAVE, "/api/slave/response", {"errors": {"drop_frames": True, "drop_rate": 1.0}})
    time.sleep(0.3)
    mark(SLAVE, "tx")
    post(MASTER, "/api/master/gi", {"qoi": 20})
    time.sleep(1.5)
    sent = delta(SLAVE, "tx")
    post(SLAVE, "/api/slave/response", {"errors": {"drop_frames": False, "drop_rate": 0}})
    ok &= sent == []
    detail.append(f"丢帧率1.0 子站发送帧数={len(sent)}")

    # 错误 COT：开启后选择确认错位，主站不误判
    post(SLAVE, "/api/slave/response", {"errors": {"wrong_cot": True}})
    time.sleep(0.3)
    mark(SLAVE, "tx")
    r = post(MASTER, "/api/master/yk", {"ioa": 2001, "state": 1}, timeout=40)
    time.sleep(1.0)
    ack = [f for f in delta(SLAVE, "tx") if f["type_id"] == 45]
    post(SLAVE, "/api/slave/response", {"errors": {"wrong_cot": False}})
    time.sleep(0.3)
    ok &= r.get("ok") is False and cot_of(ack) == [8]
    detail.append(f"错误COT 主站ok={r.get('ok')} 子站COT={cot_of(ack)}")

    record("6. 响应注入矩阵：GI延迟 / 不响应 / 损坏 / 丢帧 / 错误COT", ok, "; ".join(detail))


def stage7_points() -> None:
    ok, detail = True, []
    r1 = post(SLAVE, "/api/points/batch", {"type": "YX", "ioas": [2001], "action": "disable"})
    time.sleep(0.3)
    disabled = [p for p in get(SLAVE, "/api/points")["points"]
                if p["type"] == "YX" and p["ioa"] == 2001][0]["enabled"]
    r2 = post(SLAVE, "/api/points/batch", {"type": "YX", "ioas": [2001], "action": "enable"})
    time.sleep(0.3)
    enabled = [p for p in get(SLAVE, "/api/points")["points"]
               if p["type"] == "YX" and p["ioa"] == 2001][0]["enabled"]
    r3 = post(SLAVE, "/api/points/batch", {"type": "YX", "ioas": [2001], "action": "group",
                                           "group": 2})
    time.sleep(0.3)
    group = [p for p in get(SLAVE, "/api/points")["points"]
             if p["type"] == "YX" and p["ioa"] == 2001][0]["group"]
    post(SLAVE, "/api/points/batch", {"type": "YX", "ioas": [2001], "action": "group", "group": 1})
    ok &= (r1.get("ok") and not disabled) and (r2.get("ok") and enabled) and (r3.get("ok") and group == 2)
    detail.append(f"禁用→{disabled} 启用→{enabled} 改组→{group}")

    import urllib.request
    for path, name in (("/api/points/yaml", "YAML"), ("/api/export/points.csv", "CSV"),
                       ("/api/export/session.json", "会话")):
        with urllib.request.urlopen(MASTER + path, timeout=10) as resp:
            body = resp.read().decode("utf-8", "replace")
        ok &= len(body) > 20
        detail.append(f"{name}导出 {len(body)}B")

    record("7. 点表管理：批量启停·改组 + YAML/CSV/会话导出", ok, "; ".join(detail))


def stage8_multi_client() -> None:
    import socket

    before = get(SLAVE, "/api/status").get("client_list") or []
    s = socket.create_connection(("127.0.0.1", IEC_PORT), timeout=5)
    my_id = f"127.0.0.1:{s.getsockname()[1]}"
    try:
        time.sleep(0.8)
        st = get(SLAVE, "/api/status")
        after = st.get("client_list") or []
        record("8. 多客户端：第二个 TCP 客户端接入后出现在子站客户端列表",
               my_id in after and len(after) == len(before) + 1,
               f"clients {before} → {after}（新客户端 {my_id}）")
    finally:
        s.close()
        time.sleep(0.8)
        after_close = get(SLAVE, "/api/status").get("client_list") or []
        record("8b. 该客户端断开后从列表移除", my_id not in after_close,
               f"断开后 clients={after_close}")


def stage9_frontend(shots: bool) -> None:
    import aiohttp

    async def probe():
        async with aiohttp.ClientSession() as sess, \
                sess.ws_connect(SLAVE.replace("http://", "ws://") + "/ws") as ws:
                first = await ws.receive_json(timeout=5)
                post(SLAVE, "/api/slave/yx", {"ioa": 1, "value": True})
                got_frame = False
                for _ in range(20):
                    m = await ws.receive_json(timeout=5)
                    if m.get("kind") == "frame":
                        got_frame = True
                        break
                await ws.send_str("refresh")
                for _ in range(20):
                    m = await ws.receive_json(timeout=5)
                    if m.get("kind") == "snapshot":
                        vals = {p["ioa"]: p["value"] for p in m["data"].get("points", [])
                                if p.get("type") == "YX"}
                        return first.get("kind") == "snapshot", got_frame, vals.get(1)

    try:
        kind_ok, frame_ok, yx1 = asyncio.run(probe())
        ok = kind_ok and frame_ok and yx1 == "ON"
        detail = f"首帧=snapshot:{kind_ok}; 变位推送={frame_ok}; refresh后YX1={yx1}"
    except Exception as e:  # noqa: BLE001
        ok, detail = False, f"WS 探针异常: {e}"

    record("9. 前端实时链路：WS 推送 + refresh 快照（页面无需手动刷新）", ok, detail)
    if shots:
        shot("flow")


def stage10_shutdown() -> None:
    r1 = post(MASTER, "/api/master/stop")
    time.sleep(0.8)
    ms = get(MASTER, "/api/status")
    r2 = post(MASTER, "/api/master/stop")      # 空操作也必须 ok（前端要能对齐状态）
    time.sleep(0.3)
    r3 = post(MASTER, "/api/master/start", {"host": "127.0.0.1", "port": IEC_PORT,
                                            "addr": 1, "reconnect": True})
    time.sleep(2.0)
    ms2 = get(MASTER, "/api/status")
    mark(MASTER, "rx")
    post(MASTER, "/api/master/gi", {"qoi": 20})
    time.sleep(1.5)
    data = [f for f in delta(MASTER, "rx") if f["type_id"] in (1, 13)]
    record("10. 关停（含空操作重复点击）与重连后再次召唤",
           bool(r1.get("ok")) and not ms.get("started") and bool(r2.get("ok"))
           and bool(r3.get("ok")) and ms2.get("state") == "Running" and bool(data),
           f"断开→started={ms.get('started')}; 重复断开={r2.get('ok')}; "
           f"重连 state={ms2.get('state')}; 重连后数据帧={len(data)}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", action="store_true", help="各阶段用 Chrome 无头截图")
    args = ap.parse_args()

    print(f"全流程验收 | 主站 {MASTER} | 子站 {SLAVE} | IEC104 端口 {IEC_PORT}\n")
    for fn in (stage0_reset, stage1_start, stage2_system_commands, stage3_control_commands,
               stage4_param_file, stage5_simulation, stage6_injection, stage7_points,
               stage8_multi_client):
        try:
            fn()
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            record(f"{fn.__name__} 异常", False, str(e))
    try:
        stage9_frontend(args.shots)
    except Exception as e:  # noqa: BLE001
        record("9. 前端实时链路", False, str(e))
    try:
        stage10_shutdown()
    except Exception as e:  # noqa: BLE001
        record("10. 关停与重连", False, str(e))

    print("\n===== 汇总 =====")
    checked = [r for r in _results if r[1] != "OBS"]
    passed = sum(1 for _, s, _ in checked if s == PASS)
    for name, status, _ in checked:
        print(f"  {status}  {name}")
    print(f"共 {len(checked)} 项，通过 {passed}，失败 {len(checked) - passed}")
    return 0 if passed == len(checked) else 1


if __name__ == "__main__":
    raise SystemExit(main())
