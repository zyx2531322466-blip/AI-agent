"""提示词（作为包数据随程序一起分发）。

提示词是**内容**不是逻辑，所以放文件里：改它不用碰代码，它本身也能被人读、
被评审，以后 FR-049 的讲解模式还可以直接把原文展示出来。

每个阶段一对文件：

- ``*.system.md``：**规则**——你是谁、必须遵守什么，不含占位符；
- ``*.user.md``：**数据**——这次要处理什么，含 ``{{占位符}}``。

把规则和数据分开，不只是为了整洁：使用者给的目标属于"数据"，
放进 system 里就可能被当成指令（提示词注入的入口）。
分开写，这条边界才是清楚的。
"""

from __future__ import annotations

from importlib.resources import files

from ..templates import render_text


def load(name: str) -> str:
    """读取原始提示词文本。"""
    return files(__name__).joinpath(name).read_text(encoding="utf-8")


def render(name: str, context: dict[str, str]) -> str:
    """读取并渲染提示词里的占位符。"""
    return render_text(load(name), context, source=f"提示词 prompts/{name}")


__all__ = ["load", "render"]
