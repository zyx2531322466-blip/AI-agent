"""会话的开始：先重建状态，再接受新指令（T027 / T029）。

一条硬规矩写在 FR-017 里：**会话开始时先重建状态摘要，再执行新指令**。
顺序不能反——不然后半段就是在猜"上次到哪了"。

:func:`session_brief` 是会话的第一件事，之后的各个阶段才有意义。

冲突校验（FR-018）也在这里汇总：交接记录说的和项目实际对不上时，
**先停下来让人裁决**，而不是继续往下做。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..workspace import format as fmt
from ..workspace.handoff import Handoff, find_conflicts, read_latest_handoff
from ..workspace.store import Project
from ..workspace.tasks import ready_tasks

_ACTIVE_STATUSES = ("进行中", "阻塞")


@dataclass(frozen=True)
class SessionBrief:
    """会话开始时该知道的一切。"""

    project: str
    last_handoff: Handoff | None
    #: 必须裁决的问题（记录指向了不存在的东西）
    conflicts: tuple[fmt.Problem, ...]
    #: 提示性问题（记录可能过期之类）
    warnings: tuple[fmt.Problem, ...]
    counts: dict[str, int]
    active: tuple[fmt.Task, ...]
    ready: tuple[fmt.Task, ...]
    open_questions: tuple[fmt.Clarification, ...]

    @property
    def ok(self) -> bool:
        """没有必须裁决的冲突。"""
        return not self.conflicts

    def render(self) -> str:
        lines: list[str] = [f"项目：{self.project}", ""]

        if self.last_handoff is None:
            lines += ["上次到哪：还没有交接记录（这可能是第一次会话）", ""]
        else:
            handoff = self.last_handoff
            lines += [
                f"上次到哪（sessions/{handoff.session}.md）",
                f"  上轮做了什么：{_oneline(handoff.did)}",
                f"  当前状态：{_oneline(handoff.state)}",
                f"  下一步建议：{_oneline(handoff.next_steps)}",
                f"  未决问题：{_oneline(handoff.open_questions)}",
                "",
            ]

        lines.append("现在到哪")
        lines.append(
            "  任务：完成 {完成} / 进行中 {进行中} / 阻塞 {阻塞} / 未开始 {未开始}".format(
                **self.counts
            )
        )
        if self.active:
            lines.append("  进行中或阻塞：")
            for task in self.active:
                lines.append(f"    - {task.id}（{task.status}）{task.title}")
                if task.conclusion and task.conclusion != "无":
                    # 中间结论必须出现在摘要里——不然新会话还得重讲一遍背景（FR-020）
                    lines.append(f"        上次留下的结论：{task.conclusion}")
        if self.ready:
            lines.append("  现在能动手（按优先级）：")
            lines += [
                f"    - {task.id}（{task.priority or '无优先级'}）{task.title}"
                for task in self.ready[:5]
            ]
        else:
            lines.append("  现在能动手：没有（先看 pm-agent tasks --coverage）")
        if self.open_questions:
            lines.append(
                f"  待澄清：{len(self.open_questions)} 条（pm-agent questions 看全部）"
            )

        if self.conflicts:
            lines += ["", "冲突：**先裁决再继续**"]
            lines += [f"  - {problem.render()}" for problem in self.conflicts]
        if self.warnings:
            lines += ["", "提示"]
            lines += [f"  - {problem.render()}" for problem in self.warnings]
        return "\n".join(lines)


def session_brief(project: Project) -> SessionBrief:
    """重建"现在到哪了"。**只读**，不改任何东西。"""
    last = read_latest_handoff(project)
    problems = find_conflicts(project, last) if last else []
    tasks = project.tasks()

    return SessionBrief(
        project=project.meta.name,
        last_handoff=last,
        conflicts=tuple(fmt.errors(problems)),
        warnings=tuple(fmt.warnings(problems)),
        counts={
            status: sum(1 for task in tasks if task.status == status)
            for status in fmt.TASK_STATUSES
        },
        active=tuple(task for task in tasks if task.status in _ACTIVE_STATUSES),
        ready=tuple(ready_tasks(project)),
        open_questions=tuple(fmt.parse_clarifications(project.spec_text())),
    )


def _oneline(text: str) -> str:
    """把多行文本压成一行，方便塞进摘要。"""
    return "；".join(part.strip() for part in text.splitlines() if part.strip())
