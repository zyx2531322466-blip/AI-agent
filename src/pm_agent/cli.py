"""命令行入口。

命令与里程碑的对应（plan.md §7）：

- ``init`` / ``show`` / ``check`` 属于 M0 骨架；
- ``ask`` 用于验证模型接入是否配好（T005）。

``specify`` / ``plan`` / ``tasks`` / ``track`` / ``report`` / ``skill`` /
``export`` 会在后续任务里逐个加入。**加之前不注册空命令**——
一个点了就报错的命令，还不如让它在帮助里根本不出现。
"""

from __future__ import annotations

import functools
import datetime as dt
from pathlib import Path
from typing import Callable, Optional

import typer
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__
from .errors import FormatError, PMAgentError, WorkspaceError
from .explain.design import export_design
from .explain.goals import goal_review
from .harness.projects import find_projects, overview
from .harness.impact import analyze_change_impact, trace_task
from .workspace.decisions import record_decision
from .templates import load as load_template
from .workspace.transfer import (
    build_demo,
    copy_for_demo,
    export_project,
    restore_project,
)
from .harness.session import session_brief
from .harness.report import build_report, check_report
from .harness.risks import acknowledge_risk, detect_risks
from .model import Message, get_provider
from .stages.specify import draft_spec, prepare_spec_change
from .stages.tasks import draft_coverage, draft_tasks, prepare_tasks_change
from .stages.work import draft_work, past_deliveries, pick_task, prepare_work_change
from .workspace import create_project
from .workspace import format as fmt
from .workspace.changes import history_entries, read_change_meta
from .workspace.requirements import requirement_history
from .workspace.review import confirm_requirement, export_review, resolve_clarification
from .workspace.handoff import draft_handoff, render_handoff, write_handoff
from .workspace.store import Project
from .workspace.tasks import (
    coverage_gaps,
    parse_status_update,
    ready_tasks,
    set_task_status,
)
from .workspace.skills import (
    get_skill,
    list_skills,
    load_reference,
    load_skill,
    record_usage,
    revise_skill,
    save_skill,
    share_skill,
    suggest_skills,
    usage_summary,
)
from .stages import announce

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "项目管理 Agent —— 规范驱动的本地项目管理助手。\n\n"
        "第一次用？先跑 `pm-agent guide`：它从建项目开始，一路带到出汇报，"
        "每一步都说明该敲什么、参数是什么意思。"
    ),
)
console = Console()


def label(tag: str, style: str, body: str) -> Text:
    """拼一行"标签 + 内容"，其中内容不做 markup 解析。

    为什么必须这样：模型输出、用户写的目标、文件里的报错原文都可能
    含有方括号（例如 ``[echo]``）。如果直接交给 Rich 打印，``[echo]``
    会被当成样式标签吃掉——这会毁掉 FR-037 要求的"明确标注"。
    """
    out = Text()
    out.append(tag, style=style)
    out.append(" ")
    out.append(body)
    return out


def guarded(func: Callable[..., None]) -> Callable[..., None]:
    """把可预期失败变成"说清楚 + 给下一步"，而不是抛堆栈（FR-037）。"""

    @functools.wraps(func)
    def wrapper(*args: object, **kwargs: object) -> None:
        try:
            func(*args, **kwargs)
        except PMAgentError as exc:
            console.print(label("错误", "bold red", exc.message))
            if exc.hint:
                console.print(label("怎么办", "yellow", exc.hint))
            raise typer.Exit(code=1) from exc

    return wrapper


@app.command()
def version() -> None:
    """显示版本号。"""
    console.print(f"pm-agent [bold]{__version__}[/]")


@app.command()
@guarded
def init(
    path: Path = typer.Argument(Path("."), help="项目目录，默认当前目录"),
    name: str = typer.Option(..., "--name", "-n", help="项目名称"),
    goal: str = typer.Option(..., "--goal", "-g", help="一句话说明这个项目要达成什么"),
    learning_goal: Optional[list[str]] = typer.Option(
        None,
        "--learning-goal",
        "-l",
        help="这个项目你想学到什么，可以重复多次（FR-051）",
    ),
    git: bool = typer.Option(
        True,
        "--git/--no-git",
        help="是否初始化 git 版本库，默认初始化（plan.md §11 的决策）",
    ),
) -> None:
    """创建一个项目工作区；已存在的文件不会被覆盖。"""
    result = create_project(
        path,
        name=name,
        goal=goal,
        learning_goals=list(learning_goal or []),
        init_git=git,
    )

    console.print(
        Panel(
            _titled(result.project.meta.name, result.project.meta.goal),
            title=f"项目已就绪：{result.project.root}",
            border_style="green",
        )
    )

    if result.created:
        console.print(label("新建", "green", "、".join(result.created)))
    if result.skipped:
        console.print(
            label(
                "已存在，保持原样",
                "yellow",
                "、".join(result.skipped) + "  （绝不覆盖你写过的东西）",
            )
        )

    git_message, git_tag, git_style = _git_summary(result.git_status)
    console.print(label(git_tag, git_style, git_message))
    if result.git_note:
        console.print(Text(f"  {result.git_note}"))

    console.print("[dim]下一步：pm-agent show 看看现状，或直接编辑 spec.md 写规范。[/]")


@app.command()
@guarded
def show(path: Path = typer.Argument(Path("."), help="项目目录，默认当前目录")) -> None:
    """显示项目概览。"""
    project = Project.open(path)
    meta = project.meta

    table = Table(show_header=False, box=None, pad_edge=False)
    table.add_column(style="bold cyan", no_wrap=True)
    table.add_column()
    table.add_row("名称", Text(meta.name))
    table.add_row("目标", Text(meta.goal))
    table.add_row("状态", Text(meta.status))
    table.add_row("创建日期", Text(meta.created))
    table.add_row("位置", Text(str(project.root)))

    console.print(Panel(table, title="项目", border_style="cyan"))

    goals = meta.learning_goals
    console.print("[bold]这个项目我想学到什么[/]（FR-051）")
    if goals:
        for item in goals:
            console.print(Text(f"  · {item}"))
    else:
        console.print("  [dim]还没写。在 project.yaml 的 learning_goals 里补上。[/]")

    requirement_ids = project.requirement_ids()
    total_tasks, done_tasks = project.tasks_summary()
    console.print()
    console.print("[bold]进度概览[/]")
    span = ""
    if len(requirement_ids) > 1:
        span = f"（{requirement_ids[0]} ~ {requirement_ids[-1]}）"
    console.print(Text(f"  需求条目：{len(requirement_ids)}{span}"))
    console.print(Text(f"  任务：{done_tasks}/{total_tasks} 已完成"))
    console.print(
        "[dim]注：需求条目已按规范解析；任务清单仍是编号统计（正式解析在 T018）。[/]"
    )

    problems = fmt.warnings(fmt.check_workspace(project.root))
    if problems:
        console.print()
        console.print("[yellow]提示[/]")
        for item in problems:
            console.print(Text(f"  · {item.render()}"))


@app.command()
@guarded
def resume(path: Path = typer.Argument(Path("."), help="项目目录，默认当前目录")) -> None:
    """重建状态摘要——会话的第一件事（FR-017）。

    有必须裁决的冲突时退出码为 1：先弄清记录和实际为什么对不上，再往下做。
    """
    project = Project.open(path)
    brief = session_brief(project)
    console.print(Text(brief.render()))
    if not brief.ok:
        raise typer.Exit(code=1)


@app.command()
@guarded
def check(
    path: Path = typer.Argument(Path("."), help="项目目录，默认当前目录"),
    fix: bool = typer.Option(False, "--fix", help="自动创建缺失的数据目录"),
) -> None:
    """检查项目工作区是否符合格式定义。"""
    root = Path(path).expanduser()

    if fix and root.is_dir():
        created = []
        for name in fmt.DATA_DIRECTORIES:
            target = root / name
            if not target.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                created.append(name + "/")
        if created:
            console.print("[green]已创建[/] " + "、".join(created))
        else:
            console.print("[dim]没有需要创建的目录。[/]")

    problems = fmt.check_workspace(root)
    blocking = fmt.errors(problems)
    warnings = fmt.warnings(problems)

    for item in warnings:
        console.print(label("提示", "yellow", item.render()))
    for item in blocking:
        console.print(label("问题", "red", item.render()))

    if blocking:
        console.print(f"\n[red]共 {len(blocking)} 处问题需要处理。[/]")
        raise typer.Exit(code=1)

    console.print("[green]格式检查通过。[/]")


@app.command()
@guarded
def ask(
    prompt: str = typer.Argument(..., help="要问模型的问题"),
    provider: Optional[str] = typer.Option(
        None, "--provider", "-p", help="模型实现：openai-compat（默认）或 echo"
    ),
    system: Optional[str] = typer.Option(None, "--system", help="可选的系统提示"),
) -> None:
    """调用一次模型，用于验证接入是否配好。"""
    impl = get_provider(provider)

    messages: list[Message] = []
    if system:
        messages.append(Message(role="system", content=system))
    messages.append(Message(role="user", content=prompt))

    console.print(f"[dim]模型实现：{impl.describe()}[/]")
    reply = impl.complete(messages)
    console.print(Panel(Text(reply), border_style="cyan"))


def _titled(title: str, subtitle: str) -> Text:
    body = Text()
    body.append(title, style="bold")
    body.append("\n")
    body.append(subtitle)
    return body


def _git_summary(status: str) -> tuple[str, str, str]:
    """把 git 初始化结果翻译成"发生了什么 + 该用什么颜色"。"""
    table = {
        "initialized": ("版本库已初始化，交接记录与产物从此可追溯", "git", "green"),
        "existing": ("已经是版本库，没有改动它", "git", "yellow"),
        "skipped": ("按 --no-git 的要求跳过了版本库初始化", "git", "dim"),
        "unavailable": ("没找到 git，已跳过版本库初始化", "git", "yellow"),
        "failed": ("git 初始化没有成功", "git", "red"),
    }
    return table.get(status, (status, "git", "dim"))


def _show_requirement_history(project: Project, requirement_id: str) -> None:
    """把某条需求的来龙去脉按时间打出来。"""
    revisions = requirement_history(project, requirement_id)
    if not revisions:
        console.print(f"[dim]没有找到 {requirement_id} 的变更记录。[/]")
        return
    if len(revisions) == 1 and revisions[0].time == "（无变更记录）":
        console.print(f"[dim]history/ 里还没有记录，看不出 {requirement_id} 的历史。[/]")
        console.print(Text(f"  当前内容：{revisions[0].after}"))
        return
    for revision in revisions:
        console.print(label(revision.time, "cyan", revision.reason or "（未写说明）"))
        if revision.before is None:
            console.print(Text(f"  + 出现：{revision.after}"))
        elif revision.after is None:
            console.print(Text(f"  - 删除：{revision.before}"))
        else:
            console.print(Text(f"  - {revision.before}"))
            console.print(Text(f"  + {revision.after}"))

@app.command()
@guarded
def stage(
    name: str = typer.Argument(..., help="阶段名：specify / plan / tasks / track"),
    explain: bool = typer.Option(
        False, "--explain", "-e", help="连取舍与被放弃的备选一起讲（FR-049）"
    ),
) -> None:
    """说明一个阶段的来龙去脉：目的、输入、产出、依据；--explain 再讲取舍。"""
    console.print(Text(announce(name, explain=explain)))


@app.command()
@guarded
def requirements(
    path: Path = typer.Argument(Path("."), help="项目目录，默认当前目录"),
    limit: int = typer.Option(20, "--limit", "-n", help="最多显示多少条"),
) -> None:
    """列出规范里的需求条目。"""
    project = Project.open(path)
    items = project.requirements()
    if not items:
        console.print("[dim]规范里还没有需求条目。[/]")
        return

    table = Table(title=f"需求条目（共 {len(items)} 条）")
    table.add_column("编号", style="cyan", no_wrap=True)
    table.add_column("分组")
    table.add_column("内容")
    for item in items[: max(limit, 0)]:
        table.add_row(Text(item.id), Text(item.section or "—"), Text(item.text))
    console.print(table)
    if len(items) > limit:
        console.print(f"[dim]（还有 {len(items) - limit} 条没显示，用 --limit 调整）[/]")


@app.command()
@guarded
def tasks(
    path: Path = typer.Argument(Path("."), help="项目目录，默认当前目录"),
    milestone: Optional[str] = typer.Option(None, "--milestone", "-m", help="只看某个里程碑"),
    ready: bool = typer.Option(False, "--ready", help="只看现在就能动手的（最小切片）"),
    coverage: bool = typer.Option(False, "--coverage", help="只看覆盖缺口（FR-010）"),
) -> None:
    """列出任务清单；--ready 看能动手的，--coverage 看缺口。"""
    project = Project.open(path)

    if coverage:
        console.print(Text(coverage_gaps(project).render()))
        return

    items = ready_tasks(project) if ready else project.tasks()
    if milestone:
        items = [item for item in items if item.milestone == milestone]
    if not items:
        console.print("[dim]没有符合条件的任务。[/]")
        return

    title = f"就绪任务（{len(items)} 个，按优先级排）" if ready else f"任务（共 {len(items)} 个）"
    table = Table(title=title)
    table.add_column("编号", style="cyan", no_wrap=True)
    table.add_column("状态", no_wrap=True)
    table.add_column("优先级", no_wrap=True)
    table.add_column("需求", no_wrap=True)
    table.add_column("动作")
    for item in items:
        table.add_row(
            Text(item.id),
            Text("完成" if item.done else "未完成"),
            Text(item.priority or "—"),
            Text("、".join(item.requirements) or "—"),
            Text(item.title),
        )
    console.print(table)


@app.command()
@guarded
def track(
    sentence: str = typer.Argument(..., help='一句话，例如 "T018 做完了，提交 abc123"'),
    path: Path = typer.Option(Path("."), "--path", "-C", help="项目目录，默认当前目录"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认"),
) -> None:
    """用一句话更新任务状态；程序先回显它听懂了什么（FR-019）。"""
    project = Project.open(path)
    update = parse_status_update(project, sentence)
    if update is None:
        raise WorkspaceError(
            "没听出这句话说的是哪个任务、要改成什么状态",
            hint='带上任务编号最省事，例如：pm-agent track "T018 做完了，提交 abc123"',
        )

    console.print(label("我听懂的是", "cyan", ""))
    console.print(Text(f"  项目：{project.meta.name}（{project.root}）"))
    console.print(Text(f"  任务：{update.task.id} {update.task.title}"))
    console.print(Text(f"  状态：{update.task.status} → {update.status}"))
    if update.evidence:
        console.print(Text(f"  证据：{update.evidence}"))

    if not yes and not typer.confirm("对吗？", default=True):
        console.print("[yellow]已取消，任务清单没有改动。[/]")
        return

    change = set_task_status(
        project, update.task.id, update.status, evidence=update.evidence or None
    )
    project.apply(change)
    console.print(label("已更新", "green", f"{update.task.id} → {update.status}"))


@app.command()
@guarded
def handoff(
    path: Path = typer.Argument(Path("."), help="项目目录，默认当前目录"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认，直接写入"),
) -> None:
    """把这一轮的状态写成交接记录，落到 sessions/（FR-016）。

    草稿里填的都是**事实**（任务状态、就绪任务、待澄清清单）；
    "这一轮做了什么"留白，那件事只有你知道，程序不替你编。
    """
    project = Project.open(path)
    record = draft_handoff(project)

    console.print("[dim]下面是草稿：事实部分已填好，「这一轮做了什么」请手工补一句。[/]")
    console.print()
    console.print(Text(render_handoff(record)))
    console.print()

    if not yes and not typer.confirm("写入这份交接记录？", default=True):
        console.print("[yellow]已取消，sessions/ 没有新增文件。[/]")
        return

    written = write_handoff(project, record)
    console.print(label("已写出", "green", str(written.relative_to(project.root))))
    console.print("[dim]下次开会话先跑 pm-agent resume 接上。[/]")


@app.command()
@guarded
def specify(
    path: Path = typer.Argument(Path("."), help="项目目录，默认当前目录"),
    goal: Optional[str] = typer.Option(
        None, "--goal", "-g", help="覆盖 project.yaml 里的一句话目标"
    ),
    provider: Optional[str] = typer.Option(
        None, "--provider", "-p", help="模型实现：deepseek（默认）/ openai-compat / echo"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认，直接写入"),
) -> None:
    """把目标整理成结构化规范，写入 spec.md（先给预览，确认后才写）。"""
    project = Project.open(path)
    impl = get_provider(provider)

    console.print(f"[dim]模型实现：{impl.describe()}[/]")
    console.print("[dim]正在生成规范，请稍候…[/]")

    draft = draft_spec(project, impl, goal=goal)
    change = prepare_spec_change(project, draft)

    console.print()
    console.print(change.render())
    console.print()

    if not yes and not typer.confirm("写入 spec.md？", default=True):
        console.print("[yellow]已取消，spec.md 没有任何改动。[/]")
        return

    result = project.apply(change)
    console.print(label("已写入", "green", "、".join(result.written)))
    console.print("[dim]想反悔就 pm-agent undo。[/]")


@app.command()
@guarded
def work(
    task_id: Optional[str] = typer.Argument(
        None, help="要执行的任务编号，例如 T003；不写就挑第一条能动手的"
    ),
    path: Path = typer.Option(Path("."), "--path", "-C", help="项目目录，默认当前目录"),
    provider: Optional[str] = typer.Option(
        None, "--provider", "-p", help="模型实现：deepseek（默认）/ openai-compat / echo"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认，直接留存"),
    redo: bool = typer.Option(
        False, "--redo", help="这条任务以前做过，明知重复也要重做（默认会拦住）"
    ),
    done: bool = typer.Option(
        False, "--done", help="写入后直接记为完成（不给就会当场问你一次）"
    ),
) -> None:
    """让 AI 接手一条任务：装配上下文 → 产出交付物 → **直接写进项目文件**。

    交付物里的文件会写进项目目录，同一条变更里再留一份记录（说明产出了哪些文件、
    依据什么上下文），所以能整体撤回。边界：不覆盖程序自己维护的文件、
    不越出项目目录、**不改任务状态**——完成仍由你拍板（FR-014 / FR-053）。
    """
    project = Project.open(path)
    task, why = pick_task(project, task_id)
    impl = get_provider(provider)

    console.print(label("项目", "cyan", f"{project.meta.name}（{project.root}）"))
    console.print(label("这次做的是", "cyan", f"{task.id} {task.title}"))
    console.print(f"[dim]为什么是它：{why}[/]")

    past = past_deliveries(project, task.id)
    if past:
        console.print(
            label("注意", "yellow", f"这条任务以前产出过 {len(past)} 次：")
        )
        for item in past:
            console.print(Text(f"     - {item.render()}", style="dim"))
        if not redo:
            raise WorkspaceError(
                f"{task.id} 之前已经产出过（最近一次 {past[-1].at}），这次没有重做",
                hint=(
                    f"想重做就先把它退掉：pm-agent undo {path}"
                    "（那批文件会一起退掉）\n"
                    f"觉得它其实已经做完了（产出就在项目里）："
                    f'pm-agent track "{task.id} 做完了，提交 <提交号>" --path {path}\n'
                    "确认要叠加再跑一遍就加 --redo；也可以直接改现有文件——"
                    "它给你的是草稿，最后一步始终由你定"
                ),
            )
        console.print("[dim]（--redo）这次会要求沿用上次的文件名，别另起一套。[/]")

    console.print(f"[dim]模型实现：{impl.describe()}[/]")
    console.print("[dim]正在装配上下文并产出交付物，请稍候…[/]")

    draft = draft_work(project, task, impl)
    change = prepare_work_change(project, task, draft)

    context_bits = []
    if draft.requirements:
        context_bits.append("需求 " + "、".join(draft.requirements))
    if draft.decisions:
        context_bits.append("决策 " + "、".join(draft.decisions))
    if draft.skills:
        context_bits.append("能力单元 " + "、".join(draft.skills))
    if context_bits:
        console.print(label("上下文来自", "dim", "；".join(context_bits)))

    console.print()
    console.print(change.render())
    console.print()

    if not yes and not typer.confirm("把这批文件写进项目？", default=True):
        console.print("[yellow]已取消，项目里没有任何改动。[/]")
        return

    result = project.apply(change)
    console.print(label("已写入", "green", "、".join(result.written)))
    console.print("[dim]下一步：照产出里第 3 节的办法，自己跑一遍验证；不对就整体撤回："
                  f"pm-agent undo {path}[/]")

    # 写完了 ≠ 做完了。就在这一轮里问一次——省掉"再敲一条 track、还要自己拼证据"（FR-057）。
    record = next(
        (item for item in result.written if item.startswith(f"{fmt.EVIDENCE_DIR}/")), ""
    )
    delivered = tuple(
        item for item in result.written if item and item != record and item != fmt.TASKS_FILE
    )
    wants_done = done
    if not done and not yes:
        console.print()
        wants_done = typer.confirm("这条任务算完成了吗？", default=False)
    if wants_done:
        evidence = f"{record}（产出：{'、'.join(delivered) or '无文件'}）" if record else (
            "、".join(delivered) or "本次执行没有产出文件"
        )
        project.apply(
            set_task_status(project, task.id, "完成", evidence=evidence)
        )
        console.print(label("已记为完成", "green", f"{task.id} → 完成"))
        console.print(label("证据", "dim", evidence))
    else:
        console.print(
            f'[dim]没标完成，它现在是「进行中」。做完时说一声：'
            f'pm-agent track "{task.id} 做完了，提交 <提交号>" --path {path}[/]'
        )


@app.command()
@guarded
def breakdown(
    path: Path = typer.Argument(Path("."), help="项目目录，默认当前目录"),
    provider: Optional[str] = typer.Option(
        None, "--provider", "-p", help="模型实现：deepseek（默认）/ openai-compat / echo"
    ),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认，直接写入"),
) -> None:
    """把规范拆成任务清单，写入 tasks.md（先给预览，确认后才写）。"""
    project = Project.open(path)
    requirements = project.requirements()
    if not requirements:
        raise WorkspaceError(
            "规范里还没有需求条目，没法拆解",
            hint="先跑 pm-agent specify 生成规范，或手工往 spec.md 里写条目",
        )

    impl = get_provider(provider)
    console.print(f"[dim]模型实现：{impl.describe()}[/]")
    console.print(f"[dim]正在把 {len(requirements)} 条需求拆成任务，请稍候…[/]")

    draft = draft_tasks(project, impl)
    change = prepare_tasks_change(project, draft)

    report = draft_coverage(project, draft)
    console.print()
    if report.ok:
        console.print("[green]覆盖检查：每条需求都有任务为它服务。[/]")
    else:
        console.print("[yellow]覆盖缺口（FR-010：只报告，不挡写入）[/]")
        console.print(Text(report.render()))

    console.print()
    console.print(change.render())
    console.print()

    if not yes and not typer.confirm("写入 tasks.md？", default=True):
        console.print("[yellow]已取消，tasks.md 没有任何改动。[/]")
        return

    result = project.apply(change)
    console.print(label("已写入", "green", "、".join(result.written)))
    console.print("[dim]看能动手的任务：pm-agent tasks --ready。[/]")


@app.command()
@guarded
def history(
    path: Path = typer.Argument(Path("."), help="项目目录，默认当前目录"),
    limit: int = typer.Option(10, "--limit", "-n", help="最多显示多少条"),
    requirement: Optional[str] = typer.Option(
        None, "--requirement", "-r", help="只看某条需求的历史，例如 FR-003"
    ),
) -> None:
    """列出变更记录，最近在前；加 --requirement 看某条需求的来龙去脉。"""
    project = Project.open(path)
    if requirement:
        _show_requirement_history(project, requirement)
        return

    entries = history_entries(project)
    if not entries:
        console.print("[dim]还没有任何变更记录。[/]")
        return

    table = Table(title=f"变更记录（共 {len(entries)} 条）")
    table.add_column("时间", style="cyan", no_wrap=True)
    table.add_column("状态", no_wrap=True)
    table.add_column("说明")
    table.add_column("文件", justify="right", no_wrap=True)
    for entry in entries[: max(limit, 0)]:
        meta = read_change_meta(entry)
        table.add_row(
            Text(entry.name),
            Text("已撤回" if meta.get("undone") else "可撤回"),
            Text(str(meta.get("reason") or "（未写说明）")),
            Text(f"{len(meta.get('files') or [])} 个"),
        )
    console.print(table)


@app.command()
@guarded
def undo(path: Path = typer.Argument(Path("."), help="项目目录，默认当前目录")) -> None:
    """撤回最近一次变更。"""
    project = Project.open(path)
    result = project.undo_last()

    console.print(label("已撤回", "green", result.entry_dir.name))
    for item in result.restored:
        console.print(Text(f"  恢复  {item}"))
    for item in result.removed:
        console.print(Text(f"  删除  {item}（写入前它并不存在）"))


@app.command()
@guarded
def questions(path: Path = typer.Argument(Path("."), help="项目目录，默认当前目录")) -> None:
    """列出规范里还没答案的问题（FR-004）。"""
    project = Project.open(path)
    items = fmt.parse_clarifications(project.spec_text())
    if not items:
        console.print("[green]没有待澄清的问题。[/]")
        return

    table = Table(title=f"待澄清（{len(items)} 条）")
    table.add_column("序号", style="dim", no_wrap=True)
    table.add_column("来自", style="cyan", no_wrap=True)
    table.add_column("问题")
    for index, item in enumerate(items, start=1):
        table.add_row(str(index), Text(item.source), Text(item.text))
    console.print(table)
    console.print("[dim]回答其中一条：pm-agent clarify \"结论\" --for 序号或来源[/]")


@app.command()
@guarded
def clarify(
    answer: str = typer.Argument(..., help="这处待澄清定成了什么"),
    target: Optional[str] = typer.Option(
        None, "--for", "-f", help="回答哪一处：questions 里的序号，或来源（如 FR-003）；只剩一条时可不写"
    ),
    path: Path = typer.Option(Path("."), "--path", "-C", help="项目目录，默认当前目录"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认，直接写入"),
) -> None:
    """把一处待澄清的结论回填进规范（FR-054）：问题原样留着，后面记上结论。"""
    project = Project.open(path)
    change, resolved = resolve_clarification(project, answer=answer, target=target)
    left = len(fmt.parse_clarifications(project.spec_text())) - 1

    console.print(label("回答的是", "cyan", f"[{resolved.source}] {resolved.question}"))
    console.print(label("回填成", "green", resolved.after))
    if resolved.unconfirmed:
        console.print(
            label(
                "顺带作废确认",
                "yellow",
                f"{resolved.unconfirmed} 的内容变了，此前那次确认随之失效——"
                f"重看一遍再 pm-agent confirm {resolved.unconfirmed} --path {path}",
            )
        )
    if resolved.stale:
        console.print(
            label(
                "顺带提醒",
                "yellow",
                f"这句里还留着「{'、'.join(resolved.stale)}」这类字眼，措辞要不要顺一顺由你"
                "（直接编辑 spec.md 即可）",
            )
        )

    console.print()
    console.print(change.render())
    console.print()

    if not yes and not typer.confirm("把结论写进 spec.md？", default=True):
        console.print("[yellow]已取消，spec.md 没有任何改动。[/]")
        return

    result = project.apply(change)
    console.print(label("已回填", "green", "、".join(result.written)))
    console.print(
        f"[dim]这一处不再算未决；还剩 {max(left, 0)} 处——"
        f"pm-agent questions {path} 看全部。想反悔就 pm-agent undo。[/]"
    )


@app.command()
@guarded
def confirm(
    requirement_id: str = typer.Argument(..., help="要确认的需求编号，例如 FR-003"),
    path: Path = typer.Option(Path("."), "--path", "-C", help="项目目录，默认当前目录"),
) -> None:
    """确认一条需求：看过了，可以按它去做（FR-006）。

    这是使用者明确发起的小改动（只动 frontmatter 一行），所以打印预览后直接写入，
    不再二次询问——反悔有 ``pm-agent undo``。
    """
    project = Project.open(path)
    change = confirm_requirement(project, requirement_id)
    if change.is_noop:
        console.print(label("无需改动", "yellow", f"{requirement_id} 已经确认过"))
        return
    console.print(change.render())
    project.apply(change)
    console.print(label("已确认", "green", requirement_id))


@app.command()
@guarded
def review(
    path: Path = typer.Argument(Path("."), help="项目目录，默认当前目录"),
) -> None:
    """导出一份给别人看的评审稿（FR-007）。"""
    project = Project.open(path)
    change = export_review(project)
    console.print(label("写往", "cyan", change.entries[0].path))
    result = project.apply(change)
    console.print(label("已写出", "green", "、".join(result.written)))
    console.print("[dim]这份稿子不依赖本工具：直接发给别人读就行。[/]")


@app.command()
@guarded
def goals(path: Path = typer.Argument(Path("."), help="项目目录，默认当前目录")) -> None:
    """对照「这个项目我想学到什么」和已经产出的东西（FR-051）。"""
    project = Project.open(path)
    console.print(Text(goal_review(project).render()))


@app.command()
@guarded
def design(
    path: Path = typer.Argument(Path("."), help="项目目录，默认当前目录"),
) -> None:
    """导出设计说明：把「为什么这么设计」汇总成一份可读文档（T036）。"""
    project = Project.open(path)
    change = export_design(project)
    console.print(label("写往", "cyan", change.entries[0].path))
    result = project.apply(change)
    console.print(label("已写出", "green", "、".join(result.written)))
    console.print("[dim]这份文档讲的是为什么，不是怎么用——评审和简历都能用。[/]")


@app.command()
@guarded
def risks(
    path: Path = typer.Argument(Path("."), help="项目目录，默认当前目录"),
    include_all: bool = typer.Option(False, "--all", help="连已处置的也列出来"),
    acknowledge: Optional[str] = typer.Option(
        None, "--ack", help="标记某条预警已处置，例如 超期:T005"
    ),
) -> None:
    """风险视图：五类风险，事实与推测分开（FR-021 / FR-023 / FR-024）。"""
    project = Project.open(path)

    if acknowledge:
        project.apply(acknowledge_risk(project, acknowledge))
        console.print(label("已处置", "green", acknowledge))
        console.print("[dim]同类预警不再重复提醒；想看全部加 --all。[/]")
        return

    items = detect_risks(project, include_acknowledged=include_all)
    if not items:
        console.print("[green]没有风险。[/]")
        return

    table = Table(title=f"风险（{len(items)} 条）")
    table.add_column("类型", style="cyan", no_wrap=True)
    table.add_column("对象", no_wrap=True)
    table.add_column("标记", no_wrap=True)
    table.add_column("说明")
    for risk in items:
        table.add_row(
            Text(risk.kind), Text(risk.subject), Text(risk.inference), Text(risk.text)
        )
    console.print(table)
    console.print(f"[dim]处置某条：pm-agent risks . --ack \"{items[0].key}\"[/]")


@app.command()
@guarded
def report(
    path: Path = typer.Argument(Path("."), help="项目目录，默认当前目录"),
    audience: str = typer.Option("自己", "--audience", "-a", help="读者：自己 / 团队 / 上级"),
    since: Optional[str] = typer.Option(None, "--since", help="周期起点，例如 2026-09-16"),
    write: bool = typer.Option(False, "--write", "-w", help="同时存一份到 reports/"),
) -> None:
    """生成进度汇报：四类分组、每条标来源（FR-030 ~ FR-033）。"""
    project = Project.open(path)
    report_data = build_report(project, audience=audience, since=since)

    problems = check_report(report_data)
    if problems:
        raise FormatError(
            "汇报里有无法核查的内容，已打回：\n" + fmt.render_problems(problems),
            hint="补上来源再生成；补不上就别写进去（FR-031）",
        )

    text = report_data.render()
    console.print(Text(text))

    if not write:
        return
    stamp = dt.date.today().isoformat()
    change = project.prepare_write(
        f"reports/汇报-{stamp}.md", text, reason="生成进度汇报"
    )
    project.apply(change)
    console.print()
    console.print(label("已写出", "green", change.entries[0].path))


@app.command()
@guarded
def skills(
    path: Path = typer.Argument(Path("."), help="项目目录，默认当前目录"),
    suggest: Optional[str] = typer.Option(
        None, "--suggest", "-s", help="给一段描述，看哪几个能力单元相关"
    ),
) -> None:
    """列出能力单元（**只看元数据**）；`--suggest` 给建议。"""
    project = Project.open(path)

    if suggest:
        found = suggest_skills(project, suggest)
        if not found:
            console.print("[dim]没有明显相关的能力单元。[/]")
            return
        for item in found:
            console.print(label("建议", "cyan", f"{item.meta.name}（{item.reason}）"))
            console.print(Text(f"    {item.meta.description}"))
            console.print(Text(f"    适用：{item.meta.when_to_use}"))
        return

    items = list_skills(project)
    if not items:
        console.print("[dim]还没有能力单元。[/]")
        return
    usage = usage_summary(project)
    table = Table(title=f"能力单元（{len(items)} 个，这里只显示元数据）")
    table.add_column("名称", style="cyan", no_wrap=True)
    table.add_column("来源", no_wrap=True)
    table.add_column("采纳/拒绝", no_wrap=True)
    table.add_column("一句话说明")
    for meta in items:
        counts = usage.get(meta.name, {})
        table.add_row(
            Text(meta.name),
            Text(meta.source),
            Text(f"{counts.get('accepted', 0)}/{counts.get('declined', 0)}"),
            Text(meta.description),
        )
    console.print(table)
    console.print("[dim]看正文：pm-agent skill <名字>；看理由加 --why；读引用文件加 -r <文件>[/]")


@app.command()
@guarded
def skill(
    name: str = typer.Argument(..., help="能力单元的名字"),
    path: Path = typer.Option(Path("."), "--path", "-C", help="项目目录，默认当前目录"),
    why: bool = typer.Option(False, "--why", help="只看为什么这样做（FR-050）"),
    reference: Optional[str] = typer.Option(
        None, "--reference", "-r", help="读第三级：reference/ 下的文件"
    ),
) -> None:
    """看一个能力单元：默认正文，`--why` 看理由，`-r` 读引用文件。"""
    project = Project.open(path)
    meta = get_skill(project, name)

    if reference:
        console.print(Text(load_reference(project, name, reference)))
        return
    if why:
        console.print(label("为什么这样做", "cyan", meta.why))
        return

    console.print(label("元数据", "cyan", meta.one_line()))
    console.print()
    console.print(Text(load_skill(project, name)))


@app.command()
@guarded
def skill_save(
    name: str = typer.Option(..., "--name", "-n", help="能力单元的名字（英文短横线式）"),
    description: str = typer.Option(..., "--desc", "-d", help="一句话说明"),
    when_to_use: str = typer.Option(..., "--when", help="什么时候用它"),
    when_not_to_use: str = typer.Option(..., "--not-when", help="什么时候别用它"),
    inputs: str = typer.Option(..., "--inputs", help="需要什么"),
    outputs: str = typer.Option(..., "--outputs", help="产出什么"),
    why: str = typer.Option(..., "--why", help="为什么这样做（FR-050）"),
    steps: Optional[list[str]] = typer.Option(None, "--step", help="步骤要点，可重复"),
    version: str = typer.Option("1", "--version", help="版本号"),
    update: bool = typer.Option(False, "--update", help="改成修订已有能力单元"),
    path: Path = typer.Option(Path("."), "--path", "-C", help="项目目录，默认当前目录"),
) -> None:
    """把一次成功做法沉淀成能力单元——或修订已有的（`--update`）。"""
    project = Project.open(path)
    if update:
        change = revise_skill(
            project,
            name,
            version=version,
            steps=steps,
            description=description,
            when_to_use=when_to_use,
            when_not_to_use=when_not_to_use,
            inputs=inputs,
            outputs=outputs,
            why=why,
        )
    else:
        change = save_skill(
            project,
            name=name,
            description=description,
            when_to_use=when_to_use,
            when_not_to_use=when_not_to_use,
            inputs=inputs,
            outputs=outputs,
            why=why,
            steps=list(steps or []),
            version=version,
        )
    console.print(change.render())
    project.apply(change)
    console.print(label("已写出", "green", change.entries[0].path))


@app.command()
@guarded
def skill_use(
    name: str = typer.Argument(..., help="能力单元的名字"),
    outcome: str = typer.Option(..., "--outcome", "-o", help="accepted 或 declined"),
    path: Path = typer.Option(Path("."), "--path", "-C", help="项目目录，默认当前目录"),
) -> None:
    """记一次采纳或拒绝（FR-028）；拒绝之后有一段时间不再建议它（FR-027）。"""
    project = Project.open(path)
    project.apply(record_usage(project, name, outcome))
    console.print(label("已记录", "green", f"{name} → {outcome}"))


@app.command()
@guarded
def projects(
    root: Path = typer.Argument(Path("."), help="放项目的目录，默认当前目录"),
    detail: bool = typer.Option(False, "--detail", "-d", help="每个项目多给一行"),
) -> None:
    """跨项目总览：每个项目的进展、阻塞与风险（只读扫描，不写任何东西）。"""
    found = find_projects(root)
    if not found:
        console.print(f"[dim]{root} 下没有找到项目。[/]")
        return

    table = Table(title=f"项目总览（{len(found)} 个）")
    table.add_column("项目", style="cyan", no_wrap=True)
    table.add_column("位置")
    table.add_column("完成", justify="right", no_wrap=True)
    table.add_column("进行中", justify="right", no_wrap=True)
    table.add_column("阻塞", justify="right", no_wrap=True)
    table.add_column("风险", justify="right", no_wrap=True)
    table.add_column("最近交接", no_wrap=True)

    for item in overview(root):
        table.add_row(
            Text(item.name),
            Text(str(item.root)),
            Text(str(item.counts["完成"])),
            Text(str(item.counts["进行中"])),
            Text(str(len(item.blocked))),
            Text(str(item.risk_count)),
            Text(item.last_session or "—"),
        )
    console.print(table)
    if detail:
        for item in overview(root):
            console.print(Text(f"· {item.one_line()}"))
    console.print("[dim]切换项目就是换个路径：pm-agent show <项目目录>[/]")


@app.command()
@guarded
def skill_share(
    name: str = typer.Argument(..., help="要共享的能力单元名字"),
    source: Path = typer.Option(..., "--from", help="从哪个项目复制"),
    target: Path = typer.Option(..., "--to", help="复制到哪个项目"),
    new_name: Optional[str] = typer.Option(None, "--as", help="在目标项目里换个名字"),
) -> None:
    """把一个项目的能力单元复制到另一个项目（FR-041）。

    复制之后两边各是各的：来源的归属与使用历史不受影响。
    """
    source_project = Project.open(source)
    target_project = Project.open(target)
    change = share_skill(
        source_project, target_project, name, new_name=new_name
    )
    console.print(change.render())
    target_project.apply(change)
    console.print(
        label("已复制到", "green", f"{target_project.meta.name}/{change.entries[0].path}")
    )


@app.command()
@guarded
def export(
    path: Path = typer.Argument(Path("."), help="要导出的项目"),
    to: Path = typer.Option(..., "--to", help="导出到哪个位置"),
    for_demo: bool = typer.Option(False, "--for-demo", help="说明这份导出是用来演示的副本"),
) -> None:
    """把项目整个导出到另一个位置（目录复制，不打包）。"""
    project = Project.open(path)
    target = copy_for_demo(project, to) if for_demo else export_project(project, to)
    console.print(label("已导出到", "green", str(target)))
    console.print("[dim]目录复制：带出门演示不用解压，打开就能读。[/]")
    if for_demo:
        console.print("[dim]副本与真实项目相互独立：演示时怎么折腾都不会回流。[/]")


@app.command()
@guarded
def restore(
    source: Path = typer.Argument(..., help="从哪个目录恢复"),
    to: Path = typer.Option(..., "--to", help="恢复到哪个位置"),
) -> None:
    """从一份导出恢复成项目，并校验它能不能正常打开。"""
    project = restore_project(source, to)
    console.print(label("已恢复到", "green", str(project.root)))
    console.print(
        Text(
            f"  项目：{project.meta.name}；需求 {len(project.requirements())} 条、"
            f"任务 {len(project.tasks())} 个。"
        )
    )


@app.command()
@guarded
def demo(
    path: Path = typer.Argument(Path("."), help="示范项目放哪"),
    reset: bool = typer.Option(
        False,
        "--reset",
        help="先清空再重建（回到初始状态）；只对本工具建的示范项目有效",
    ),
) -> None:
    """建一个示范项目；`--reset` 回到初始状态。"""
    project = build_demo(path, reset=reset)
    console.print(label("示范项目就绪", "green", str(project.root)))
    console.print("[dim]下一步：pm-agent guide 看怎么走，或 pm-agent resume 看它现在到哪。[/]")
    console.print("[dim]它是独立的：演示完整个删掉就行。[/]")


@app.command()
@guarded
def guide() -> None:
    """第一次用？照着走一遍（不用先读文档）。"""
    console.print(Markdown(load_template("guide.md")))


@app.command()
@guarded
def impact(
    requirement_id: str = typer.Argument(..., help="要改的需求编号，例如 FR-022"),
    path: Path = typer.Option(Path("."), "--path", "-C", help="项目目录，默认当前目录"),
) -> None:
    """改一条需求之前，先看会波及什么（FR-022）。"""
    project = Project.open(path)
    console.print(Text(analyze_change_impact(project, requirement_id).render()))


@app.command()
@guarded
def decide(
    title: str = typer.Option(..., "--title", "-t", help="决策标题"),
    background: str = typer.Option(..., "--background", "-b", help="背景：为什么要定这件事"),
    option: Optional[list[str]] = typer.Option(None, "--option", "-o", help="备选方案，可重复"),
    choice: str = typer.Option(..., "--choice", "-c", help="最终选择"),
    why: str = typer.Option(..., "--why", help="理由"),
    path: Path = typer.Option(Path("."), "--path", "-C", help="项目目录，默认当前目录"),
) -> None:
    """记录一次关键决定（FR-036）：五样少一样都写不进去。"""
    project = Project.open(path)
    change = record_decision(
        project,
        title=title,
        background=background,
        options=list(option or []),
        choice=choice,
        why=why,
    )
    console.print(change.render())
    project.apply(change)
    console.print(label("已写出", "green", change.entries[0].path))


@app.command()
@guarded
def trace(
    task_id: str = typer.Argument(..., help="任务编号，例如 T067"),
    path: Path = typer.Option(Path("."), "--path", "-C", help="项目目录，默认当前目录"),
) -> None:
    """查一个任务的来龙去脉：来源需求 + 相关决策（T070）。"""
    project = Project.open(path)
    console.print(Text(trace_task(project, task_id).render()))
