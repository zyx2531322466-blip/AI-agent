"""学习目标的复盘对照（T035 / FR-051）。

"这个项目我想学到什么"记在 ``project.yaml`` 的 ``learning_goals`` 里，
这里把它和**已经产出的东西**对上去。

一句要紧的话：**匹配是推测，不是事实**。目标是自由文本，任务标题里没有权威的
对应关系，所以每条匹配都标出来由（重合了几处）并写明"推测"——让人自己判断，
而不是替他把结论下了（FR-024）。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..workspace import format as fmt
from ..workspace.store import Project

#: 匹配到几处重合才值得列出来
MIN_OVERLAP = 2


@dataclass(frozen=True)
class GoalProgress:
    """某一个学习目标：产出的整体进展 + 疑似相关的已完成任务。"""

    goal: str
    #: 已经走通的阶段与依据（例如 "规范" / "51 条需求"）
    stages: tuple[tuple[str, str], ...]
    #: （任务, 重合数）——**推测**
    related: tuple[tuple[fmt.Task, int], ...]


@dataclass(frozen=True)
class GoalReview:
    """整个项目的学习目标复盘。"""

    learning_goals: tuple[str, ...]
    items: tuple[GoalProgress, ...]

    def render(self) -> str:
        if not self.learning_goals:
            return "project.yaml 里还没有写 learning_goals——补上它，复盘才有对象。"

        lines: list[str] = ["这个项目想学到什么（FR-051）", ""]
        for item in self.items:
            lines.append(f"· {item.goal}")
            if item.stages:
                joined = "；".join(f"{name} {detail}" for name, detail in item.stages)
                lines.append(f"    已走通：{joined}")
            else:
                lines.append("    已走通：还没有可查的产出")
            if item.related:
                lines.append("    可能相关的已完成任务（推测，自己判断）：")
                lines += [
                    f"      - {task.id} {task.title}（标题重合 {score} 处）"
                    for task, score in item.related
                ]
            else:
                lines.append("    可能相关的已完成任务：没找到明显重合的（不代表没有）")
            lines.append("")
        return "\n".join(lines).rstrip()


def goal_review(project: Project) -> GoalReview:
    """把学习目标和已经产出的东西对一遍。**只读。**"""
    goals = tuple(project.meta.learning_goals)
    done_tasks = [task for task in project.tasks() if task.done]

    items: list[GoalProgress] = []
    for goal in goals:
        scored = sorted(
            (
                (task, fmt.bigram_overlap(goal + (task.conclusion or ""), task.title))
                for task in done_tasks
            ),
            key=lambda pair: (-pair[1], pair[0].id),
        )
        items.append(
            GoalProgress(
                goal=goal,
                stages=_stages_done(project),
                related=tuple(
                    (task, score) for task, score in scored if score >= MIN_OVERLAP
                )[:5],
            )
        )
    return GoalReview(learning_goals=goals, items=tuple(items))


def _stages_done(project: Project) -> tuple[tuple[str, str], ...]:
    """已经走通的阶段，以及**依据**（数是查出来的，不是估的）。"""
    progress: list[tuple[str, str]] = []
    requirements = project.requirements()
    if requirements:
        progress.append(("规范", f"{len(requirements)} 条需求"))
    tasks = project.tasks()
    if tasks:
        done = sum(1 for task in tasks if task.done)
        progress.append(("任务", f"{len(tasks)} 个任务，完成 {done} 个"))
    sessions = [path for path in project.path("sessions").glob("*.md")] if project.path("sessions").is_dir() else []
    if sessions:
        progress.append(("跟踪", f"{len(sessions)} 份交接记录"))
    return tuple(progress)
