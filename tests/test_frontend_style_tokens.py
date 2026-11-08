"""前端配色令牌静态门禁（设计一致性，第一类可自动发现问题）.

规则：组件/页面里出现硬编码颜色（#hex / rgb() / rgba()）即失败——颜色必须
来自 `theme.ts` 的 antd token 或 `global.css` 的主题变量，否则深/浅主题切换时
会出现「一边能看、一边看不见」的死角。

允许清单：
- `src/theme.ts`：主题令牌定义本身；
- `src/styles/global.css`：html/body 的基础底色（theme token 之外的最小兜底）；
- `src/kit/KitSwitcher.tsx`：套件切换器在任何套件样式加载前就要显示，刻意零依赖；
- `src/classic/**`：冻结的经典版 v1.3.1 UI 快照（对照界面，不再演进）；
- 测试文件：可能断言具体颜色值。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "webui" / "frontend" / "src"

COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b|\brgba?\([^)]*\)")
ALLOWED = {
    Path("theme.ts"),
    Path("styles/global.css"),
    # 界面套件切换器/过渡屏必须能在「任何套件样式都未加载」时显示，因此刻意不依赖
    # PF token / antd token，颜色写死并与 uiStore 的深浅主题一一对应。
    Path("kit/KitSwitcher.tsx"),
    Path("kit/KitSplash.tsx"),
}

# 冻结的经典版（v1.3.1 UI 快照，见 docs/ui_kits.md）：按当年的 antd 主题写死少量
# 状态色，只作为对照界面，不再演进；token 门禁只约束当前主界面（PF）。
FROZEN_KITS = {"classic"}


def _files() -> list[Path]:
    return [
        p for p in SRC.rglob("*")
        if p.suffix in (".ts", ".tsx", ".css")
        and ".test." not in p.name
        and p.relative_to(SRC) not in ALLOWED
        and p.relative_to(SRC).parts[0] not in FROZEN_KITS
    ]


def _strip_comments(text: str) -> str:
    """把注释内容替换成空格（保留换行，行号不漂移）."""
    def blank(match: re.Match[str]) -> str:
        return re.sub(r"[^\n]", " ", match.group(0))

    text = re.sub(r"/\*.*?\*/", blank, text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", blank, text)
    return text


def test_no_hardcoded_colors_outside_theme() -> None:
    problems: list[str] = []
    for path in _files():
        code = _strip_comments(path.read_text(encoding="utf-8"))
        for lineno, line in enumerate(code.splitlines(), 1):
            for match in COLOR_RE.finditer(line):
                problems.append(
                    f"{path.relative_to(SRC)}:{lineno}: {match.group(0)} → 请改用 theme token/CSS 变量"
                )
    assert not problems, "组件里存在硬编码颜色：\n" + "\n".join(f"  - {p}" for p in problems)
