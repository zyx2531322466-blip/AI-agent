"""tasks 阶段：把需求条目拆解成任务清单（对应 tasks.md 的 T018）。

和 specify 是兄弟：同样只产出数据（不打印、不询问、不写文件），同样先校验再落盘，
同样把提示词放成数据文件（``prompts/tasks.*.md``）。

校验分两层，边界要分清：

- **挡住写入的**：解析不出任务、任务缺 FR-009 的三要素——这种草稿写进去就是坏清单。
- **只报告不挡的**：覆盖缺口（FR-010 说的是"报出来"）。缺口留着让人决定怎么补，
  不该由程序替他挡下来。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import FormatError
from ..model import Message, ModelProvider
from ..prompts import render as render_prompt
from ..workspace import format as fmt
from ..workspace.changes import Change
from ..workspace.files import split_frontmatter
from ..workspace.store import Project
from ..workspace.tasks import CoverageReport, coverage_gaps

MIN_TASKS = 1


@dataclass(frozen=True)
class TaskDraft:
    """模型产出的一份任务清单草稿（**尚未落盘**）。"""

    text: str
    source: str = ""


def draft_tasks(project: Project, provider: ModelProvider) -> TaskDraft:
    """调一次模型，产出一份任务清单草稿。**只读项目，不写文件。**"""
    requirements = project.requirements()
    rendered = (
        "\n".join(f"- **{item.id}**（{item.section}）{item.text}" for item in requirements)
        or "（规范里还没有需求条目）"
    )
    context = {
        "name": project.meta.name,
        "goal": project.meta.goal,
        "requirements": rendered,
    }
    messages = [
        Message(role="system", content=render_prompt("tasks.system.md", context)),
        Message(role="user", content=render_prompt("tasks.user.md", context)),
    ]
    reply = provider.complete(messages)
    return TaskDraft(text=_clean(reply), source=provider.describe())


def check_draft(project: Project, draft: TaskDraft) -> list[fmt.Problem]:
    """检查草稿能不能落盘：能解析、且每条任务三要素齐全。"""
    where = fmt.TASKS_FILE
    text = draft.text.strip()

    if not text:
        return [fmt.Problem(where, "模型返回了空内容", "重跑一次；反复为空就检查模型接入")]

    tasks = fmt.parse_tasks(text)
    problems: list[fmt.Problem] = []
    if len(tasks) < MIN_TASKS:
        problems.append(
            fmt.Problem(
                where,
                "草稿里没有解析出任何任务",
                "行格式要像 `- [ ] **T001**（— / FR-001）动作。**完成标准**：……**优先级**：P1。**依赖**：无`",
            )
        )
        return problems

    for task in tasks:
        missing: list[str] = []
        if "完成标准" not in task.fields or not task.standard:
            missing.append("完成标准")
        if "优先级" not in task.fields or not task.priority:
            missing.append("优先级")
        if "依赖" not in task.fields:
            missing.append("依赖")
        if missing:
            problems.append(
                fmt.Problem(
                    where,
                    f"{task.id} 缺要素：{'、'.join(missing)}",
                    "FR-009 要求三个要素齐全；重跑一次，或改 prompts/tasks.system.md",
                )
            )
    problems.extend(fmt.check_tasks(text))
    return problems


def prepare_tasks_change(project: Project, draft: TaskDraft, *, reason: str = "生成任务清单") -> Change:
    """校验草稿并组装成一份**待确认**的变更；不合格就抛错、不产出变更。"""
    problems = check_draft(project, draft)
    if problems:
        raise FormatError(
            "模型产出的任务清单不合格，没有写入任何文件：\n"
            + fmt.render_problems(problems)
            + f"\n\n模型原文（前 300 字）：\n{draft.text[:300]}",
            hint="重跑一次通常就好；反复失败就改 prompts/tasks.system.md",
        )
    return project.prepare_write(fmt.TASKS_FILE, draft.text, reason=reason)


def draft_coverage(project: Project, draft: TaskDraft) -> CoverageReport:
    """草稿的覆盖缺口（FR-010）——只报告，不挡写入。"""
    requirements = project.requirements()
    tasks = fmt.parse_tasks(draft.text)
    covered = {rid for task in tasks for rid in task.requirements}
    return CoverageReport(
        uncovered_requirements=tuple(r for r in requirements if r.id not in covered),
        sourceless_tasks=tuple(t for t in tasks if not t.has_source),
    )


def _clean(reply: str) -> str:
    """把模型回复清理成干净的清单正文（剥掉自加的 frontmatter 与代码围栏）。"""
    _, body, _ = split_frontmatter(reply)
    fence = "`" * 3
    stripped = body.strip()
    if stripped.startswith(fence) and stripped.endswith(fence):
        first_newline = stripped.find("\n")
        if first_newline != -1:
            stripped = stripped[first_newline + 1 : -len(fence)]
    return stripped.strip("\n") + "\n"
