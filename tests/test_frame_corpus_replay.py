"""互操作语料库回放回归.

目标：把“真机/现场报文”变成可重复执行的回归资产。

- 合成基线（本目录 ``*.i104``）锁定解码行为与主站入库结果；
- ``real/`` 下的真机抓包只要放入即可参与逐帧可解码冒烟；
- 每个场景的 golden 快照来自 ``generate_corpus.py`` 生成的 ``manifest.json``，
  解码行为变化会让本测试失败，提示更新语料或修复回归。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.capture.format import DIRECTION_RX, CaptureFile
from core.data.point_table import PointTable
from core.engine.master import MasterEngine
from core.protocol.types import ConnState
from tests.fixtures.frames.generate_corpus import frame_summary

CORPUS_DIR = Path(__file__).parent / "fixtures" / "frames"
MANIFEST = json.loads((CORPUS_DIR / "manifest.json").read_text(encoding="utf-8"))
SCENARIOS = MANIFEST["scenarios"]
SCENARIO_IDS = [s["name"] for s in SCENARIOS]

# 真机语料可选登记：文件名 → 回放后应看到的点值（格式同 manifest.master_checks）。
# 未登记的 real/*.i104 仍会跑“逐帧可解码”冒烟，只是不做业务值断言。
REAL_EXPECTATIONS: dict[str, list[dict]] = {}


def _load_scenario(name: str):
    scenario = next(s for s in SCENARIOS if s["name"] == name)
    header, frames = CaptureFile.load_binary(CORPUS_DIR / scenario["file"])
    return scenario, header, frames


def _corpus_files() -> list[Path]:
    files: list[Path] = []
    for root in (CORPUS_DIR, CORPUS_DIR / "real"):
        for pattern in ("*.i104", "*.json"):
            files.extend(
                p for p in sorted(root.glob(pattern)) if p.name != "manifest.json"
            )
    return files


def _make_engine() -> MasterEngine:
    """构造一个不建真连接的主站引擎（TCPClient 全部 mock）."""
    with patch("core.engine.master.TCPClient") as mock_client_cls:
        client = mock_client_cls.return_value
        client.start = AsyncMock()
        client.stop = AsyncMock()
        client.send = AsyncMock()
        client.disconnect = AsyncMock()
        client.stats = MagicMock()
        engine = MasterEngine(
            host="127.0.0.1", port=2404, common_addr=1,
            auto_start=False, auto_gi=False, reconnect=False,
            point_table=PointTable(),
        )
    return engine


async def _replay(engine: MasterEngine, frames) -> None:
    """把 RX 方向帧喂给主站引擎；U/S/I 帧均走真实分发路径."""
    engine._state_machine._state = ConnState.RUNNING
    for frame in frames:
        if frame.direction == DIRECTION_RX:
            engine._on_frame_received(frame.frame_data)
            # 让 _spawn 出来的 S 帧发送/事件任务跑完
            await asyncio.sleep(0)


def _assert_point(engine: MasterEngine, check: dict) -> None:
    kind, ioa, expected = check["kind"], check["ioa"], check["value"]
    getter = {
        "yx": engine.data_store.get_yx,
        "yc": engine.data_store.get_yc,
        "ym": engine.data_store.get_ym,
    }[kind]
    actual = getter(ioa)
    assert actual is not None, f"{kind.upper()} IOA {ioa} 未入库（回放未生效）"
    if isinstance(expected, float):
        assert actual.value == pytest.approx(expected, abs=1e-3), (
            f"{kind.upper()} IOA {ioa}: {actual.value} != {expected}"
        )
    else:
        assert actual.value == expected, (
            f"{kind.upper()} IOA {ioa}: {actual.value!r} != {expected!r}"
        )


def test_manifest_is_tracked_and_complete() -> None:
    assert MANIFEST["version"] == 1
    assert len(SCENARIOS) >= 7
    names = {s["name"] for s in SCENARIOS}
    # 关键场景必须存在，避免后续重构把语料删空
    assert {
        "gi_basic", "soe_burst", "cp24_variants", "silent_device",
        "sbo_command", "param_file", "malformed",
    } <= names


def test_corpus_covers_key_protocol_paths() -> None:
    type_names = {
        frame.get("type_name")
        for scenario in SCENARIOS
        for frame in scenario["frames"]
        if frame.get("type_name")
    }
    required = {
        "C_IC_NA_1", "C_SC_NA_1",
        "M_SP_NA_1", "M_DP_NA_1", "M_ME_NA_1", "M_ME_NB_1", "M_ME_NC_1",
        "M_IT_NA_1", "M_SP_TB_1", "M_DP_TB_1", "M_ME_TF_1",
        "M_IT_TA_1", "M_ME_TA_1", "M_ME_TB_1", "M_ME_TC_1", "M_IT_TB_1",
        "M_ST_TB_1", "M_EI_NA_1",
        "P_ME_NA_1", "P_AC_NA_1",
        "F_FR_NA_1", "F_FR_NB_1", "F_SR_NA_1", "F_AF_NA_1",
        "F_SG_NA_1", "F_LS_NA_1",
    }
    missing = required - type_names
    assert not missing, f"语料缺少关键类型：{sorted(missing)}"


@pytest.mark.parametrize("scenario", SCENARIOS, ids=SCENARIO_IDS)
def test_golden_decode_matches_manifest(scenario: dict) -> None:
    """逐帧解码结果必须与 manifest 的 golden 快照一致."""
    _, frames = CaptureFile.load_binary(CORPUS_DIR / scenario["file"])
    assert len(frames) == len(scenario["frames"])

    for index, (frame, expected) in enumerate(
        zip(frames, scenario["frames"], strict=True)
    ):
        actual = frame_summary(frame)
        assert actual == expected, (
            f"{scenario['name']} 第 {index} 帧解码结果与 manifest 不一致；"
            "若确认是有意变更，请重跑 generate_corpus.py 并提交新基线"
        )


@pytest.mark.parametrize("scenario", SCENARIOS, ids=SCENARIO_IDS)
async def test_master_replay_restores_points(scenario: dict) -> None:
    """把 RX 帧按真实分发路径回放，断言点值/静默设备行为."""
    engine = _make_engine()
    _, _, frames = _load_scenario(scenario["name"])
    await _replay(engine, frames)

    if scenario["name"] == "silent_device":
        # 只发 EI 的静默装置：不得凭空产生点
        assert not engine.data_store.get_yx_ref()
        assert not engine.data_store.get_yc_ref()
        assert not engine.data_store.get_ym_ref()

    for check in scenario["master_checks"]:
        _assert_point(engine, check)


async def test_malformed_frames_do_not_break_following_frames() -> None:
    """畸形帧（截断/未知类型/长度不足）后，后续合法帧仍必须入库."""
    scenario, _, frames = _load_scenario("malformed")
    assert any(
        frame.get("decode_error") or frame.get("asdu_decode_error")
        for frame in scenario["frames"]
    ), "畸形帧语料退化成了全合法帧，回归价值已丢失"

    engine = await _replay_and_get("malformed")
    assert engine.data_store.get_yx(800) is not None
    assert engine.data_store.get_yx(801) is not None


async def _replay_and_get(name: str) -> MasterEngine:
    engine = _make_engine()
    _, _, frames = _load_scenario(name)
    await _replay(engine, frames)
    return engine


def test_every_corpus_file_is_loadable() -> None:
    """合成基线与 real/ 真机抓包都应能被 CaptureFile 读取."""
    files = _corpus_files()
    assert files, "语料目录为空"
    for path in files:
        header, frames = CaptureFile.load(path)
        assert header is not None
        assert frames, f"{path.name} 未解析出任何帧"
        for frame in frames:
            assert frame.frame_data, f"{path.name} 含空帧"
            frame_summary(frame)  # 不抛出即视为可解码（畸形帧已在内部捕获）


def test_corpus_exports_to_wireshark_pcap(tmp_path: Path) -> None:
    """语料可直接导出为 Wireshark 识别的 pcap（合成 TCP 头）."""
    _, frames = _load_scenario("gi_basic")[1:]
    out = tmp_path / "gi_basic.pcap"
    count = CaptureFile.save_pcap(out, frames, created=MANIFEST["created"])
    assert count == len(frames)

    _, loaded = CaptureFile.load_pcap(out)
    assert [f.frame_data for f in loaded] == [f.frame_data for f in frames]


def test_real_corpus_expectations_are_valid() -> None:
    """REAL_EXPECTATIONS 只能登记实际存在的 real/ 文件与合法点值类型."""
    real_dir = CORPUS_DIR / "real"
    for filename, checks in REAL_EXPECTATIONS.items():
        assert (real_dir / filename).is_file(), f"登记了不存在的真机语料：{filename}"
        for check in checks:
            assert check["kind"] in {"yx", "yc", "ym"}
