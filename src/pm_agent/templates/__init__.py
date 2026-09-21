"""内置模板（作为包数据随程序一起分发）。

改模板时请同步检查 ``pm_agent/workspace/format.py`` 的校验规则：
模板生成出来的文件必须能通过 ``check_workspace``，
否则 ``create_project`` 的自检会直接报错。
"""

from __future__ import annotations

from importlib.resources import files

PLACEHOLDER_OPEN = "{{"
PLACEHOLDER_CLOSE = "}}"


def load(name: str) -> str:
    """读取原始模板文本。"""
    return files(__name__).joinpath(name).read_text(encoding="utf-8")


def render_template(name: str, context: dict[str, str]) -> str:
    """渲染 ``{{key}}`` 占位符。

    渲染后若还有没被替换的占位符，直接报错——宁可现在报错，
    也不要把 ``{{goal}}`` 这样的字符串留在使用者的项目里。
    """
    text = load(name)
    for key, value in context.items():
        text = text.replace(f"{PLACEHOLDER_OPEN}{key}{PLACEHOLDER_CLOSE}", value)
    if PLACEHOLDER_OPEN in text:
        leftover = text[text.index(PLACEHOLDER_OPEN) :][:40]
        raise ValueError(f"模板 {name} 里有未替换的占位符：{leftover}")
    return text
