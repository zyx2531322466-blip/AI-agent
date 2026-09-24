"""Markdown + YAML frontmatter 的读写。

为什么自己写而不引第三方库：我们的格式只有一种形态——
开头一段 YAML 前置数据，后面是正文。几十行足够，
少一个依赖就少一处需要解释的东西（对应原则 5：每个阶段可讲解）。

用途：``sessions/`` 交接记录与 ``decisions/`` 决策记录都需要
「人能读的正文 + 程序能读的元数据」这种混合形态。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..errors import FormatError

FRONTMATTER_FENCE = "---"


def split_frontmatter(text: str) -> tuple[dict[str, Any], str, bool]:
    """拆出 (元数据, 正文, 是否有 frontmatter)。

    没有 frontmatter 时返回 ``({}, 原文, False)``，不算错误——
    因为规范与任务清单允许是纯人写的文档。
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != FRONTMATTER_FENCE:
        return {}, text, False

    for index in range(1, len(lines)):
        if lines[index].strip() == FRONTMATTER_FENCE:
            raw = "\n".join(lines[1:index])
            body = "\n".join(lines[index + 1 :]).lstrip("\n")
            try:
                meta = yaml.safe_load(raw) or {}
            except yaml.YAMLError as exc:
                raise FormatError(
                    f"frontmatter 的 YAML 解析失败：{exc}",
                    hint="frontmatter 是开头两条 --- 之间的部分，检查缩进与引号",
                ) from exc
            if not isinstance(meta, dict):
                raise FormatError(
                    "frontmatter 必须是「键: 值」结构",
                    hint="例如 status: ok、created: 2026-09-13",
                )
            return meta, body, True

    raise FormatError(
        "frontmatter 只有开头的 ---，没有结束的 ---",
        hint="在元数据后面再补一行 ---",
    )


def read_markdown(path: Path) -> tuple[dict[str, Any], str]:
    """读取一个 Markdown 文件，返回 (元数据, 正文)。"""
    text = path.read_text(encoding="utf-8")
    meta, body, _ = split_frontmatter(text)
    return meta, body


def render_markdown(meta: dict[str, Any] | None, body: str) -> str:
    """渲染成「frontmatter + 正文」的文本。"""
    body = body.strip("\n")
    if not meta:
        return body + "\n"
    head = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    return f"{FRONTMATTER_FENCE}\n{head}\n{FRONTMATTER_FENCE}\n\n{body}\n"


def strip_code_fence(text: str) -> str:
    """去掉最外层的一对代码围栏（如果有）。"""
    fence = "`" * 3
    stripped = text.strip()
    if not (stripped.startswith(fence) and stripped.endswith(fence)):
        return text
    first_newline = stripped.find("\n")
    if first_newline == -1:
        return text
    return stripped[first_newline + 1 : -len(fence)]


def clean_model_reply(reply: str) -> str:
    """把模型回复清理成干净的正文：剥掉它自作主张加的 frontmatter 与最外层围栏。

    模型常干这两件多余的事，而两者混进落盘的文件里都会让人看到不该有的东西。
    抽在这里是因为**不只一个阶段要用**（specify 与 work 都要），
    规则只该有一处定义，否则两边的清理行为迟早分叉。
    """
    _, body, _ = split_frontmatter(reply)
    return strip_code_fence(body).strip("\n") + "\n"


def set_frontmatter_line(text: str, key: str, value: str) -> str:
    """在 frontmatter 里设置一个键；没有 frontmatter 就在开头补一个。

    **行级手术**：只动那一行（或插入一行），其余部分逐字不动。
    先解析再整体重新渲染会把空行、缩进一起重排——"只改该改的"就成了一句空话。

    ``value`` 是已经渲染好的 YAML 片段（例如 ``12``、``[FR-001, FR-002]``）。
    """
    trailing = "\n" if text.endswith("\n") else ""
    lines = text.split("\n")
    if trailing:
        lines = lines[:-1]

    if lines and lines[0].strip() == FRONTMATTER_FENCE:
        for index in range(1, len(lines)):
            if lines[index].strip() != FRONTMATTER_FENCE:
                continue
            for offset in range(1, index):
                if lines[offset].split(":", 1)[0].strip() == key:
                    lines[offset] = f"{key}: {value}"
                    return "\n".join(lines) + trailing
            lines.insert(index, f"{key}: {value}")
            return "\n".join(lines) + trailing

    head = [FRONTMATTER_FENCE, f"{key}: {value}", FRONTMATTER_FENCE, ""]
    return "\n".join([*head, *lines]) + trailing
