"""变更影响分析：改一条需求之前，先看会波及什么（T067 / T068）。

这是 FR-022 的落点。为什么要**在改之前**看：影响面是唯一能提前看到的东西，
等改完才发现"三个任务要重做、一个已完成的要返工"，代价已经付了。

分析全靠已有的追溯关系（任务指回需求、任务之间有依赖），所以复算得出、也说得清依据。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import WorkspaceError
from ..workspace import format as fmt
from ..workspace.decisions import decisions_mentioning
from ..workspace.store import Project

#: 受影响的任务到了几条，就该重新评审而不是直接改
REVIEW_THRESHOLD = 3


@dataclass(frozen=True)
class ChangeImpact:
    """改一条需求会波及什么。"""

    requirement: fmt.Requirement
    #: 直接关联这条需求的任务
    tasks: tuple[fmt.Task, ...]
    #: 依赖上面那些任务的下游任务（连带影响）
    downstream: tuple[fmt.Task, ...]
    #: 受影响的里程碑
    milestones: tuple[str, ...]
    #: 已经完成的、可能要重做的工作
    done_tasks: tuple[fmt.Task, ...]

    @property
    def affected(self) -> tuple[fmt.Task, ...]:
        return (*self.tasks, *self.downstream)

    @property
    def needs_review(self) -> bool:
        """影响面够大就该重新评审；**已完成的工作要重做**这一条单独算。"""
        return len(self.affected) >= REVIEW_THRESHOLD or bool(self.done_tasks)

    def render(self) -> str:
        lines = [f"改 {self.requirement.id} 会波及："]
        if self.tasks:
            lines += [f"  - 直接相关：{task.id} {task.title}" for task in self.tasks]
        else:
            lines.append("  - 直接相关：没有任务关联它")
        if self.downstream:
            lines += [f"  - 连带影响：{task.id} {task.title}" for task in self.downstream]
        if self.milestones:
            lines.append(f"  - 受影响里程碑：{'、'.join(self.milestones)}")
        if self.done_tasks:
            lines += [
                f"  - 要重做的工作：{task.id} 已经完成（证据：{task.evidence or '没写'}）"
                for task in self.done_tasks
            ]
        lines.append("")
        if self.needs_review:
            lines.append(
                f"**建议先重新评审**：受影响 {len(self.affected)} 条任务"
                f"（阈值 {REVIEW_THRESHOLD}），其中 {len(self.done_tasks)} 条已完成。"
            )
        else:
            lines.append(f"影响面不大（{len(self.affected)} 条任务），可以直接改。")
        return "\n".join(lines)


def analyze_change_impact(project: Project, requirement_id: str) -> ChangeImpact:
    """分析改一条需求的影响面。**只读。**"""
    requirements = {item.id: item for item in project.requirements()}
    if requirement_id not in requirements:
        available = "、".join(sorted(requirements)) or "（一条也没有）"
        raise WorkspaceError(
            f"规范里没有 {requirement_id}", hint=f"现有条目：{available}"
        )

    tasks = project.tasks()
    direct = tuple(task for task in tasks if requirement_id in task.requirements)
    downstream = _downstream_closure(tasks, {task.id for task in direct})
    milestones = tuple(
        dict.fromkeys(task.milestone for task in (*direct, *downstream) if task.milestone)
    )
    return ChangeImpact(
        requirement=requirements[requirement_id],
        tasks=direct,
        downstream=downstream,
        milestones=milestones,
        done_tasks=tuple(task for task in direct if task.done),
    )


def _downstream_closure(
    tasks: tuple[fmt.Task, ...] | list[fmt.Task], seed: set[str]
) -> tuple[fmt.Task, ...]:
    """顺依赖往下走到底：受影响的不只是一层。

    FR-022 要求的是"无遗漏"——T005 依赖 T004、T004 依赖被改需求的任务，
    那 T005 一样会受牵连。只算一层会把这种连带影响漏掉。
    """
    affected = set(seed)
    result: list[fmt.Task] = []
    changed = True
    while changed:
        changed = False
        for task in tasks:
            if task.id in affected:
                continue
            if any(dep in affected for dep in task.depends_on):
                affected.add(task.id)
                result.append(task)
                changed = True
    return tuple(sorted(result, key=lambda task: task.id))


@dataclass(frozen=True)
class TaskTrace:
    """一个任务的来龙去脉：来源需求 + 相关决策。"""

    task: fmt.Task
    requirements: tuple[fmt.Requirement, ...]
    decisions: tuple[object, ...]

    def render(self) -> str:
        lines = [f"{self.task.id} {self.task.title}"]
        lines.append("  来源需求：")
        lines += (
            [f"    - {item.id} {item.text}" for item in self.requirements]
            or ["    - （这个任务没写来源，或者写的是「—」）"]
        )
        lines.append("  相关决策：")
        lines += (
            [f"    - {item.render()}" for item in self.decisions]
            or ["    - （还没有提到它的决策记录）"]
        )
        return "\n".join(lines)


def trace_task(project: Project, task_id: str) -> TaskTrace:
    """任务 → 需求 → 决策，一条链查下来（T070）。**只读。**"""
    tasks = {task.id: task for task in project.tasks()}
    if task_id not in tasks:
        available = "、".join(sorted(tasks)) or "（一个也没有）"
        raise WorkspaceError(f"任务清单里没有 {task_id}", hint=f"现有任务：{available}")
    task = tasks[task_id]

    requirements = tuple(
        item for item in project.requirements() if item.id in task.requirements
    )
    decisions = tuple(
        dict.fromkeys(
            [*decisions_mentioning(project, task_id)]
            + [d for rid in task.requirements for d in decisions_mentioning(project, rid)]
        )
    )
    return TaskTrace(task=task, requirements=requirements, decisions=decisions)
