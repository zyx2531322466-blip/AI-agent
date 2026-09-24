"""项目设计说明：把"为什么这么做"汇总成一份能直接给人看的文档（T036）。

简历材料的正确形态不是"我做了什么功能"，而是"我为什么这么设计、还考虑过什么"。
这些内容本来散在三处：阶段说明（`stages.yaml` 的取舍与备选）、学习目标
（`project.yaml`）、现在的进度（规范与任务）。这里把它们汇总成一份文档。

**不复制、只引用**：阶段说明是权威版本，这份文档是它的一个视图；
改了 `stages.yaml`，重新导一次就同步了。
"""

from __future__ import annotations

import datetime as dt

from ..stages import load_stages
from ..workspace.changes import Change
from ..workspace.store import Project

DESIGN_DIR = "reports"


def build_design_document(project: Project, *, today: str | None = None) -> str:
    """生成设计说明（纯 Markdown，不依赖本工具就能读）。"""
    stamp = today or dt.date.today().isoformat()
    lines: list[str] = [
        f"# {project.meta.name} —— 设计说明",
        "",
        f"- 导出日期：{stamp}",
        f"- 一句话目标：{project.meta.goal}",
        "",
        "> 这份文档讲的是**为什么这么设计**，不是怎么用。每条取舍都能在系统里找到出处。",
        "",
        "## 一、这个项目想学到什么",
        "",
    ]
    goals = project.meta.learning_goals
    lines += [f"- {goal}" for goal in goals] or ["（project.yaml 里还没写 learning_goals）"]

    lines += ["", "## 二、流程的每一步，各是为什么", ""]
    for index, (key, stage) in enumerate(load_stages().items(), start=1):
        lines += [
            f"### {index}. {stage.title}（`{key}`）",
            "",
            f"- **目的**：{stage.purpose}",
            f"- **依据**：{stage.basis or '（还没写依据）'}",
        ]
        if stage.tradeoffs:
            lines.append(f"- **取舍**：{stage.tradeoffs}")
        if stage.alternatives:
            lines.append(f"- **被放弃的备选**：{stage.alternatives}")
        lines.append("")

    requirements = project.requirements()
    tasks = project.tasks()
    sessions = (
        list(project.path("sessions").glob("*.md"))
        if project.path("sessions").is_dir()
        else []
    )
    lines += [
        "## 三、现在到哪",
        "",
        f"- 需求条目：{len(requirements)} 条",
        f"- 任务：{len(tasks)} 个，完成 {sum(1 for task in tasks if task.done)} 个",
        f"- 交接记录：{len(sessions)} 份",
        "",
        "## 四、这些「为什么」存在哪里",
        "",
        "- 阶段的依据与取舍：`stages/stages.yaml`（`pm-agent stage <名字> --explain` 也能看）",
        "- 设计原则与偏差记录：`plan.md`",
        "- 逐条需求与验收标准：`spec.md`",
        "- 每轮会话的交接：`sessions/`",
        "",
    ]
    return "\n".join(lines)


def export_design(
    project: Project, *, moment: dt.datetime | None = None, reason: str = "导出设计说明"
) -> Change:
    """产出一份"写入设计说明"的变更（**不落盘**）。"""
    stamp = (moment or dt.datetime.now()).strftime("%Y-%m-%d")
    return project.prepare_write(
        f"{DESIGN_DIR}/设计说明-{stamp}.md",
        build_design_document(project, today=stamp),
        reason=reason,
    )
