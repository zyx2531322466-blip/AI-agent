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
from dataclasses import dataclass

from ..errors import WorkspaceError
from . import format as fmt
from .changes import Change
from .files import set_frontmatter_line, split_frontmatter
from .store import Project

#: 评审稿落在 reports/ 下（六个数据目录之一）
REVIEW_DIR = "reports"

#: 回填后原话里若还留着这些字眼，说明那句该顺一顺了（只提示，不代改）
STALE_WORDS = ("还没定", "待定", "不确定", "不知道", "TBD", "待确认")


@dataclass(frozen=True)
class ClarificationAnswer:
    """一次"回答待澄清问题"的结果——给人看的摘要（不含变更本身）。"""

    question: str
    source: str
    line: int
    #: 回填之后那一行长什么样
    after: str
    #: 如果这条需求此前被确认过、这次因内容变化而作废，记下编号
    unconfirmed: str = ""
    #: 回填后原话里还留着的"没定"类字眼
    stale: tuple[str, ...] = ()


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


def clarifications_of(project: Project) -> list[fmt.Clarification]:
    """当前还没答案的问题（按出现顺序，序号从 1 起）。"""
    return fmt.parse_clarifications(project.spec_text())


def pick_clarification(
    items: list[fmt.Clarification], target: str | None
) -> fmt.Clarification:
    """按序号或来源定位一处待澄清（不指定时只允许只剩一条的情形）。

    为什么允许两种定位方式：人手里拿着的是"问题本身"，而脚本里拿着的是编号。
    两条路都留着，但**多解就报错、绝不猜**——回填错地方等于给规范写进一条错结论。
    """
    if not items:
        raise WorkspaceError(
            "规范里没有待澄清的问题",
            hint="用 pm-agent questions 看一眼；没有问题就不用回填",
        )

    def listing() -> str:
        return "\n".join(
            f"  {index}. [{item.source}] {item.text}"
            for index, item in enumerate(items, start=1)
        )

    if target is None:
        if len(items) == 1:
            return items[0]
        raise WorkspaceError(
            f"现在有 {len(items)} 处待澄清，得说清回答的是哪一处",
            hint="用 --for 指定（序号或来源都行）：\n" + listing(),
        )

    text = target.strip()
    if text.isdigit():
        index = int(text)
        if not 1 <= index <= len(items):
            raise WorkspaceError(
                f"没有第 {index} 处待澄清（现在共 {len(items)} 处）",
                hint="序号从 1 起，用 pm-agent questions 看一遍",
            )
        return items[index - 1]

    matched = [item for item in items if item.source == text]
    if not matched:
        matched = [item for item in items if text in item.source]
    if not matched:
        raise WorkspaceError(
            f"没有来自「{text}」的待澄清问题",
            hint="现有的来源：\n" + listing(),
        )
    if len(matched) > 1:
        raise WorkspaceError(
            f"「{text}」下有 {len(matched)} 处待澄清，得说清是哪一处",
            hint="改用序号：\n"
            + "\n".join(
                f"  {items.index(item) + 1}. [{item.source}] {item.text}"
                for item in matched
            ),
        )
    return matched[0]


def resolve_clarification(
    project: Project,
    *,
    answer: str,
    target: str | None = None,
    reason: str | None = None,
) -> tuple[Change, ClarificationAnswer]:
    """产出一份"把结论回填进规范"的变更（**不落盘**），附一份给人看的摘要。

    回填的写法分两种位置（都在同一行内完成，**行级手术**，其余逐字不动）：

    - 问题在**需求条目里**（``- **FR-003** …[待澄清] 问题？``）：
      把 ``[待澄清] 问题？`` 换成 ``**结论**：<答案>``；
    - 问题在**"待澄清问题"那一节**（``- [待澄清] 问题？``）：
      去掉标记、保留问题，追加 ``**结论**：<答案>``——问过什么必须留痕。

    还有一条连带处理：如果这条需求此前被**确认**过，它的内容变了，确认随之失效——
    同一次变更里把它从 ``confirmed`` 里摘掉，免得"内容已改、状态还写着确认过"。
    """
    body = answer.strip()
    if not body:
        raise WorkspaceError("结论不能是空的", hint="写清这处待澄清定成了什么")

    raw = project.spec_text()
    items = fmt.parse_clarifications(raw)
    item = pick_clarification(items, target)

    lines = raw.split("\n")
    index = item.line - 1
    if index >= len(lines):
        raise WorkspaceError(
            f"第 {item.line} 行已经不在规范里了", hint="规范被改过；重跑一次 questions 看看"
        )
    original = lines[index]
    marker_at = original.find(fmt.CLARIFICATION_MARKER)
    if marker_at < 0:
        raise WorkspaceError(
            f"第 {item.line} 行里找不到 {fmt.CLARIFICATION_MARKER} 标记",
            hint="规范被改过；重跑一次 questions 看看",
        )

    # 去掉标记本身，把它后面紧跟着的冒号也一并去掉；**问题原样留着**——
    # "问过什么"和"后来定成什么"要同时看得到（FR-054）。
    head = original[:marker_at].rstrip()
    asked = original[marker_at + len(fmt.CLARIFICATION_MARKER) :]
    asked = asked.strip().lstrip("：:").strip()
    kept = f"{head} {asked}".strip()
    tail = f"{kept} **结论**：{body}".strip()
    lines[index] = tail
    updated = "\n".join(lines)

    unconfirmed = ""
    requirement_id = (
        item.source
        if fmt.REQUIREMENT_LINE_RE.match(tail) and item.source.startswith("FR-")
        else ""
    )
    if requirement_id:
        confirmed = parse_confirmed(updated)
        if requirement_id in confirmed:
            rest = [item for item in confirmed if item != requirement_id]
            rendered = "[" + ", ".join(rest) + "]"
            updated = set_frontmatter_line(updated, fmt.CONFIRMED_KEY, rendered)
            unconfirmed = requirement_id

    stale = tuple(word for word in STALE_WORDS if word in tail)
    change = project.prepare_write(
        fmt.SPEC_FILE,
        updated,
        reason=reason or f"回填待澄清（{item.source}）",
    )
    return change, ClarificationAnswer(
        question=item.text,
        source=item.source,
        line=item.line,
        after=tail,
        unconfirmed=unconfirmed,
        stale=stale,
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
