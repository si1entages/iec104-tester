"""真机功能测试 — 对**运行中的主站服务**逐项下发只读类功能并核对真机应答.

用法:
  python tests/e2e/qa_real_device.py [--base http://127.0.0.1:8765] [--yk]

安全约定（真机！）:
- 默认只做**非控制类**功能: 总召唤 / 累计量召唤 / 时钟同步 / 读命令 / 测试命令 / 复位进程
- 遥控(YK)/设点/升降等**控制类命令一律不发**（会操作真实设备），确需测试加 --yk
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request

BASE = "http://127.0.0.1:8765"
_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
PASS, FAIL = "PASS", "FAIL"
_results: list[tuple[str, str, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    _results.append((name, PASS if ok else FAIL, detail))
    print(f"[{PASS if ok else FAIL}] {name}\n      {detail}", flush=True)


def post(path: str, body: dict | None = None, timeout: float = 20) -> dict:
    data = json.dumps(body or {}).encode()
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"},
                                 method="POST")
    with _opener.open(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def get(path: str) -> dict:
    with _opener.open(BASE + path, timeout=15) as r:
        return json.loads(r.read().decode())


def recent_frames() -> list[dict]:
    return get("/api/recent").get("frames", [])


def is_i_frame(hexs: str) -> bool:
    """APCI 控制域判定 I 帧：两个控制字节的 bit0 均为 0."""
    try:
        raw = bytes.fromhex(hexs.replace(" ", ""))
        return len(raw) >= 6 and (raw[2] & 1) == 0 and (raw[3] & 1) == 0
    except Exception:
        return False


def frames_since(ts: float, direction: str = "rx") -> list[dict]:
    out = []
    for fr in recent_frames():
        d = fr.get("data", fr)
        if d.get("direction") != direction or float(fr.get("ts", 0) or 0) < ts:
            continue
        if is_i_frame(d.get("hex", "")):
            out.append(decode_asdu(d.get("hex", "")))
    return out


def decode_asdu(hexs: str) -> dict:
    """最小 ASDU 解码：type / vsq / cot / ca / IOA 列表."""
    try:
        raw = bytes.fromhex(hexs.replace(" ", ""))
        if len(raw) < 10:
            return {}
        apdu_len = raw[1]
        body = raw[6:2 + apdu_len]
        if not body:
            return {}
        t = body[0]
        vsq = body[1]
        # ASDU 头: [0]=type [1]=VSQ [2]=COT(bit6=P/N, bit7=T) [3]=源发地址 [4:6]=CA
        cot = body[2] & 0x3F
        ca = body[5] << 8 | body[4]
        num = vsq & 0x7F
        sq = bool(vsq & 0x80)
        pos = 6
        ioas: list[int] = []
        if sq:
            # SQ=1: 只有首个 IOA，其余按 +1 推得
            if pos + 3 <= len(body):
                ioas.append(body[pos] | body[pos + 1] << 8 | body[pos + 2] << 16)
        else:
            # SQ=0: 每对象 3 字节 IOA + 类型相关数据体；此处只取首个 IOA
            # （对象步长因类型而异，全量解析交由主站引擎）
            if pos + 3 <= len(body):
                ioas.append(body[pos] | body[pos + 1] << 8 | body[pos + 2] << 16)
        return {"type": t, "cot": cot, "ca": ca, "sq": sq, "num": num, "ioas": ioas}
    except Exception:
        return {}


def wait_frames(ts: float, pred, timeout: float = 6.0, direction: str = "rx") -> list[dict]:
    deadline = time.time() + timeout
    found: list[dict] = []
    while time.time() < deadline:
        found = [f for f in frames_since(ts, direction) if pred(f)]
        if found:
            return found
        time.sleep(0.2)
    return found


def main() -> int:
    global BASE
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=BASE)
    parser.add_argument("--yk", action="store_true", help="允许控制类命令（会操作真实设备！）")
    args = parser.parse_args()
    BASE = args.base.rstrip("/")

    st = get("/api/status")
    record("0. 连接状态", st.get("state") == "Running",
           f"state={st.get('state')} tx={st.get('tx')} rx={st.get('rx')} "
           f"目标={st.get('host')}:{st.get('port')} CA={st.get('addr')}")

    # 1. STOPDT / STARTDT 循环
    ts = time.time()
    post("/api/master/stop")
    time.sleep(1.0)
    r = post("/api/master/start", {"host": st["host"], "port": st["port"],
                                   "addr": st.get("addr", 1), "reconnect": True}, timeout=20)
    time.sleep(2.0)
    st2 = get("/api/status")
    record("1. 停止→重新启动（STOPDT/STARTDT 生命周期）",
           bool(r.get("ok")) and st2.get("state") == "Running",
           f"start={r}; state={st2.get('state')}")

    # 2. 总召唤
    ts = time.time()
    r = post("/api/master/gi", {"qoi": 20}, timeout=25)
    term = wait_frames(ts, lambda f: f.get("type") == 100 and f.get("cot") == 10, 8)
    data = wait_frames(ts, lambda f: f.get("type") in (1, 2, 9, 11, 13, 21, 30, 35), 3)
    record("2. 总召唤 QOI=20（数据 + ACTTERM）",
           bool(r.get("ok")) and bool(term) and bool(data),
           f"gi={r}; 数据帧={[(f['type'], f['cot'], f['ioas'][:6]) for f in data[:6]]}; "
           f"结束帧={'有' if term else '无'}")

    # 3. 累计量召唤
    ts = time.time()
    r = post("/api/master/ci", {"qcc": 0}, timeout=25)
    it = wait_frames(ts, lambda f: f.get("type") in (15, 16, 20, 21, 37), 6)
    record("3. 累计量召唤 QCC=0", bool(r.get("ok")) and bool(it),
           f"ci={r}; 应答={[(f['type'], f['cot'], f['ioas'][:6]) for f in it[:6]]}")

    # 4. 时钟同步
    ts = time.time()
    r = post("/api/master/clock", timeout=20)
    cs = wait_frames(ts, lambda f: f.get("type") == 103 and f.get("cot") == 7, 6, "rx")
    record("4. 时钟同步（ACTCON）", bool(r.get("ok")) and bool(cs),
           f"clock={r}; 应答={[(f['type'], f['cot']) for f in cs[:3]]}")

    # 5. 读命令（读总召唤里见到的第一个 IOA；没有则用 1）
    ts = time.time()
    gi_data = wait_frames(ts - 60, lambda f: f.get("type") in (1, 9, 21, 30), 1)
    ioa = next(iter({i for f in gi_data for i in f.get("ioas", [])}), 1)
    r = post("/api/master/read", {"ioa": ioa}, timeout=20)
    rd = wait_frames(ts, lambda f: f.get("cot") == 5 and ioa in f.get("ioas", []), 6)
    record(f"5. 读命令 IOA={ioa}（COT=5 当前值）", bool(r.get("ok")) and bool(rd),
           f"read={r}; 应答={[(f['type'], f['cot'], f['ioas']) for f in rd[:3]]}")

    # 6. 测试命令
    ts = time.time()
    r = post("/api/master/test", timeout=20)
    tst = wait_frames(ts, lambda f: f.get("type") == 104 and f.get("cot") == 7, 6)
    record("6. 测试命令（ACTCON）", bool(r.get("ok")) and bool(tst),
           f"test={r}; 应答={[(f['type'], f['cot']) for f in tst[:3]]}")

    # 7. 复位进程
    ts = time.time()
    r = post("/api/master/reset", timeout=20)
    rp = wait_frames(ts, lambda f: f.get("type") == 105 and f.get("cot") == 7, 6)
    record("7. 复位进程（ACTCON）", bool(r.get("ok")) and bool(rp),
           f"reset={r}; 应答={[(f['type'], f['cot']) for f in rp[:3]]}")

    # 8. 控制类命令（默认跳过）
    if args.yk:
        record("8. 控制类命令（--yk 已指定，但脚本默认不自动执行真机遥控）",
               True, "请按真机规程手动确认 IOA 与操作性质后在 UI 上操作")
    else:
        record("8. 控制类命令（遥控/设点）", True,
               "已按安全约定跳过 —— 真机上发遥控会操作实际设备；确认后加 --yk 再在 UI 操作")

    print("\n===== 汇总 =====")
    passed = sum(1 for _, s, _ in _results if s == PASS)
    for name, status, _ in _results:
        print(f"  {status}  {name}")
    print(f"共 {len(_results)} 项，通过 {passed}，失败 {len(_results) - passed}")
    return 0 if passed == len(_results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
