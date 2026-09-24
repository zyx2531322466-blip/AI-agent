"""多项目并行：跨项目总览（T055 ~ T058）。

**「当前项目」就是命令里给的那个路径。** 这个工具一次只面对一个项目，
切换就是换个路径——所以"切换后不残留上一个项目的上下文"不是靠清理实现，
而是靠**结构上做不到**：每个命令只打开自己那个目录，``Project.path()``
还会拒绝越出项目目录（见 ``workspace/store.py``）。

总览是**只读扫描**：打开每个项目读一读，不产生任何跨项目写入（FR-040）。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from ..workspace import format as fmt
from ..workspace.handoff import read_latest_handoff
from ..workspace.store import Project
from .risks import detect_risks


@dataclass(frozen=True)
class ProjectDigest:
    """一个项目的当前状态摘要——总览里的一行。"""

    root: Path
    name: str
    counts: dict[str, int]
    blocked: tuple[str, ...]
    risk_count: int
    last_session: str | None

    def one_line(self) -> str:
        blocked = f"阻塞 {len(self.blocked)}" if self.blocked else "无阻塞"
        session = self.last_session or "还没有交接记录"
        return (
            f"{self.name}：完成 {self.counts['完成']} / 进行中 {self.counts['进行中']} / "
            f"{blocked} / 风险 {self.risk_count}；最近交接 {session}"
        )


def find_projects(root: Path) -> list[Path]:
    """找出这个目录下的项目：它自己，以及它的一层子目录里有 ``project.yaml`` 的。

    只扫一层——项目集合是一个"平铺的架子"，不搞递归，免得把别人的仓库也扫进来。
    """
    root = Path(root).expanduser()
    found: list[Path] = []
    if (root / fmt.PROJECT_FILE).is_file():
        found.append(root)
    if root.is_dir():
        for entry in sorted(root.iterdir(), key=lambda item: item.name):
            if entry.is_dir() and (entry / fmt.PROJECT_FILE).is_file():
                found.append(entry)
    return found


def digest(project: Project, *, now: dt.datetime | None = None) -> ProjectDigest:
    """一个项目的摘要。只读。"""
    tasks = project.tasks()
    handoff = read_latest_handoff(project)
    return ProjectDigest(
        root=project.root,
        name=project.meta.name,
        counts={
            status: sum(1 for task in tasks if task.status == status)
            for status in fmt.TASK_STATUSES
        },
        blocked=tuple(task.id for task in tasks if task.status == "阻塞"),
        risk_count=len(detect_risks(project, now=now)),
        last_session=handoff.session if handoff else None,
    )


def overview(root: Path, *, now: dt.datetime | None = None) -> list[ProjectDigest]:
    """扫一个目录下的所有项目，逐个给摘要。**只读**，不写任何东西。"""
    return [digest(Project.open(path), now=now) for path in find_projects(root)]
