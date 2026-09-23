"""需求条目的操作：分配编号、新增、定点修改（对应 tasks.md 的 T012）。

解析与校验在 ``format.py``（那才是"格式定义"待的地方，而且编号的正则就在那儿）；
这里放**会改文件的操作**，所以它产出 ``Change``、依赖 ``changes``。

三条约定：

1. **编号只增不复用**。删掉编号最大的那条以后，下一个新条目仍然拿新号——
   靠的是 frontmatter 里的水位线（``next_requirement``）。复用编号会让别处
   已有的引用静默指向另一条需求，这类 bug 不报错、最难查。
2. **改动是定点替换**。只重写该改的那一行，其余部分逐字不动。为了让这句话
   站得住，这里用**行级手术**而不是"解析后重新渲染"——重新渲染会把空行、
   缩进这些细节一起重排。
3. **水位线由 add_requirement 维护**。从没经过本工具新增过条目的规范，
   退化规则是"当前最大编号 + 1"。这是有意的：没有新增历史，就没有号会被复用。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import WorkspaceError
from . import changes
from . import format as fmt
from .changes import Change
from .files import set_frontmatter_line, split_frontmatter
from .store import Project


@dataclass(frozen=True)
class RequirementRevision:
    """某条需求的一次变化。

    ``before`` 为 None 表示这条需求当时还不存在；``after`` 为 None 表示它被删掉了。
    """

    time: str
    reason: str
    before: str | None
    after: str | None


def next_requirement_id(spec_text: str) -> str:
    """下一条需求的编号。

    优先信 frontmatter 里的水位线（只增不减），没有水位线时按现有最大编号推。
    两者取大再加一，所以"删掉最大号再新增"不会把旧号发出去。
    """
    meta, _, _ = split_frontmatter(spec_text)
    try:
        watermark = int(meta[fmt.WATERMARK_KEY])
    except (KeyError, TypeError, ValueError):
        watermark = 0

    highest = max(
        (int(item.id[3:]) for item in fmt.parse_requirements(spec_text)), default=0
    )
    return f"FR-{max(watermark, highest) + 1:03d}"


def add_requirement(
    project: Project, text: str, *, reason: str = "新增需求条目"
) -> Change:
    """产出一份"新增一条需求"的变更（**不落盘**）。

    新条目插在**最后一条需求之后**；一条需求都没有时追加到文档末尾。
    分组由位置决定——想放进别的分组，手工挪那一行。
    """
    body = text.strip()
    if not body:
        raise WorkspaceError(
            "需求内容不能为空", hint="写清这条需求要系统做到什么"
        )

    raw = project.spec_text()
    requirement_id = next_requirement_id(raw)
    lines = raw.split("\n")

    items = fmt.parse_requirements(raw)
    if items:
        index = items[-1].line  # 1 起的行号正好是"插在它后面"的 0 起下标
    elif lines and lines[-1] == "":
        index = len(lines) - 1
    else:
        index = len(lines)
    lines.insert(index, f"- **{requirement_id}** {body}")

    updated = _with_watermark("\n".join(lines), int(requirement_id[3:]))
    return project.prepare_write(fmt.SPEC_FILE, updated, reason=reason)


def update_requirement(
    project: Project, requirement_id: str, text: str, *, reason: str = "修改需求条目"
) -> Change:
    """产出一份"改写某一条需求"的变更（**不落盘**）。

    定点替换：只重写那一行，其余逐字不动。
    """
    body = text.strip()
    if not body:
        raise WorkspaceError(
            "需求内容不能为空", hint="要删条目就手工删那一行；这里不接受空内容"
        )

    raw = project.spec_text()
    items = {item.id: item for item in fmt.parse_requirements(raw)}
    if requirement_id not in items:
        available = "、".join(sorted(items)) or "（一条也没有）"
        raise WorkspaceError(
            f"规范里没有 {requirement_id} 这条需求",
            hint=f"现有条目：{available}",
        )

    lines = raw.split("\n")
    lines[items[requirement_id].line - 1] = f"- **{requirement_id}** {body}"
    return project.prepare_write(fmt.SPEC_FILE, "\n".join(lines), reason=reason)


def requirement_history(
    project: Project, requirement_id: str
) -> list[RequirementRevision]:
    """某条需求的变更历史（从旧到新）。

    数据全部来自 T008 留下的 ``history/``：每条变更记录里都存着改动前的
    ``spec.md``。把它们按时间排开、逐段比对目标条目的文本，就得到
    "何时变、为何变"——这是那套快照的第二次回报。

    一处诚实的局限：如果 spec.md 被**手工**改过（没经过本工具），
    最后一段会显示成"由上一次受管的变更产生"。
    """
    revisions: list[RequirementRevision] = []
    previous: str | None = None
    for time, reason, text in _spec_timeline(project):
        current = _text_of(text, requirement_id)
        if current is None and previous is None:
            continue
        if current == previous:
            continue
        revisions.append(
            RequirementRevision(time=time, reason=reason, before=previous, after=current)
        )
        previous = current
    return revisions


def _text_of(spec_text: str, requirement_id: str) -> str | None:
    for item in fmt.parse_requirements(spec_text):
        if item.id == requirement_id:
            return item.text
    return None


def _spec_timeline(project: Project) -> list[tuple[str, str, str]]:
    """``(时间, 原因, 当时的规范全文)``，从旧到新。

    第一条是"最早那次变更之前"，其余每条都标着**产生它的那次变更**。
    """
    snapshots: list[tuple[str, str, str]] = []
    for entry in reversed(changes.history_entries(project)):  # 旧 → 新
        path = entry / changes.BEFORE_DIR / fmt.SPEC_FILE
        if not path.is_file():
            continue
        meta = changes.read_change_meta(entry)
        snapshots.append(
            (entry.name, str(meta.get("reason") or ""), path.read_text(encoding="utf-8"))
        )

    if not snapshots:
        return [("（无变更记录）", "", project.spec_text())]

    timeline: list[tuple[str, str, str]] = [("（起始）", "", snapshots[0][2])]
    for index, (stamp, reason, _before) in enumerate(snapshots):
        after = (
            snapshots[index + 1][2]
            if index + 1 < len(snapshots)
            else project.spec_text()
        )
        timeline.append((stamp, reason, after))
    return timeline


def _with_watermark(text: str, number: int) -> str:
    """把水位线写进 frontmatter（行级手术，见 files.set_frontmatter_line）。"""
    return set_frontmatter_line(text, fmt.WATERMARK_KEY, str(number))
