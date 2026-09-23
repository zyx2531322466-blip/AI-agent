"""任务的读写：覆盖缺口、最小切片、要素校验、状态推进（T018 ~ T024）。

沿用前几处的分工：解析与校验在 ``format.py``（那才是"格式定义"），
这里放**会改文件的操作**，所以它产出 ``Change``。

三条约定：

1. **创建时严格，读取时宽容**。新建任务必须带齐 FR-009 的三要素（完成标准、
   优先级、依赖），缺一个就写不进去；但读一份手写的旧清单时，缺字段只是"没写"，
   不该让整个项目打不开。
2. **改动是定点替换**。改哪个字段只重写那个字段，行里其它内容逐字不动——
   和 T012 改需求条目同一个道理。
3. **没有证据不算完成**（FR-014）。"做完了"得能指到东西，光勾个框不算。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import WorkspaceError
from . import format as fmt
from .changes import Change
from .store import Project


def tasks_by_milestone(project: Project) -> dict[str, list[fmt.Task]]:
    """按里程碑分组（FR-011）。里程碑就是任务清单里的二级标题。"""
    grouped: dict[str, list[fmt.Task]] = {}
    for task in project.tasks():
        grouped.setdefault(task.milestone or "（未归入里程碑）", []).append(task)
    return grouped


@dataclass(frozen=True)
class CoverageReport:
    """覆盖缺口的两个方向（FR-010）。"""

    uncovered_requirements: tuple[fmt.Requirement, ...]
    sourceless_tasks: tuple[fmt.Task, ...]

    @property
    def ok(self) -> bool:
        return not self.uncovered_requirements and not self.sourceless_tasks

    def render(self) -> str:
        lines: list[str] = []
        if self.uncovered_requirements:
            lines.append("没有任何任务覆盖的需求：")
            lines += [
                f"  - {item.id} {item.text}" for item in self.uncovered_requirements
            ]
        if self.sourceless_tasks:
            lines.append("找不到来源的任务：")
            lines += [f"  - {item.id} {item.title}" for item in self.sourceless_tasks]
        return "\n".join(lines) if lines else "没有覆盖缺口。"


def coverage_gaps(project: Project) -> CoverageReport:
    """同时报出两个方向的缺口（FR-010）。

    ``sourceless_tasks`` 只收**漏写来源**的任务：写了 ``（— / —）`` 的任务
    算"明确没有来源"（基础设施类任务确实不属于某一条需求），不算缺口。
    """
    requirements = project.requirements()
    tasks = project.tasks()
    covered = {rid for task in tasks for rid in task.requirements}

    return CoverageReport(
        uncovered_requirements=tuple(r for r in requirements if r.id not in covered),
        sourceless_tasks=tuple(t for t in tasks if not t.has_source),
    )


def ready_tasks(project: Project) -> list[fmt.Task]:
    """现在就能动手的任务，按优先级排（FR-013 的最小切片）。

    条件：未完成、且依赖都已完成。排序键是优先级（``P1`` → 1）再按编号，
    所以"优先级最高的那条链路"总排在最前面。
    """
    tasks = project.tasks()
    done = {task.id for task in tasks if task.done}
    ready = [
        task
        for task in tasks
        if not task.done and all(dep in done for dep in task.depends_on)
    ]
    return sorted(ready, key=lambda task: (_priority_rank(task.priority), task.id))


def _priority_rank(priority: str) -> int:
    """``P1`` → 1；没写优先级的排到最后。"""
    text = priority.strip().upper()
    if text.startswith("P") and text[1:].isdigit():
        return int(text[1:])
    return 99


def add_task(
    project: Project,
    *,
    title: str,
    standard: str,
    priority: str,
    depends_on: tuple[str, ...] | list[str] = (),
    requirements: tuple[str, ...] | list[str] = (),
    milestone: str | None = None,
    parallel: bool = False,
    reason: str = "新增任务",
) -> Change:
    """产出一份"新增任务"的变更（**不落盘**）。

    **三要素缺一个就不产出变更**（FR-009）——不是"提醒你补"，而是压根写不进去。
    依赖和关联需求都必须真实存在，否则就是悬空引用（FR-012）。
    """
    if not title.strip():
        raise WorkspaceError("任务要有内容", hint="写清这个任务要做什么")
    if not standard.strip():
        raise WorkspaceError(
            "任务缺完成标准（FR-009）", hint="写清'怎么算做完了'，要能独立验收"
        )
    if not priority.strip():
        raise WorkspaceError("任务缺优先级（FR-009）", hint="例如 P1 / P2 / P3")

    path = project.path(fmt.TASKS_FILE)
    raw = project.read_text(fmt.TASKS_FILE) if path.is_file() else ""
    known_tasks = {task.id for task in fmt.parse_tasks(raw)}
    known_requirements = {item.id for item in project.requirements()}

    for dependency in depends_on:
        if dependency not in known_tasks:
            raise WorkspaceError(
                f"依赖的 {dependency} 不存在",
                hint="依赖只能指向已存在的任务（FR-012：不出现悬空依赖）",
            )
    for requirement_id in requirements:
        if requirement_id not in known_requirements:
            raise WorkspaceError(
                f"关联的 {requirement_id} 不存在",
                hint="任务要么关联一条真实需求，要么明确写成（— / —）",
            )

    task_id = next_task_id(raw)
    reference = " / ".join(["—", "、".join(requirements) or "—"])
    line = (
        f"- [ ]{' [P]' if parallel else ''} **{task_id}**（{reference}）{title.strip()}。"
        f"**完成标准**：{standard.strip()}。"
        f"**优先级**：{priority.strip()}。"
        f"**依赖**：{'、'.join(depends_on) or '无'}。"
    )

    lines = raw.split("\n") if raw else []
    lines.insert(_insert_position(lines, milestone), line)
    return project.prepare_write(fmt.TASKS_FILE, "\n".join(lines), reason=reason)


def next_task_id(tasks_text: str) -> str:
    """下一个任务编号：按现有最大号加一。

    任务编号**没有**水位线，理由：任务号只在清单内部排序用，关系是"任务指向需求"
    单向，不会有人从别处引用一个已删除的任务号。哪天要引用任务号了再补也不迟。
    """
    highest = max((int(task.id[1:]) for task in fmt.parse_tasks(tasks_text)), default=0)
    return f"T{highest + 1:03d}"


def update_task(
    project: Project,
    task_id: str,
    *,
    standard: str | None = None,
    priority: str | None = None,
    depends_on: tuple[str, ...] | list[str] | None = None,
    evidence: str | None = None,
    reason: str = "调整任务",
) -> Change:
    """产出一份"改任务要素"的变更（**不落盘**）。

    定点替换：只重写被改的那个字段，行里其它内容逐字不动。改了依赖会当场查悬空。
    """
    raw = project.read_text(fmt.TASKS_FILE)
    tasks = {task.id: task for task in fmt.parse_tasks(raw)}
    if task_id not in tasks:
        available = "、".join(sorted(tasks)) or "（一个也没有）"
        raise WorkspaceError(f"任务清单里没有 {task_id}", hint=f"现有任务：{available}")

    if depends_on is not None:
        for dependency in depends_on:
            if dependency not in tasks:
                raise WorkspaceError(
                    f"依赖的 {dependency} 不存在",
                    hint="依赖只能指向已存在的任务（FR-012）",
                )
        if task_id in depends_on:
            raise WorkspaceError(f"{task_id} 不能依赖自己", hint="去掉这条自依赖")

    lines = raw.split("\n")
    index = tasks[task_id].line - 1
    line = lines[index]
    if standard is not None:
        line = _set_field(line, "完成标准", standard)
    if priority is not None:
        line = _set_field(line, "优先级", priority)
    if depends_on is not None:
        line = _set_field(line, "依赖", "、".join(depends_on) or "无")
    if evidence is not None:
        line = _set_field(line, "证据", evidence or "无")
    lines[index] = line
    return project.prepare_write(fmt.TASKS_FILE, "\n".join(lines), reason=reason)


def complete_task(
    project: Project, task_id: str, *, evidence: str = "", reason: str = ""
) -> Change:
    """产出一份"把任务标记完成"的变更（**不落盘**）。

    **没有证据就不产出变更**（FR-014）：只勾一个框不算完成。证据是"别人能去看的
    东西"——代码变更、文档、可运行的结果、评审结论。
    """
    raw = project.read_text(fmt.TASKS_FILE)
    tasks = {task.id: task for task in fmt.parse_tasks(raw)}
    if task_id not in tasks:
        raise WorkspaceError(f"任务清单里没有 {task_id}", hint="先确认任务编号")

    task = tasks[task_id]
    final_evidence = evidence.strip() or task.evidence.strip()
    if not final_evidence or final_evidence == "无":
        raise WorkspaceError(
            f"{task_id} 还没有完成证据，不能标记完成（FR-014）",
            hint="给出证据（代码变更 / 文档 / 可运行结果 / 评审结论），或者先别勾",
        )

    lines = raw.split("\n")
    index = task.line - 1
    line = lines[index]
    if evidence.strip():
        line = _set_field(line, "证据", evidence.strip())
    if line.startswith("- [ ]"):
        line = "- [x]" + line[len("- [ ]") :]
    lines[index] = line
    return project.prepare_write(
        fmt.TASKS_FILE, "\n".join(lines), reason=reason or f"完成 {task_id}"
    )


def _insert_position(lines: list[str], milestone: str | None) -> int:
    """插到哪一行：指定里程碑就插在该组末尾，否则插在文件末尾。"""
    if not lines:
        return 0
    tasks = fmt.parse_tasks("\n".join(lines))
    if milestone:
        in_group = [task for task in tasks if task.milestone == milestone]
        if not in_group:
            available = "、".join(
                dict.fromkeys(task.milestone for task in tasks if task.milestone)
            )
            raise WorkspaceError(
                f"没有名为 {milestone} 的里程碑",
                hint=f"现有里程碑：{available or '（没有）'}",
            )
        return in_group[-1].line  # 1 起行号正好是"插在它后面"的 0 起下标

    index = len(lines)
    if lines and lines[-1] == "":
        index -= 1
    return index


def _set_field(line: str, label: str, value: str) -> str:
    """在一行里设置 ``**label**：值``；没有这个字段就追加到行尾。

    只动这一段，行里其它内容（动作、别的字段）逐字不动。
    结尾统一补一个句号——不然替换之后会和下一个字段粘在一起（``P1**依赖**``）。
    """
    rendered = value.strip().rstrip("。") + "。"
    marker = f"**{label}**："
    start = line.find(marker)
    if start == -1:
        return line.rstrip() + f"**{label}**：{rendered}"

    value_start = start + len(marker)
    following = next(
        (
            match.start()
            for match in fmt.TASK_FIELD_RE.finditer(line[value_start:])
        ),
        None,
    )
    end = value_start + following if following is not None else len(line)
    return line[:value_start] + rendered + line[end:]
