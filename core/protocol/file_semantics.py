"""文件传输语义档位（WP3a）.

把 5 项开放项（NOF / SCQ / WITH_DEACT / 多节 / FRQ-SRQ）中**有歧义、
且多实现不一致**的口径从硬编码常量提升为**显式配置**，而不是靠猜改默认值。

依据（2026-11-12 新口径：互测 + 多独立开源实现交叉证据）：
- lib60870-C v2.4.1：无目录处理器；select=1/request=2/request-section=6；
  否定 F_FR status=0x80；LSQ=3(节)/1(文件)；不要求 DEACT。
- lib60870.NET（MZ Automation）：**目录触发的充分必要条件是 COT=REQUEST(5)**，
  SCQ 值不参与判断；F_DR_TA_1 SQ=1 多对象；否定 F_SC 用 COT=47。
- otfabric/iec104-interop v0.6.0（5 栈矩阵）：目录口径 `F_SC SCQ=0 COT=5 →
  F_DR_TA_1 + LFD`；否定确认 COT 44~47；25 配对 3071 passed。

档位：
- ``ed2``：以 lib60870.NET / otfabric 共识为准（目录 COT=REQ(5)、SCQ=0）；
- ``ed1``：保守口径（目录 COT=FILE(13)、SCQ=5 项目约定，兼容既有本仓行为）；
- ``project``：完全等同 ed1（历史默认），命名上明确它是"项目约定"而非标准。

**默认 ed1/project 不变**：已有 golden 帧与既有测试全部依赖它；改档位是显式动作。
"""

from __future__ import annotations

from dataclasses import dataclass

from .types import COT

#: 档位名（配置里只能取这三个）
PROFILES = ("ed1", "ed2", "project")


@dataclass(frozen=True)
class FileSemantics:
    """一组可判定的文件传输语义参数."""

    profile: str = "ed1"
    #: 目录召唤的传送原因
    directory_cot: int = int(COT.FILE)
    #: 目录召唤的 SCQ（0 = 未用 / 5 = 项目约定 SELECT_SECTION 复用）
    directory_scq: int = 5
    #: NOF 是否按 Ed.2 枚举校验（0=DEFAULT 1=TRANSPARENT 2=DISTURBANCE…）
    nof_enum: bool = False
    #: FRQ/SRQ 否定标志位（lib60870 口径 0x80；Schneider 资料为 0x01）
    negative_flag: int = 0x80
    #: 收到 LSQ=2/4 后是否补发去激活（多实现观察：均不要求）
    send_deact_on_with_deact: bool = False
    #: 从站分包的最大节字节数（0 = 单节，保持历史行为）
    section_size: int = 0

    def describe(self) -> str:
        return (
            f"profile={self.profile} directory=COT{self.directory_cot}/SCQ{self.directory_scq} "
            f"nof_enum={self.nof_enum} negative_flag=0x{self.negative_flag:02x} "
            f"deact={self.send_deact_on_with_deact} section_size={self.section_size}"
        )


#: ed1 / project：历史默认（本仓既有 golden 帧依赖，逐字节不变）
ED1 = FileSemantics(profile="ed1")
PROJECT = FileSemantics(profile="project")

#: ed2：lib60870.NET + otfabric 共识口径
ED2 = FileSemantics(
    profile="ed2",
    directory_cot=int(COT.REQ),   # 5
    directory_scq=0,               # 目录不依赖 SCQ
    nof_enum=True,
    negative_flag=0x80,
    send_deact_on_with_deact=False,
    section_size=0,
)

_REGISTRY = {"ed1": ED1, "ed2": ED2, "project": PROJECT}


def resolve(profile: str | None, *, section_size: int | None = None,
            nof_enum: bool | None = None) -> FileSemantics:
    """解析档位名 → 语义对象；非法名抛 ``ValueError``（不静默兜底）.

    ``section_size`` / ``nof_enum`` 是逐项覆盖，便于现场只改一个歧义点而不换档。
    """
    name = (profile or "ed1").strip().lower()
    if name not in _REGISTRY:
        raise ValueError(f"未知文件传输语义档位 {profile!r}（可选 {PROFILES}）")
    base = _REGISTRY[name]
    if section_size is None and nof_enum is None:
        return base
    return FileSemantics(
        profile=base.profile,
        directory_cot=base.directory_cot,
        directory_scq=base.directory_scq,
        nof_enum=base.nof_enum if nof_enum is None else bool(nof_enum),
        negative_flag=base.negative_flag,
        send_deact_on_with_deact=base.send_deact_on_with_deact,
        section_size=base.section_size if section_size is None
        else max(0, int(section_size)),
    )


def known_nof_values() -> dict[int, str]:
    """Ed.2 NOF 枚举（供界面提示 / 校验；不是全部标准值，仅常见项）."""
    return {
        0: "DEFAULT",
        1: "TRANSPARENT_FILE",
        2: "DISTURBANCE_DATA",
        3: "SEQUENCE_OF_EVENTS",
        4: "SEQUENCE_OF_ANALOGUE_VALUES",
    }
