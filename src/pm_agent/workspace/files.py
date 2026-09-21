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
