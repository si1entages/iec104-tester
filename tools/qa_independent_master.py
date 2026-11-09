"""独立的极简 IEC 60870-5-104 主站客户端（验收用，不依赖本项目 core/）.

字节级按标准手写：STARTDT → 总召唤 → 读数据 → 停止。用于验证本工具的**子站**
能被第三方软件（非本项目引擎）真实连上、读数、收自发帧。
"""

from __future__ import annotations

import socket
import struct
import sys
import time


def i_frame(vs: int, vr: int, asdu: bytes) -> bytes:
    return b"\x68" + bytes([len(asdu) + 4]) + struct.pack("<HH", vs * 2, vr * 2) + asdu


def s_frame(vr: int) -> bytes:
    return b"\x68\x04" + struct.pack("<HH", 1, vr * 2)


def u_frame(kind: bytes) -> bytes:
    return b"\x68\x04" + kind + b"\x00\x00"


def gi_asdu(ca: int = 1) -> bytes:
    # C_IC_NA_1(100): type=100, vsq=1, cot=6(act), ca, ioa=0, qoi=20
    return bytes([100, 1, 6, 0]) + struct.pack("<H", ca) + b"\x00\x00\x00" + bytes([20])


def parse_frames(buf: bytes) -> list[tuple[str, bytes]]:
    frames: list[tuple[str, bytes]] = []
    i = 0
    while i + 2 <= len(buf):
        if buf[i] != 0x68:
            i += 1
            continue
        length = buf[i + 1]
        if len(buf) < i + 2 + length:
            break
        body = buf[i + 2 : i + 2 + length]
        c1 = body[0]
        if c1 & 0x01 == 0:
            frames.append(("I", body))   # I 帧: bit0=0（VS=1 时 c1=0x02 也归此类）
        elif c1 & 0x03 == 0x03:
            frames.append(("U", body))   # U 帧: bit0=bit1=1
        else:
            frames.append(("S", body))   # S 帧: bit0=1, bit1=0 (c1=0x01)
        i += 2 + length
    return frames


def main(host: str, port: int, seconds: float) -> int:
    sock = socket.create_connection((host, port), timeout=3)
    sock.settimeout(0.5)
    vs, vr = 0, 0
    events: list[str] = []

    # STARTDT
    sock.sendall(u_frame(b"\x07\x00"))
    t0 = time.time()
    got_con = False
    while time.time() - t0 < 3 and not got_con:
        try:
            data = sock.recv(4096)
        except socket.timeout:
            continue
        for kind, body in parse_frames(data):
            if kind == "U" and body[0] == 0x0B:
                got_con = True
                events.append("STARTDT_CON ✓")
    if not got_con:
        print("FAIL: STARTDT 无确认")
        return 1

    # 总召唤
    sock.sendall(i_frame(vs, vr, gi_asdu()))
    vs += 1
    t0 = time.time()
    actcon = actterm = False
    data_points: dict[int, tuple[int, float]] = {}
    frames_rx = 0
    while time.time() - t0 < seconds and not (actcon and actterm):
        try:
            data = sock.recv(8192)
        except socket.timeout:
            continue
        if not data:
            break
        vr_last = vr
        for kind, body in parse_frames(data):
            frames_rx += 1
            if kind == "I":
                vr = ((body[3] << 8) | body[2]) >> 1
                asdu = body[4:]
                if len(asdu) < 6:
                    continue
                tid, vsq = asdu[0], asdu[1]
                cot = asdu[2] & 0x3F
                if tid == 100 and cot == 7:
                    actcon = True
                    events.append("GI_ACTCON ✓")
                elif tid == 100 and cot == 10:
                    actterm = True
                    events.append("GI_ACTTERM ✓")
                elif tid in (1, 2, 13, 15, 30, 45, 46, 50) and cot in (3, 20, 21):
                    # SQ=0：每个对象 IOA(3B)+数据；SQ=1：首对象 IOA(3B)+N 个连续值
                    sq = vsq & 0x80
                    count = vsq & 0x7F
                    off = 6
                    if not sq:
                        for _ in range(count):
                            if off + 3 > len(asdu):
                                break
                            ioa = asdu[off] | (asdu[off + 1] << 8) | (asdu[off + 2] << 16)
                            if tid == 1 and off + 4 <= len(asdu):
                                data_points[ioa] = (tid, float(asdu[off + 3] & 1))
                                off += 4
                            elif tid == 13 and off + 8 <= len(asdu):
                                data_points[ioa] = (tid, struct.unpack("<f", asdu[off + 3 : off + 7])[0])
                                off += 8
                            else:
                                break
                    else:
                        if off + 3 > len(asdu):
                            continue
                        base = asdu[off] | (asdu[off + 1] << 8) | (asdu[off + 2] << 16)
                        off += 3
                        step = 1 if tid == 1 else 5
                        for k in range(count):
                            ioa = base + k
                            if tid == 1 and off + 1 <= len(asdu):
                                data_points[ioa] = (tid, float(asdu[off] & 1))
                            elif tid == 15 and off + 5 <= len(asdu):
                                data_points[ioa] = (tid, float(struct.unpack("<i", asdu[off : off + 4])[0]))
                            elif tid == 13 and off + 5 <= len(asdu):
                                data_points[ioa] = (tid, struct.unpack("<f", asdu[off : off + 4])[0])
                            off += step
        # 服务端攒了未确认帧就 S 帧确认（每 8 帧或超 1s）
        if vr != vr_last and frames_rx % 8 == 0:
            sock.sendall(s_frame(vr))
    if vr != (0 if frames_rx == 0 else vr):
        sock.sendall(s_frame(vr))

    print(f"连接: {host}:{port}")
    for e in events:
        print(" ", e)
    print(f"  收到帧: {frames_rx}，总召唤数据点: {len(data_points)}")
    for ioa in sorted(data_points)[:8]:
        print(f"    IOA={ioa} type={data_points[ioa][0]} value={data_points[ioa][1]}")

    # listen 模式（seconds>5 时启用）：继续挂在线上收自发帧（COT=3 等），
    # 验证子站工作台的手动置数 / 响应注入能到达**外部**主站
    if seconds > 5:
        t1 = time.time()
        spont: dict[tuple[int, int], int] = {}
        while time.time() - t1 < seconds - 5:
            try:
                data = sock.recv(8192)
            except socket.timeout:
                continue
            if not data:
                break
            for kind, body in parse_frames(data):
                if kind != "I":
                    continue
                vr = ((body[3] << 8) | body[2]) >> 1
                asdu = body[4:]
                if len(asdu) < 6:
                    continue
                tid, cot = asdu[0], asdu[2] & 0x3F
                pn = bool(asdu[2] & 0x40)
                spont[(tid, cot, pn)] = spont.get((tid, cot, pn), 0) + 1
        print(
            "  监听期自发帧统计:",
            {f"type{k[0]}/cot{k[1]}/pn{int(k[2])}": v for k, v in sorted(spont.items())},
        )

    # STOPDT 后关闭
    sock.sendall(u_frame(b"\x13\x00"))
    time.sleep(0.3)
    sock.close()
    ok = got_con and actcon and actterm and len(data_points) > 0
    print("RESULT:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    host = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 2404
    secs = float(sys.argv[3]) if len(sys.argv) > 3 else 5.0
    sys.exit(main(host, port, secs))
