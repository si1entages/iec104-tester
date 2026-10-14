"""QA 独立验证 — 主站侧 SBO 自动两段式（真实 TCP，无 mock）.

覆盖 team-lead 指定的高危点：
  1. sbo=true 点只发执行 -> 主站自动补选择（S/E=1）-> 等 ACTCON(PN=0) -> 发执行（S/E=0）
  2. sbo=false 点只发执行 -> 主站只发执行帧（无选择帧）
  3. 选择被拒(PN=1) -> 主站中止，报文序列中确无执行帧
  4. 选择超时（无应答）-> 主站中止，无执行帧，且 _pending_acks 无残留
  5. 显式 select=True -> 单帧 select，旧语义不变
  6. 竞态：同 IOA 上一次命令的滞后 ACTTERM 不得破坏下一次选择等待

场景 3/4 用一个最小"假子站" raw TCP server 精确注入 PN=1 / 静默；
场景 1/2/5/6 用真实 SlaveEngine 回环。
"""

from __future__ import annotations

import asyncio
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from core.data.point_table import PointTable, YkPointDef  # noqa: E402
from core.engine.master import MasterEngine  # noqa: E402
from core.engine.slave import SlaveEngine  # noqa: E402
from core.protocol.apci import APCICodec  # noqa: E402
from core.protocol.asdu import ASDU  # noqa: E402
from core.protocol.types import COT, TypeID  # noqa: E402

IOA_SBO_TRUE = 100
IOA_SBO_FALSE = 101
IOA_YC_PLAIN = 4001
PASS, FAIL = "PASS", "FAIL"
_results: list[tuple[str, str, str]] = []


def record(name: str, ok: bool, detail: str) -> None:
    _results.append((name, PASS if ok else FAIL, detail))
    print(f"[{PASS if ok else FAIL}] {name}\n      {detail}")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _pt(*, sbo_true_ioas, sbo_false_ioas, common_addr=1) -> PointTable:
    pt = PointTable()
    pt.common_addr = common_addr
    for ioa in sbo_true_ioas:
        pt.add_yk(YkPointDef(ioa=ioa, name=f"YK_{ioa}", command_type="single",
                             select_before_execute=True))
    for ioa in sbo_false_ioas:
        pt.add_yk(YkPointDef(ioa=ioa, name=f"YK_{ioa}", command_type="single",
                             select_before_execute=False))
    return pt


def _decode_i(frame: bytes) -> dict:
    a = ASDU.decode(frame[6:])
    obj = a.objects[0] if a.objects else None
    return {
        "cot": a.cot, "pn": a.pn, "type_id": int(a.type_id),
        "ioa": obj.ioa if obj else None,
        "select": bool(getattr(obj.data, "select", False)) if obj else None,
    }


async def _wait_until(pred, timeout=5.0, interval=0.03) -> bool:
    loop = asyncio.get_running_loop()
    end = loop.time() + timeout
    while loop.time() < end:
        if pred():
            return True
        await asyncio.sleep(interval)
    return pred()


# ── 真实双引擎 ────────────────────────────────────────────────────
async def _real_pair():
    """启动主站+子站，主站点表 sbo=true(100)/sbo=false(101)，子站同配置."""
    port = _free_port()
    pt = _pt(sbo_true_ioas=[IOA_SBO_TRUE], sbo_false_ioas=[IOA_SBO_FALSE])
    slave = SlaveEngine(host="127.0.0.1", port=port, common_addr=1, point_table=pt)
    slave.data_store.init_from_point_table(pt)
    master = MasterEngine(host="127.0.0.1", port=port, common_addr=1,
                          auto_start=True, auto_gi=False, reconnect=False,
                          point_table=pt)
    tx_frames: list[bytes] = []
    master.set_raw_frame_callback(lambda d, direction: tx_frames.append(d) if direction == "tx" else None)
    await slave.start()
    await master.start()
    assert await _wait_until(lambda: str(master.state).lower() == "running", timeout=8)
    assert await _wait_until(lambda: slave.client_count > 0, timeout=5)
    return master, slave, tx_frames


# ── 假子站（精确注入）──────────────────────────────────────────────
class FakeSlave:
    """最小 IEC104 子站：握手 STARTDT，按配置回命令确认，记录收到的命令帧."""

    def __init__(self, mode: str):
        # mode: "ack" (正常ACTCON+ACTTERM) | "nack_select"(选择PN=1) | "silent"(不回)
        self.mode = mode
        self.command_frames: list[dict] = []
        self.server: asyncio.AbstractServer | None = None
        self.rx_seq = 0
        self.tx_seq = 0

    async def start(self, port: int) -> None:
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", port)

    async def _send_i(self, writer, asdu_bytes: bytes) -> None:
        frame = APCICodec.encode_i(self.tx_seq, self.rx_seq, asdu_bytes)
        self.tx_seq += 1
        writer.write(frame)
        await writer.drain()

    async def _handle(self, reader, writer) -> None:
        try:
            while True:
                head = await reader.readexactly(2)
                if head[0] != 0x68:
                    break
                rest = await reader.readexactly(head[1])
                frame = head + rest
                ftype = APCICodec.frame_type_of(frame)
                if ftype == "U":
                    if frame[2] == 0x07:  # STARTDT ACT -> CON
                        writer.write(APCICodec.startdt_con())
                        await writer.drain()
                    continue
                if ftype != "I":
                    continue
                # 仅对 I 帧计数接收序列号（U/S 帧不占 V(R) 空间）
                self.rx_seq += 1
                try:
                    asdu = ASDU.decode(frame[6:])
                except Exception:
                    continue
                obj = asdu.objects[0] if asdu.objects else None
                if obj is None:
                    continue
                info = {"ioa": obj.ioa, "cot": asdu.cot,
                        "select": bool(getattr(obj.data, "select", False))}
                self.command_frames.append(info)
                if self.mode == "silent":
                    continue
                if asdu.cot == COT.ACT:
                    if info["select"]:
                        # 选择阶段
                        if self.mode == "stale_actterm":
                            # 先发一条"上一条命令的滞后 ACTTERM"，再发真正的选择确认。
                            # 若主站未正确忽略非 ACTCON 帧，会把 ACTTERM 误判为选择被拒。
                            await self._send_i(
                                writer, self._build_ack(asdu.type_id, COT.ACTTERM, obj, False)
                            )
                            await asyncio.sleep(0.02)
                        pn = (self.mode == "nack_select")
                        ack = self._build_ack(asdu.type_id, COT.ACTCON, obj, pn)
                        await self._send_i(writer, ack)
                    else:
                        # 执行阶段
                        await self._send_i(writer, self._build_ack(asdu.type_id, COT.ACTCON, obj, False))
                        await self._send_i(writer, self._build_ack(asdu.type_id, COT.ACTTERM, obj, False))
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        finally:
            try:
                writer.close()
            except Exception:
                pass

    @staticmethod
    def _build_ack(type_id, cot, obj, pn: bool) -> bytes:
        """手工构造命令确认 ASDU（回送同一对象）."""
        # 复用引擎的 builder：build_single_command 反向不便，直接手工编码
        vsq = 0x01
        coa = (1).to_bytes(2, "little")
        ioa = obj.ioa.to_bytes(3, "little")
        cot_byte = (cot & 0x3F) | (0x40 if pn else 0)
        cot_b = bytes([cot_byte, 0x00])
        body = obj.data.to_bytes() if hasattr(obj.data, "to_bytes") else bytes([obj.data.state])
        return bytes([int(type_id), vsq]) + cot_b + coa + ioa + body

    async def stop(self) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()


async def _master_against_fake(mode: str, *, sbo_true=True, t1=1.0):
    port = _free_port()
    fake = FakeSlave(mode)
    await fake.start(port)
    pt = _pt(sbo_true_ioas=[IOA_SBO_TRUE] if sbo_true else [],
             sbo_false_ioas=[] if sbo_true else [IOA_SBO_TRUE])
    master = MasterEngine(host="127.0.0.1", port=port, common_addr=1,
                          auto_start=True, auto_gi=False, reconnect=False,
                          point_table=pt, t1=t1)
    tx_frames: list[bytes] = []
    master.set_raw_frame_callback(lambda d, direction: tx_frames.append(d) if direction == "tx" else None)
    await master.start()
    ready = await _wait_until(lambda: str(master.state).lower() == "running", timeout=8)
    assert ready, f"master not running: {master.state}"
    return master, fake, tx_frames


# ═══════════════════════════════════════════════════════════════════
#  场景
# ═══════════════════════════════════════════════════════════════════

async def sc1_auto_two_phase():
    master, slave, tx = await _real_pair()
    try:
        tx.clear()
        await master.single_command(IOA_SBO_TRUE, True, select=False, qu=0)
        await asyncio.sleep(0.8)
        cmds = [_decode_i(f) for f in tx if APCICodec.frame_type_of(f) == "I"
                and int(ASDU.decode(f[6:]).type_id) in (TypeID.C_SC_NA_1,)]
        selects = [c for c in cmds if c["select"]]
        execs = [c for c in cmds if not c["select"]]
        ok = len(selects) == 1 and len(execs) == 1
        detail = f"主站命令帧: {[(c['type_id'], c['select']) for c in cmds]} (期望 选择S/E=1 ×1 + 执行S/E=0 ×1)"
        record("1. sbo=true 只发执行 -> 主站自动两段式", ok, detail)
    finally:
        await _stop(master, slave)


async def sc2_sbo_false_single_frame():
    master, slave, tx = await _real_pair()
    try:
        tx.clear()
        await master.single_command(IOA_SBO_FALSE, True, select=False, qu=0)
        await asyncio.sleep(0.6)
        cmds = [c for f in tx if APCICodec.frame_type_of(f) == "I"
                for c in [_decode_i(f)] if c["type_id"] == TypeID.C_SC_NA_1]
        selects = [c for c in cmds if c["select"]]
        execs = [c for c in cmds if not c["select"]]
        ok = len(selects) == 0 and len(execs) == 1
        detail = f"主站命令帧: {[(c['type_id'], c['select']) for c in cmds]} (期望 无选择帧, 执行帧 ×1)"
        record("2. sbo=false 只发执行 -> 主站只发执行帧", ok, detail)
    finally:
        await _stop(master, slave)


async def sc3_select_rejected_no_execute():
    master, fake, tx = await _master_against_fake("nack_select")
    try:
        tx.clear()
        err = None
        try:
            await master.single_command(IOA_SBO_TRUE, True, select=False, qu=0)
        except Exception as e:  # noqa: BLE001
            err = str(e)
        await asyncio.sleep(0.5)
        cmds = [c for f in tx if APCICodec.frame_type_of(f) == "I"
                for c in [_decode_i(f)] if c["type_id"] == TypeID.C_SC_NA_1]
        selects = [c for c in cmds if c["select"]]
        execs = [c for c in cmds if not c["select"]]
        ok = len(selects) == 1 and len(execs) == 0 and err is not None
        detail = (f"主站帧 S/E: select={len(selects)} execute={len(execs)}; "
                  f"异常={err!r} (期望 仅选择帧, 无执行帧, 抛异常)")
        record("3. 选择被拒(PN=1) -> 主站中止，无执行帧", ok, detail)
    finally:
        await _stop(master, fake)


async def sc4_select_timeout_no_execute():
    master, fake, tx = await _master_against_fake("silent", t1=0.6)
    try:
        tx.clear()
        err = None
        try:
            await master.single_command(IOA_SBO_TRUE, True, select=False, qu=0)
        except Exception as e:  # noqa: BLE001
            err = str(e)
        await asyncio.sleep(0.5)
        cmds = [c for f in tx if APCICodec.frame_type_of(f) == "I"
                for c in [_decode_i(f)] if c["type_id"] == TypeID.C_SC_NA_1]
        selects = [c for c in cmds if c["select"]]
        execs = [c for c in cmds if not c["select"]]
        leftover = dict(master._pending_acks)
        ok = len(selects) == 1 and len(execs) == 0 and err is not None and not leftover
        detail = (f"select={len(selects)} execute={len(execs)}; 异常={err!r}; "
                  f"_pending_acks 残留={list(leftover.keys())} (期望 无执行帧、抛异常、无残留)")
        record("4. 选择超时 -> 主站中止，无执行帧且无 Future 残留", ok, detail)
    finally:
        await _stop(master, fake)


async def sc5_explicit_select_unchanged():
    master, slave, tx = await _real_pair()
    try:
        tx.clear()
        await master.single_command(IOA_SBO_TRUE, True, select=True, qu=0)
        await asyncio.sleep(0.5)
        cmds = [c for f in tx if APCICodec.frame_type_of(f) == "I"
                for c in [_decode_i(f)] if c["type_id"] == TypeID.C_SC_NA_1]
        selects = [c for c in cmds if c["select"]]
        execs = [c for c in cmds if not c["select"]]
        ok = len(selects) == 1 and len(execs) == 0
        detail = f"主站命令帧: {[(c['select']) for c in cmds]} (期望 仅 1 帧 select=True，不追加执行)"
        record("5. 显式 select=True -> 旧语义不变（单帧选择）", ok, detail)
    finally:
        await _stop(master, slave)


async def sc6_lagging_actterm_race():
    """真实 TCP 上的竞态：连续两次同 IOA 命令，验证第二次不被第一次的滞后帧破坏."""
    master, slave, tx = await _real_pair()
    try:
        # 第一次完整两段式（产生 ACTCON+ACTTERM）
        await master.single_command(IOA_SBO_TRUE, True, select=False, qu=0)
        # 紧接着立刻发起第二次（模拟 UI 连点）
        err = None
        try:
            await master.single_command(IOA_SBO_TRUE, True, select=False, qu=0)
        except Exception as e:  # noqa: BLE001
            err = str(e)
        await asyncio.sleep(0.8)
        cmds = [c for f in tx if APCICodec.frame_type_of(f) == "I"
                for c in [_decode_i(f)] if c["type_id"] == TypeID.C_SC_NA_1]
        # 两次两段式 => 4 帧：select,exec,select,exec
        selects = [c for c in cmds if c["select"]]
        execs = [c for c in cmds if not c["select"]]
        ok = err is None and len(selects) == 2 and len(execs) == 2
        detail = (f"两次命令共 {len(cmds)} 帧: select={len(selects)} execute={len(execs)}; "
                  f"异常={err!r} (期望 各2帧, 无异常)")
        record("6. 连续两次同 IOA 命令（滞后 ACTTERM 竞态）", ok, detail)
    finally:
        await _stop(master, slave)


async def sc8_setpoint_two_phase_on_sbo_yk():
    """设点：命中 YK 点表且 sbo=true 的 IOA -> 与子站对称，自动两段式.

    实测发现 master `_sbo_required` 与子站 `_command_requires_sbo` 对称：
    都优先查 YK 点表。故对"既是 sbo=true 遥控点、又用作设点目标"的 IOA，
    设点命令也会自动两段式。
    """
    master, slave, tx = await _real_pair()
    try:
        tx.clear()
        await master.setpoint_shortfloat(IOA_SBO_TRUE, 123.45, select=False)
        await asyncio.sleep(0.8)
        cmds = [c for f in tx if APCICodec.frame_type_of(f) == "I"
                for c in [_decode_i(f)] if c["type_id"] == TypeID.C_SE_NC_1]
        selects = [c for c in cmds if c["select"]]
        execs = [c for c in cmds if not c["select"]]
        ok = len(selects) == 1 and len(execs) == 1
        detail = (f"设点命令帧: {[(c['type_id'], c['select']) for c in cmds]} "
                  f"(期望 选择×1 + 执行×1，命中 sbo=true YK 点)")
        record("8a. 设点(命中 sbo=true YK 点) -> 自动两段式", ok, detail)
    finally:
        await _stop(master, slave)


async def sc8b_setpoint_plain_yc_direct():
    """设点：不在 YK 点表中的普通 YC 点 -> 直发执行（向后兼容）."""
    port = _free_port()
    pt = _pt(sbo_true_ioas=[IOA_SBO_TRUE], sbo_false_ioas=[IOA_SBO_FALSE])
    # 加入一个纯 YC 点（不在 YK 表中）
    from core.data.point_table import YcPointDef
    pt.add_yc(YcPointDef(ioa=IOA_YC_PLAIN, name="YC_plain"))
    slave = SlaveEngine(host="127.0.0.1", port=port, common_addr=1, point_table=pt)
    slave.data_store.init_from_point_table(pt)
    master = MasterEngine(host="127.0.0.1", port=port, common_addr=1,
                          auto_start=True, auto_gi=False, reconnect=False, point_table=pt)
    tx: list[bytes] = []
    master.set_raw_frame_callback(lambda d, direction: tx.append(d) if direction == "tx" else None)
    await slave.start()
    await master.start()
    assert await _wait_until(lambda: str(master.state).lower() == "running", timeout=8)
    try:
        tx.clear()
        await master.setpoint_shortfloat(IOA_YC_PLAIN, 55.5, select=False)
        await asyncio.sleep(0.6)
        cmds = [c for f in tx if APCICodec.frame_type_of(f) == "I"
                for c in [_decode_i(f)] if c["type_id"] == TypeID.C_SE_NC_1]
        selects = [c for c in cmds if c["select"]]
        execs = [c for c in cmds if not c["select"]]
        ok = len(selects) == 0 and len(execs) == 1
        detail = (f"设点命令帧: {[(c['type_id'], c['select']) for c in cmds]} "
                  f"(期望 直发执行×1，YC 不在 YK 表)")
        record("8b. 设点(纯 YC 点，不在 YK 表) -> 直发执行", ok, detail)
    finally:
        await _stop(master, slave)


async def sc9_regulating_sbo_true():
    """升降命令 (C_RC_NA_1) 对 sbo=true 点也应自动两段式（master 亦改动此路径）."""
    # 需一个 sbo=true 的 YK 点，复用 IOA_SBO_TRUE
    master, slave, tx = await _real_pair()
    try:
        tx.clear()
        await master.regulating_step_command(IOA_SBO_TRUE, 2, select=False, qu=0)
        await asyncio.sleep(0.8)
        cmds = [c for f in tx if APCICodec.frame_type_of(f) == "I"
                for c in [_decode_i(f)] if c["type_id"] == TypeID.C_RC_NA_1]
        selects = [c for c in cmds if c["select"]]
        execs = [c for c in cmds if not c["select"]]
        ok = len(selects) == 1 and len(execs) == 1
        detail = f"升降命令帧: {[(c['select']) for c in cmds]} (期望 选择×1 + 执行×1)"
        record("9. 升降命令 sbo=true -> 自动两段式", ok, detail)
    finally:
        await _stop(master, slave)


async def sc10_unknown_ioa_no_raise():
    """边界：对点表中不存在的 IOA 遥控 -> 不强制 SBO、单帧、不抛异常."""
    master, slave, tx = await _real_pair()
    try:
        tx.clear()
        err = None
        try:
            await master.single_command(9999, True, select=False, qu=0)
        except Exception as e:  # noqa: BLE001
            err = repr(e)
        await asyncio.sleep(0.5)
        cmds = [c for f in tx if APCICodec.frame_type_of(f) == "I"
                for c in [_decode_i(f)] if c["type_id"] == TypeID.C_SC_NA_1]
        ok = err is None and len(cmds) == 1 and not cmds[0]["select"]
        detail = f"帧={[(c['ioa'], c['select']) for c in cmds]}; 异常={err} (期望 单帧执行, 无异常)"
        record("10. 未定义 IOA 遥控 -> 单帧、不抛异常", ok, detail)
    finally:
        await _stop(master, slave)


async def sc11_repeated_select_then_execute():
    """边界：重复选择后执行 -> 不崩溃，主机仍能完成一次执行（子站选择状态被覆盖）."""
    master, slave, tx = await _real_pair()
    try:
        tx.clear()
        # 显式连续两次选择
        await master.single_command(IOA_SBO_TRUE, True, select=True, qu=0)
        await asyncio.sleep(0.2)
        await master.single_command(IOA_SBO_TRUE, True, select=True, qu=0)
        await asyncio.sleep(0.2)
        # 再执行
        err = None
        try:
            await master.single_command(IOA_SBO_TRUE, True, select=False, qu=0)
        except Exception as e:  # noqa: BLE001
            err = repr(e)
        await asyncio.sleep(0.6)
        cmds = [c for f in tx if APCICodec.frame_type_of(f) == "I"
                for c in [_decode_i(f)] if c["type_id"] == TypeID.C_SC_NA_1]
        sel = [c for c in cmds if c["select"]]
        exe = [c for c in cmds if not c["select"]]
        # 2 次显式选择 + 第 3 次(select=False)自动补选择 = 3 选择帧；随后 1 执行帧
        ok = err is None and len(sel) == 3 and len(exe) == 1
        detail = (f"帧 select={len(sel)} execute={len(exe)}; 异常={err} "
                  f"(期望 2显式选择 + 1自动选择 = 3 选择, 1 执行, 无异常)")
        record("11. 重复选择后执行 -> 稳健", ok, detail)
    finally:
        await _stop(master, slave)


async def sc7_stale_actterm_before_actcon():
    """竞态（注入式）：选择等待期间先收到滞后 ACTTERM，再收到 ACTCON(PN=0).

    正确的实现必须忽略非 ACTCON 帧，选择判定为成功、不抛异常。
    """
    master, fake, tx = await _master_against_fake("stale_actterm", t1=1.0)
    try:
        tx.clear()
        err = None
        try:
            await master.single_command(IOA_SBO_TRUE, True, select=False, qu=0)
        except Exception as e:  # noqa: BLE001
            err = str(e)
        await asyncio.sleep(0.4)
        cmds = [c for f in tx if APCICodec.frame_type_of(f) == "I"
                for c in [_decode_i(f)] if c["type_id"] == TypeID.C_SC_NA_1]
        selects = [c for c in cmds if c["select"]]
        execs = [c for c in cmds if not c["select"]]
        # 滞后 ACTTERM 被忽略 => 选择成功 => 随后发出执行帧
        ok = err is None and len(selects) == 1 and len(execs) == 1
        detail = (f"select={len(selects)} execute={len(execs)}; 异常={err!r} "
                  f"(期望 滞后 ACTTERM 被忽略, 选择成功并发出执行帧)")
        record("7. 滞后 ACTTERM 先于 ACTCON（注入竞态）-> 选择不被误判", ok, detail)
    finally:
        await _stop(master, fake)


async def _stop(master, other):
    try:
        await asyncio.wait_for(master.stop(), timeout=6)
    except Exception:
        pass
    try:
        await asyncio.wait_for(other.stop(), timeout=6)
    except Exception:
        pass


async def main() -> int:
    for sc in (sc1_auto_two_phase, sc2_sbo_false_single_frame,
               sc3_select_rejected_no_execute, sc4_select_timeout_no_execute,
               sc5_explicit_select_unchanged, sc6_lagging_actterm_race,
               sc7_stale_actterm_before_actcon, sc8_setpoint_two_phase_on_sbo_yk,
               sc8b_setpoint_plain_yc_direct, sc9_regulating_sbo_true,
               sc10_unknown_ioa_no_raise, sc11_repeated_select_then_execute):
        try:
            await sc()
        except Exception as e:  # noqa: BLE001
            record(sc.__name__, False, f"场景执行异常: {type(e).__name__}: {e}")

    print("\n===== 汇总 =====")
    passed = sum(1 for _, s, _ in _results if s == PASS)
    for name, status, _ in _results:
        print(f"  {status}  {name}")
    print(f"共 {len(_results)} 项，通过 {passed}，失败 {len(_results) - passed}")
    return 0 if passed == len(_results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
