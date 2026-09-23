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
from pathlib import Path
from typing import Callable, Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__
from .errors import PMAgentError
from .errors import WorkspaceError
from .model import Message, get_provider
from .stages.specify import draft_spec, prepare_spec_change
from .stages.tasks import draft_coverage, draft_tasks, prepare_tasks_change
from .workspace import create_project
from .workspace import format as fmt
from .workspace.changes import history_entries, read_change_meta
from .workspace.requirements import requirement_history
from .workspace.review import confirm_requirement, export_review
from .workspace.store import Project
from .workspace.tasks import coverage_gaps, ready_tasks
from .stages import announce

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="项目管理 Agent —— 规范驱动的本地项目管理助手。",
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
def stage(name: str = typer.Argument(..., help="阶段名：specify / plan / tasks / track")) -> None:
    """说明一个阶段的目的、输入与预期产出。"""
    console.print(Text(announce(name)))


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
    table.add_column("来自", style="cyan", no_wrap=True)
    table.add_column("问题")
    for item in items:
        table.add_row(Text(item.source), Text(item.text))
    console.print(table)


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
    path: Path = typer.Option(Path("."), "--path", "-C", help="项目目录，默认当前目录"),
) -> None:
    """导出一份给别人看的评审稿（FR-007）。"""
    project = Project.open(path)
    change = export_review(project)
    console.print(label("写往", "cyan", change.entries[0].path))
    result = project.apply(change)
    console.print(label("已写出", "green", "、".join(result.written)))
    console.print("[dim]这份稿子不依赖本工具：直接发给别人读就行。[/]")
