"""规范的评审：确认状态与评审稿导出（T013 / T015 / T016）。

- **确认状态**（FR-006）：哪些条目被逐条确认过。记在 ``spec.md`` 的 frontmatter
  （``confirmed`` 列表）里，和 status / version / next_requirement 一起——
  同属"程序维护的元数据、正文归模型产出"的分工。
- **评审稿导出**（FR-007）：整理成一份**不依赖本工具**就能读的文档，并把
  "哪些还没确认、哪些还在等答案"显眼地标出来。

沿用前几处的规矩：这一层只产出数据（文本或 ``Change``），不打印、不询问，
显示与确认归 CLI。
"""

from __future__ import annotations

import datetime as dt

from ..errors import WorkspaceError
from . import format as fmt
from .changes import Change
from .files import set_frontmatter_line, split_frontmatter
from .store import Project

#: 评审稿落在 reports/ 下（六个数据目录之一）
REVIEW_DIR = "reports"


def parse_confirmed(spec_text: str) -> list[str]:
    """frontmatter 里记录的已确认条目编号（去重、按编号排序）。"""
    meta, _, _ = split_frontmatter(spec_text)
    raw = meta.get(fmt.CONFIRMED_KEY)
    if not isinstance(raw, list):
        return []
    return sorted({str(item).strip() for item in raw if str(item).strip()})


def unconfirmed_requirements(project: Project) -> list[fmt.Requirement]:
    """还没确认过的条目。"""
    confirmed = set(parse_confirmed(project.spec_text()))
    return [item for item in project.requirements() if item.id not in confirmed]


def confirm_requirement(
    project: Project, requirement_id: str, *, reason: str | None = None
) -> Change:
    """产出一份"确认某条需求"的变更（**不落盘**）。

    已经确认过的条目会返回一份**没有变化**的变更——上层照着 T008 的规矩处理
    即可（不写盘、不留历史），不必在这里特判。

    想提修改意见就用 T012 的 ``update_requirement`` 改文本：意见是"要改"，
    确认是"看过了、可以照它做"，两件事分开。
    """
    raw = project.spec_text()
    known = {item.id for item in fmt.parse_requirements(raw)}
    if requirement_id not in known:
        available = "、".join(sorted(known)) or "（一条也没有）"
        raise WorkspaceError(
            f"规范里没有 {requirement_id} 这条需求", hint=f"现有条目：{available}"
        )

    confirmed = parse_confirmed(raw)
    if requirement_id in confirmed:
        return project.prepare_write(
            fmt.SPEC_FILE, raw, reason=reason or f"{requirement_id} 已经确认过"
        )

    rendered = "[" + ", ".join(sorted({*confirmed, requirement_id})) + "]"
    return project.prepare_write(
        fmt.SPEC_FILE,
        set_frontmatter_line(raw, fmt.CONFIRMED_KEY, rendered),
        reason=reason or f"确认 {requirement_id}",
    )


def build_review_document(project: Project, *, exported_on: str | None = None) -> str:
    """生成评审稿（纯 Markdown：能直接读、能打印、能发给别人）。"""
    spec_text = project.spec_text()
    items = fmt.parse_requirements(spec_text)
    confirmed = set(parse_confirmed(spec_text))
    clarifications = fmt.parse_clarifications(spec_text)
    pending = [item for item in items if item.id not in confirmed]
    _, body, _ = split_frontmatter(spec_text)

    lines = [
        f"# {project.meta.name} —— 规范评审稿",
        "",
        f"- 导出日期：{exported_on or dt.date.today().isoformat()}",
        f"- 需求条目：共 {len(items)} 条，已确认 {len(items) - len(pending)} 条，"
        f"**待确认 {len(pending)} 条**",
        f"- 待澄清问题：{len(clarifications)} 条",
        "",
        "> 这份文档不依赖任何工具，直接读就行；意见可以直接写在文件里发回来。",
        "",
        "## 一、待确认的条目",
        "",
    ]
    lines += (
        [f"- [ ] **{item.id}**（{item.section}）{item.text}" for item in pending]
        or ["（全部条目都已确认）"]
    )
    lines += ["", "## 二、还在等答案的问题", ""]
    lines += (
        [f"- [ ] **{item.source}** {item.text}" for item in clarifications]
        or ["（暂无）"]
    )
    lines += ["", "## 三、规范全文", "", body.strip(), ""]
    return "\n".join(lines)


def export_review(
    project: Project, *, moment: dt.datetime | None = None, reason: str = "导出评审稿"
) -> Change:
    """产出一份"写入评审稿"的变更（**不落盘**）。

    落到 ``reports/评审稿-<日期>.md``；写入路径由 T008 的 ``Change`` 带着走，
    调用方 ``apply`` 之后从 ``ApplyResult.written`` 就能拿到实际路径。
    """
    stamp = (moment or dt.datetime.now()).strftime("%Y-%m-%d")
    return project.prepare_write(
        f"{REVIEW_DIR}/评审稿-{stamp}.md",
        build_review_document(project, exported_on=stamp),
        reason=reason,
    )
