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
from .model import Message, get_provider
from .workspace import create_project
from .workspace import format as fmt
from .workspace.store import Project
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
        "[dim]注：这里只是编号统计，正式的需求与任务解析在 T012 / T018。[/]"
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

@app.command()
@guarded
def stage(name: str = typer.Argument(..., help="阶段名：specify / plan / tasks / track")) -> None:
    """说明一个阶段的目的、输入与预期产出。"""
    console.print(Text(announce(name)))