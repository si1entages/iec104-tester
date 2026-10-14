"""QA 独立验证 — 子站侧 SBO 按点表配置处理（真实双引擎 TCP 联调，无 mock）.

验证 engineer2 对 core/engine/slave.py 的修复：
  - sbo=True  的 YK 点：未选择直接执行 -> 子站回 ACTCON(PN=1) 拒绝，不执行
  - sbo=False 的 YK 点：直接执行 -> 子站回 ACTCON + ACTTERM，无 PN=1
  - 设点（YC，无 sbo 字段）：直接执行 -> ACTCON + ACTTERM
  - 未在选择阶段进入的、点表中不存在的 IOA 遥控：保持严格 SBO（PN=1）

本脚本直接驱动引擎层（不经 Web UI），用 TCP 回环保证真实交互。
"""

from __future__ import annotations

import asyncio
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.data.point_table import PointTable, YcPointDef, YkPointDef  # noqa: E402
from core.engine.master import MasterEngine  # noqa: E402
from core.engine.slave import SlaveEngine  # noqa: E402
from core.protocol.apci import APCICodec  # noqa: E402
from core.protocol.asdu import ASDU  # noqa: E402
from core.protocol.types import COT, TypeID  # noqa: E402

# ── 测试点位 ──────────────────────────────────────────────────────
IOA_YK_SBO_TRUE = 100      # 遥控点, sbo=true
IOA_YK_SBO_FALSE = 101     # 遥控点, sbo=false
IOA_YK_UNDEFINED = 199     # 点表中不存在
IOA_YC = 4001              # 设点 (short float)

PASS, FAIL = "PASS", "FAIL"
_results: list[tuple[str, str, str]] = []


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _build_point_table() -> PointTable:
    pt = PointTable()
    pt.common_addr = 1
    pt.station_name = "QA-SBO"
    pt.add_yk(YkPointDef(ioa=IOA_YK_SBO_TRUE, name="YK_SBO_TRUE",
                         command_type="single", select_before_execute=True))
    pt.add_yk(YkPointDef(ioa=IOA_YK_SBO_FALSE, name="YK_SBO_FALSE",
                         command_type="single", select_before_execute=False))
    pt.add_yc(YcPointDef(ioa=IOA_YC, name="YC_4001"))
    return pt


# ── 报文记录与解码 ────────────────────────────────────────────────
class FrameLog:
    """按方向记录原始帧，并提供解码后的命令帧视图."""

    def __init__(self) -> None:
        self.lines: list[dict] = []

    def add(self, direction: str, data: bytes, client: str = "") -> None:
        frame_type = APCICodec.frame_type_of(data)
        entry = {
            "dir": direction,
            "type": frame_type,
            "hex": data.hex(" "),
            "len": len(data),
            "client": client,
            "cot": None,
            "pn": None,
            "type_id": None,
            "ioa": None,
            "select": None,
            "state": None,
        }
        if frame_type == "I" and len(data) > 6:
            try:
                asdu = ASDU.decode(data[6:])
                entry["cot"] = asdu.cot
                entry["pn"] = asdu.pn
                entry["type_id"] = int(asdu.type_id)
                if asdu.objects:
                    obj = asdu.objects[0]
                    entry["ioa"] = obj.ioa
                    data_obj = obj.data
                    if hasattr(data_obj, "select"):
                        entry["select"] = bool(data_obj.select)
                    if hasattr(data_obj, "state"):
                        entry["state"] = data_obj.state
            except Exception as e:  # noqa: BLE001
                entry["decode_error"] = str(e)
        self.lines.append(entry)

    def command_frames(self, direction: str) -> list[dict]:
        """命令类 I 帧（单命令/双命令/设点/升降/带时标命令）."""
        cmd_types = {
            TypeID.C_SC_NA_1, TypeID.C_DC_NA_1, TypeID.C_RC_NA_1,
            TypeID.C_SE_NA_1, TypeID.C_SE_NB_1, TypeID.C_SE_NC_1,
            TypeID.C_SC_TA_1, TypeID.C_DC_TA_1, TypeID.C_SE_TC_1,
        }
        return [e for e in self.lines
                if e["dir"] == direction and e["type"] == "I"
                and e["type_id"] in cmd_types]

    def ack_frames(self, direction: str, ioa: int) -> list[dict]:
        """指定 IOA 的确认 I 帧（ACTCON/ACTTERM/DEACTCON）."""
        return [e for e in self.lines
                if e["dir"] == direction and e["type"] == "I"
                and e["ioa"] == ioa
                and e["cot"] in (COT.ACTCON, COT.ACTTERM, COT.DEACTCON)]

    def reset(self) -> None:
        self.lines.clear()

    def dump(self) -> str:
        out = []
        for e in self.lines:
            if e["type"] == "I":
                out.append(
                    f"  [{e['dir']:>6}] I  type_id={e['type_id']} "
                    f"COT={e['cot']} PN={e['pn']} IOA={e['ioa']} "
                    f"S/E={e['select']} raw={e['hex']}"
                )
            else:
                out.append(f"  [{e['dir']:>6}] {e['type']} raw={e['hex']}")
        return "\n".join(out)


def record(name: str, ok: bool, detail: str) -> None:
    _results.append((name, PASS if ok else FAIL, detail))
    print(f"[{PASS if ok else FAIL}] {name}\n      {detail}")


async def _wait_until(predicate, timeout: float = 5.0, interval: float = 0.03) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


async def _bring_up(master_log: FrameLog, slave_log: FrameLog):
    """启动双子站/主站，返回 (master, slave)。"""
    port = _free_port()
    points = _build_point_table()

    slave = SlaveEngine(host="127.0.0.1", port=port, common_addr=1, point_table=points)
    slave.data_store.init_from_point_table(points)
    slave.set_raw_frame_callback(lambda d, direction, client="": slave_log.add(direction, d, client))

    master = MasterEngine(
        host="127.0.0.1", port=port, common_addr=1,
        auto_start=True, auto_gi=False, reconnect=False,
        point_table=points,
    )
    master.set_raw_frame_callback(lambda d, direction: master_log.add(direction, d))

    await slave.start()
    await master.start()
    ok = await _wait_until(lambda: master.is_running or str(master.state).lower() == "running", timeout=8)
    assert ok, f"master not running, state={master.state}"
    ok = await _wait_until(lambda: slave.client_count > 0, timeout=5)
    assert ok, "slave got no clients"
    return master, slave


async def _stop(master, slave) -> None:
    try:
        await asyncio.wait_for(master.stop(), timeout=6)
    except Exception:
        pass
    try:
        await asyncio.wait_for(slave.stop(), timeout=6)
    except Exception:
        pass


# ── 场景 ──────────────────────────────────────────────────────────

async def scenario_sbo_true_execute_only(master, slave, mlog: FrameLog, slog: FrameLog) -> None:
    """场景 A: sbo=true 的 YK 点，子站收到"裸执行"帧（未经选择）.

    子站应因未选择而拒绝：ACTCON(PN=1)，且不执行、无 ACTTERM。

    注意：必须用 _send_single_command_raw 绕过主站自动两段式，
    否则主站会先补发选择，子站自然成功——这是隔离"子站判定逻辑"的关键。
    """
    mlog.reset()
    slog.reset()
    # 绕过主站自动 SBO，直接发执行帧，隔离验证子站行为
    await master._send_single_command_raw(IOA_YK_SBO_TRUE, True, select=False, qu=0)
    await asyncio.sleep(0.6)

    # 过滤出子站“发出”的帧：slave_log 记录 direction（rx=收到, tx=发出）
    tx_acks = [e for e in slog.lines
               if e["dir"] == "tx" and e["type"] == "I" and e["ioa"] == IOA_YK_SBO_TRUE]
    actcon_pn1 = [e for e in tx_acks if e["cot"] == COT.ACTCON and e["pn"]]
    actterm = [e for e in tx_acks if e["cot"] == COT.ACTTERM]
    ok = bool(actcon_pn1) and not actterm
    detail = (
        f"子站应答={[(e['cot'], e['pn']) for e in tx_acks]}; "
        f"PN=1 ACTCON={len(actcon_pn1)} ACTTERM={len(actterm)} (期望 PN=1 且无 ACTTERM)"
    )
    record("A. sbo=true 只发执行 -> 子站拒绝 PN=1 且不执行", ok, detail)


async def scenario_sbo_false_execute_only(master, slave, mlog: FrameLog, slog: FrameLog) -> None:
    """场景 B: sbo=false 的 YK 点，只发执行 -> 直发执行 ACTCON + ACTTERM，无 PN=1."""
    mlog.reset()
    slog.reset()
    await master._send_single_command_raw(IOA_YK_SBO_FALSE, True, select=False, qu=0)
    await asyncio.sleep(0.6)

    tx_acks = [e for e in slog.lines
               if e["dir"] == "tx" and e["type"] == "I" and e["ioa"] == IOA_YK_SBO_FALSE]
    actcon = [e for e in tx_acks if e["cot"] == COT.ACTCON and not e["pn"]]
    actterm = [e for e in tx_acks if e["cot"] == COT.ACTTERM]
    any_pn1 = [e for e in tx_acks if e["pn"]]
    ok = bool(actcon) and bool(actterm) and not any_pn1
    detail = (
        f"子站应答={[(e['cot'], e['pn']) for e in tx_acks]}; "
        f"ACTCON(PN=0)={len(actcon)} ACTTERM={len(actterm)} PN=1={len(any_pn1)} "
        f"(期望 均有且 PN=1=0)"
    )
    record("B. sbo=false 只发执行 -> 直发 ACTCON+ACTTERM 无 PN=1", ok, detail)


async def scenario_sbo_true_proper_two_phase(master, slave, mlog: FrameLog, slog: FrameLog) -> None:
    """场景 C: sbo=true，正确 select->execute 两段式应成功（对照组）."""
    mlog.reset()
    slog.reset()
    # 选择
    await master.single_command(IOA_YK_SBO_TRUE, True, select=True, qu=0)
    await asyncio.sleep(0.3)
    # 执行
    await master.single_command(IOA_YK_SBO_TRUE, True, select=False, qu=0)
    await asyncio.sleep(0.6)

    tx_acks = [e for e in slog.lines
               if e["dir"] == "tx" and e["type"] == "I" and e["ioa"] == IOA_YK_SBO_TRUE]
    sel_ack = [e for e in tx_acks if e["cot"] == COT.ACTCON and not e["pn"]]
    actterm = [e for e in tx_acks if e["cot"] == COT.ACTTERM]
    ok = bool(sel_ack) and bool(actterm)
    detail = f"子站应答={[(e['cot'], e['pn']) for e in tx_acks]} (期望含 ACTCON(PN=0) 与 ACTTERM)"
    record("C. sbo=true 正确两段式 -> 成功", ok, detail)


async def scenario_setpoint_direct(master, slave, mlog: FrameLog, slog: FrameLog) -> None:
    """场景 D: 设点（YC 无 sbo 字段）只发执行 -> 直发 ACTCON + ACTTERM."""
    mlog.reset()
    slog.reset()
    await master._send_setpoint_shortfloat_raw(IOA_YC, 123.45, select=False)
    await asyncio.sleep(0.6)

    tx_acks = [e for e in slog.lines
               if e["dir"] == "tx" and e["type"] == "I" and e["ioa"] == IOA_YC]
    actcon = [e for e in tx_acks if e["cot"] == COT.ACTCON and not e["pn"]]
    actterm = [e for e in tx_acks if e["cot"] == COT.ACTTERM]
    any_pn1 = [e for e in tx_acks if e["pn"]]
    ok = bool(actcon) and bool(actterm) and not any_pn1
    detail = (
        f"子站应答={[(e['cot'], e['pn']) for e in tx_acks]}; "
        f"ACTCON(PN=0)={len(actcon)} ACTTERM={len(actterm)} PN=1={len(any_pn1)}"
    )
    record("D. 设点(无 sbo) 只发执行 -> 直发 ACTCON+ACTTERM", ok, detail)


async def scenario_undefined_ioa_strict(master, slave, mlog: FrameLog, slog: FrameLog) -> None:
    """场景 E: 点表中不存在的 IOA，只发执行 -> 保持严格 SBO（PN=1）."""
    mlog.reset()
    slog.reset()
    await master._send_single_command_raw(IOA_YK_UNDEFINED, True, select=False, qu=0)
    await asyncio.sleep(0.6)

    tx_acks = [e for e in slog.lines
               if e["dir"] == "tx" and e["type"] == "I" and e["ioa"] == IOA_YK_UNDEFINED]
    actcon_pn1 = [e for e in tx_acks if e["cot"] == COT.ACTCON and e["pn"]]
    actterm = [e for e in tx_acks if e["cot"] == COT.ACTTERM]
    ok = bool(actcon_pn1) and not actterm
    detail = f"子站应答={[(e['cot'], e['pn']) for e in tx_acks]} (期望 PN=1 且无 ACTTERM)"
    record("E. 未定义 IOA 只发执行 -> 严格 SBO 拒绝", ok, detail)


async def scenario_double_command_sbo_false(master, slave, mlog: FrameLog, slog: FrameLog) -> None:
    """场景 F: sbo=false 的双命令点，只发执行 -> ACTCON + ACTTERM 无 PN=1.

    额外造一个 sbo=false 的双命令点以覆盖 _handle_double_command 分支。
    """
    mlog.reset()
    slog.reset()
    # 绕过主站自动 SBO；double_command 用 state(int)
    await master._send_double_command_raw(IOA_YK_SBO_FALSE, 2, select=False, qu=0)
    await asyncio.sleep(0.6)

    tx_acks = [e for e in slog.lines
               if e["dir"] == "tx" and e["type"] == "I" and e["ioa"] == IOA_YK_SBO_FALSE]
    actcon = [e for e in tx_acks if e["cot"] == COT.ACTCON and not e["pn"]]
    actterm = [e for e in tx_acks if e["cot"] == COT.ACTTERM]
    any_pn1 = [e for e in tx_acks if e["pn"]]
    ok = bool(actcon) and bool(actterm) and not any_pn1
    detail = (
        f"子站应答={[(e['cot'], e['pn']) for e in tx_acks]}; "
        f"ACTCON(PN=0)={len(actcon)} ACTTERM={len(actterm)} PN=1={len(any_pn1)}"
    )
    record("F. sbo=false 双命令只发执行 -> 直发 ACTCON+ACTTERM", ok, detail)


async def main() -> int:
    mlog, slog = FrameLog(), FrameLog()
    master, slave = await _bring_up(mlog, slog)
    try:
        await scenario_sbo_true_execute_only(master, slave, mlog, slog)
        await scenario_sbo_false_execute_only(master, slave, mlog, slog)
        await scenario_sbo_true_proper_two_phase(master, slave, mlog, slog)
        await scenario_setpoint_direct(master, slave, mlog, slog)
        await scenario_undefined_ioa_strict(master, slave, mlog, slog)
        await scenario_double_command_sbo_false(master, slave, mlog, slog)
    finally:
        await _stop(master, slave)

    print("\n===== 汇总 =====")
    passed = sum(1 for _, s, _ in _results if s == PASS)
    for name, status, _ in _results:
        print(f"  {status}  {name}")
    print(f"共 {len(_results)} 项，通过 {passed}，失败 {len(_results) - passed}")
    return 0 if passed == len(_results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
