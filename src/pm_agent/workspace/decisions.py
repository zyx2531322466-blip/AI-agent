"""决策记录：把"当初为什么这么定"留下来（T069 / T070）。

FR-036 要五样东西：背景、备选方案、最终选择、理由、时间。缺一不可——
少了「备选」就不知道还有没有别的路，少了「理由」就只剩结论，下次还得重新争一遍。

落在 ``decisions/<日期>-<标题>.md``：人能直接打开读，也能被追溯链搜到。
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from pathlib import Path

from ..errors import WorkspaceError
from .changes import Change
from .files import render_markdown, split_frontmatter
from .store import Project

DECISIONS_DIR = "decisions"


@dataclass(frozen=True)
class Decision:
    """一条决策记录。"""

    title: str
    date: str
    background: str
    options: tuple[str, ...]
    choice: str
    why: str
    path: Path

    def render(self) -> str:
        options = "\n".join(f"    - {item}" for item in self.options)
        return (
            f"**{self.title}**（{self.date}）\n"
            f"  背景：{self.background}\n"
            f"  备选方案：\n{options}\n"
            f"  最终选择：{self.choice}\n"
            f"  理由：{self.why}"
        )


def record_decision(
    project: Project,
    *,
    title: str,
    background: str,
    options: list[str] | tuple[str, ...],
    choice: str,
    why: str,
    moment: dt.datetime | None = None,
    reason: str = "",
) -> Change:
    """产出一份"写入决策记录"的变更（**不落盘**）。

    五样缺一就不产出变更——省掉哪一样，这条记录日后都答不上"当初为什么"。
    """
    clean_options = [item.strip() for item in options if item.strip()]
    missing = [
        label
        for label, value in (
            ("title", title.strip()),
            ("background", background.strip()),
            ("options", clean_options),
            ("choice", choice.strip()),
            ("why", why.strip()),
        )
        if not value
    ]
    if missing:
        raise WorkspaceError(
            f"决策记录缺：{'、'.join(missing)}",
            hint="FR-036 要求背景、备选方案、最终选择、理由、时间五样齐全",
        )

    moment = moment or dt.datetime.now()
    stamp = moment.date().isoformat()
    relative = f"{DECISIONS_DIR}/{stamp}-{slug(title)}.md"
    if project.path(relative).exists():
        raise WorkspaceError(
            f"今天已经有一条同名决策了：{relative}",
            hint="换个说法，或者在标题里加个序号",
        )

    body = "\n\n".join(
        [
            f"## 背景\n\n{background.strip()}",
            "## 备选方案\n\n" + "\n".join(f"- {item}" for item in clean_options),
            f"## 最终选择\n\n{choice.strip()}",
            f"## 理由\n\n{why.strip()}",
        ]
    )
    return project.prepare_write(
        relative,
        render_markdown({"title": title.strip(), "date": stamp}, body),
        reason=reason or f"记录决策：{title.strip()}",
    )


def list_decisions(project: Project) -> list[Decision]:
    """全部决策记录，最近的在前。"""
    folder = project.path(DECISIONS_DIR)
    if not folder.is_dir():
        return []
    decisions: list[Decision] = []
    for path in sorted(folder.glob("*.md"), reverse=True):
        text = path.read_text(encoding="utf-8")
        meta, body, has_frontmatter = split_frontmatter(text)
        if not has_frontmatter:
            continue
        sections = split_sections(body)
        decisions.append(
            Decision(
                title=str(meta.get("title") or path.stem),
                date=str(meta.get("date") or ""),
                background=sections.get("背景", ""),
                options=tuple(
                    line.strip()[2:].strip()
                    for line in sections.get("备选方案", "").splitlines()
                    if line.strip().startswith("- ")
                ),
                choice=sections.get("最终选择", ""),
                why=sections.get("理由", ""),
                path=path,
            )
        )
    return decisions


def decisions_mentioning(project: Project, keyword: str) -> list[Decision]:
    """提到某个编号（比如 FR-022 或 T067）的决策——追溯链要用。"""
    return [
        item
        for item in list_decisions(project)
        if keyword in item.path.read_text(encoding="utf-8")
    ]


def split_sections(body: str) -> dict[str, str]:
    """把正文按 ``## 标题`` 切成 ``{标题: 内容}``。"""
    parts: dict[str, str] = {}
    for match in re.finditer(r"^##\s+(.+?)\s*$", body, re.MULTILINE):
        title = match.group(1).strip()
        start = match.end()
        following = re.search(r"^##\s+", body[start:], re.MULTILINE)
        end = start + following.start() if following else len(body)
        parts[title] = body[start:end].strip()
    return parts


def slug(title: str) -> str:
    """标题 → 文件名片段（中文保留，其余符号折成连字符）。"""
    text = re.sub(r"[^\w\u4e00-\u9fff]+", "-", title.strip()).strip("-")
    return text[:40] or "decision"
