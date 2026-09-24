"""风险识别：五类能从记录里算出来的风险（T042 / T043 / T044）。

**事实与推测分开**（FR-024）：

- 直接命中规则的算**事实**——截止日过了、太久没动、依赖被阻塞、
  需求净增太多、有证据却又不是完成态；
- 顺着依赖链**推出来**的算**推测**——"T005 阻塞，所以依赖它的 T008 可能也会被拖住"。

规则式、可复算：同样的项目状态永远得到同一份清单。所以"为什么报这条"永远答得上来——
每条都带 ``basis``（依据）。

处置过的预警记在 ``project.yaml`` 的 ``acknowledged_risks`` 里，不再重复提醒（FR-023）。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from ..errors import WorkspaceError
from ..workspace import changes
from ..workspace import format as fmt
from ..workspace.changes import Change
from ..workspace.store import Project

#: 超过多少天没动算"长期无进展"
STALE_DAYS = 7
#: 需求条目净增多少条算"范围蔓延"
SCOPE_CREEP_THRESHOLD = 5


@dataclass(frozen=True)
class Risk:
    """一条风险。``key`` 用来记住"这条我看过了"。"""

    kind: str
    subject: str
    text: str
    basis: str
    #: "事实" 或 "推测"
    inference: str

    @property
    def key(self) -> str:
        """稳定标识：同类同对象只算一条，处置一次就一直有效。"""
        return f"{self.kind}:{self.subject}"

    def render(self) -> str:
        return f"[{self.inference}] {self.text}（{self.basis}）"


def detect_risks(
    project: Project,
    *,
    now: dt.datetime | None = None,
    include_acknowledged: bool = False,
) -> list[Risk]:
    """列出风险。默认**跳过已处置的**——不然每次看都刷一遍同样的提醒（FR-023）。"""
    moment = now or dt.datetime.now()
    tasks = project.tasks()
    by_id = {task.id: task for task in tasks}
    risks: list[Risk] = []

    for task in tasks:
        if task.done:
            continue

        due = _parse_day(task.due)
        if due is not None and due < moment.date():
            risks.append(
                Risk(
                    kind="超期",
                    subject=task.id,
                    text=f"{task.id} 的截止日是 {task.due}，今天已经 {moment.date().isoformat()}，仍未完成",
                    basis=f"tasks.md 第 {task.line} 行的 **截止**",
                    inference="事实",
                )
            )

        updated = _parse_moment(task.updated)
        if updated is not None:
            idle = (moment - updated).days
            if idle >= STALE_DAYS:
                risks.append(
                    Risk(
                        kind="长期无进展",
                        subject=task.id,
                        text=f"{task.id} 从 {task.updated} 起 {idle} 天没有状态变化",
                        basis=f"tasks.md 第 {task.line} 行的 **更新**",
                        inference="事实",
                    )
                )

        blocked = sorted(
            dep for dep in task.depends_on if by_id.get(dep) and by_id[dep].status == "阻塞"
        )
        if blocked:
            risks.append(
                Risk(
                    kind="依赖被阻塞",
                    subject=task.id,
                    text=f"{task.id} 依赖的 {'、'.join(blocked)} 处于阻塞，它做不下去",
                    basis=f"tasks.md 第 {task.line} 行的 **依赖** 指向的任务状态",
                    inference="事实",
                )
            )

        if task.evidence.strip() and task.evidence.strip() != "无":
            risks.append(
                Risk(
                    kind="返工或验收未通过",
                    subject=task.id,
                    text=f"{task.id} 有完成证据，但当前状态是「{task.status}」——像是验收没过或返工了",
                    basis=f"tasks.md 第 {task.line} 行的 **证据** 与 **状态**",
                    inference="事实",
                )
            )

    growth = _requirement_growth(project)
    if growth >= SCOPE_CREEP_THRESHOLD:
        risks.append(
            Risk(
                kind="范围蔓延",
                subject="规范",
                text=f"规范比最早的记录多了 {growth} 条需求，范围在长",
                basis="history/ 里最早的 spec.md 快照与当前对比",
                inference="事实",
            )
        )

    risks.extend(_indirect_risks(tasks, by_id))

    if include_acknowledged:
        return risks
    acknowledged = set(project.meta.acknowledged_risks)
    return [risk for risk in risks if risk.key not in acknowledged]


def acknowledge_risk(project: Project, key: str, *, reason: str = "") -> Change:
    """记下"这条预警我处置过了"，之后同类不再重复提醒（FR-023）。"""
    known = {risk.key for risk in detect_risks(project, include_acknowledged=True)}
    if key not in known:
        available = "、".join(sorted(known)) or "（当前没有风险）"
        raise WorkspaceError(
            f"没有这条预警：{key}", hint=f"当前有：{available}"
        )
    acked = sorted({*project.meta.acknowledged_risks, key})
    return project.prepare_meta_change(
        acknowledged_risks=acked,
        reason=reason or f"处置预警 {key}",
    )


def _indirect_risks(tasks: list[fmt.Task], by_id: dict[str, fmt.Task]) -> list[Risk]:
    """顺着依赖链推出来的影响——**这是推测，不是记录直接写的**。"""
    blocked = {task.id for task in tasks if task.status == "阻塞"}
    risks: list[Risk] = []
    for task in tasks:
        if task.done:
            continue
        direct = set(task.depends_on) & blocked
        indirect = _transitive_dependencies(task, by_id) & blocked
        beyond = sorted(indirect - direct)
        if beyond:
            risks.append(
                Risk(
                    kind="依赖被阻塞",
                    subject=task.id,
                    text=f"{task.id} 间接依赖的 {'、'.join(beyond)} 处于阻塞，它可能也会被拖住",
                    basis="沿依赖链推导，不是记录里直接写的",
                    inference="推测",
                )
            )
    return risks


def _transitive_dependencies(task: fmt.Task, by_id: dict[str, fmt.Task]) -> set[str]:
    """顺着依赖往上游走，收集所有（间接）依赖的任务编号。"""
    seen: set[str] = set()
    queue = list(task.depends_on)
    while queue:
        current = queue.pop()
        if current in seen:
            continue
        seen.add(current)
        parent = by_id.get(current)
        if parent is not None:
            queue.extend(parent.depends_on)
    return seen


def _requirement_growth(project: Project) -> int:
    """需求条目净增了多少（拿最早的 spec 快照对比）。没有历史就是 0。"""
    for entry in reversed(changes.history_entries(project)):  # 旧 → 新
        snapshot = entry / changes.BEFORE_DIR / fmt.SPEC_FILE
        if snapshot.is_file():
            first = fmt.parse_requirements(snapshot.read_text(encoding="utf-8"))
            return len(project.requirements()) - len(first)
    return 0


def _parse_day(value: str) -> dt.date | None:
    try:
        return dt.date.fromisoformat(value.strip())
    except ValueError:
        return None


def _parse_moment(value: str) -> dt.datetime | None:
    text = value.strip()
    for pattern in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(text, pattern)
        except ValueError:
            continue
    return None
