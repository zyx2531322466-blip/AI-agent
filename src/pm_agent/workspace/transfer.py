"""项目搬来搬去：导出、恢复、演示副本、示范项目（T060 ~ T063）。

从 plan §11 的决定出发：**导出就是目录复制，不打包**。项目本来就是一堆人能直接
打开的文件，压缩包只会给"带出门演示"添一步解压。代价是文件多、复制慢一点——
对这个体量的项目不值一提。

三条性质，都有测试守着：

1. **导出 → 恢复后内容与状态一致**（逐文件比对字节）；
2. **副本与原件相互独立**：改副本不会回流到原件；
3. **示范项目可一键重置，且重置后逐字节一致**——所以 `build_demo` 接一个
   ``moment``，把时间戳固定住；不然每次建出来的交接记录都不一样，没法验。
"""

from __future__ import annotations

import datetime as dt
import shutil
from pathlib import Path

from ..errors import WorkspaceError
from . import format as fmt
from .files import render_markdown
from .handoff import new_handoff, write_handoff
from .store import Project, create_project

#: 演示项目里那份交接记录的时刻——固定住，重置才可比
DEMO_MOMENT = dt.datetime(2026, 9, 20, 10, 0, 0)

#: 示范项目的标记文件：`--reset` **只认它**（见 `_clear_demo`）
DEMO_MARKER = ".pm-agent-demo"

#: 标记文件里写什么——给将来打开这个目录的人看，不参与任何解析
DEMO_MARKER_TEXT = (
    "这是 pm-agent 建的示范项目。\n"
    "有这个文件，`pm-agent demo <这里> --reset` 才允许清空重建；\n"
    "没有它，--reset 会拒绝动手——避免它去清一个真实项目或别的目录。\n"
    "演示完把整个目录删掉就行。\n"
)


def export_project(project: Project, target: Path) -> Path:
    """把整个项目目录复制到 ``target``（FR-043）。目标已存在就拒绝。"""
    target = Path(target).expanduser()
    if target.exists():
        raise WorkspaceError(
            f"目标已经存在：{target}", hint="换一个位置，或者先把那里清空"
        )
    shutil.copytree(project.root, target)
    return target


def restore_project(source: Path, target: Path) -> Project:
    """从 ``source`` 恢复一份到 ``target``，并打开校验（FR-043）。"""
    source = Path(source).expanduser()
    target = Path(target).expanduser()
    if not (source / fmt.PROJECT_FILE).is_file():
        raise WorkspaceError(
            f"{source} 不像是一个项目目录", hint="它里面应该有 project.yaml"
        )
    if target.exists():
        raise WorkspaceError(f"目标已经存在：{target}", hint="换一个位置")
    shutil.copytree(source, target)
    return Project.open(target)


def copy_for_demo(project: Project, target: Path) -> Path:
    """把真实项目导出一份**副本**当演示项目（T062）。

    副本一经导出就与真实项目相互独立：演示时怎么折腾都行，改动不会回流（FR-044）。
    """
    return export_project(project, target)


def build_demo(target: Path, *, reset: bool = False, moment: dt.datetime | None = None) -> Project:
    """建一个示范项目；``reset=True`` 时先清掉再重建（T061）。

    因为时间戳固定，**重置后的目录与第一次建出来逐字节一致**——这才叫"回到初始状态"。

    ``reset`` 只对**本工具建的示范项目**有效（认 ``DEMO_MARKER``）。这条限制是
    T072 走查逼出来的：当时 ``pm-agent demo --reset`` 没给路径、落在工具自己的仓库
    根目录，它真的开始删了——先清掉 ``.git/hooks`` 与 ``.git/logs``，再被权限拦住。
    一个"清空目录"的动作，只要可能落在使用者自己挑的目录上，就必须有硬约束。
    """
    target = Path(target).expanduser()
    if reset and target.exists():
        _clear_demo(target)
    elif target.exists() and any(target.iterdir()):
        raise WorkspaceError(
            f"{target} 里已经有东西了",
            hint=(
                "换一个空目录；只有重建示范项目才用 --reset"
                f"（它只认带 {DEMO_MARKER} 标记的目录）"
            ),
        )

    moment = moment or DEMO_MOMENT
    project = create_project(
        target,
        name="待办清单（示范）",
        goal="做一个只在本地跑的待办清单：能记待办、标完成、按天回顾",
        learning_goals=["走一遍规范 → 任务 → 执行的完整链路"],
        created=moment.date().isoformat(),
    ).project

    project.apply(
        project.prepare_write(fmt.SPEC_FILE, _demo_spec(), reason="示范：铺规范"),
        moment=moment,
    )
    project.apply(
        project.prepare_write(fmt.TASKS_FILE, _demo_tasks(), reason="示范：铺任务"),
        moment=moment,
    )
    write_handoff(
        project,
        new_handoff(
            project,
            state="任务：完成 1 / 进行中 1 / 阻塞 0 / 未开始 1。",
            next_steps="- T003（P1）做按天回看",
            open_questions="- [待澄清] 待办标题最长允许多少字？",
            did="把待办表建起来并跑通读写；标题校验做到一半。",
            references="spec.md（规范）、tasks.md（任务清单）",
            moment=moment,
        ),
        moment=moment,
    )
    # 标记写在最后：只有整个示范项目建成了，它才配被 --reset 清空
    (project.root / DEMO_MARKER).write_text(DEMO_MARKER_TEXT, encoding="utf-8")
    return project


def _clear_demo(target: Path) -> None:
    """清空一个**示范项目**目录。三道闸，缺一不可。

    1. 不能是文件系统根（``C:\\`` 这种）；
    2. 必须是本工具建的示范项目——认 ``DEMO_MARKER`` 标记文件；
    3. 删的过程要能说清"删到哪了"。

    第 2 条是关键：只有标记认识这个目录，使用者的仓库、桌面、真实项目
    就都在保护范围里。第 3 条是因为半途失败比失败更糟——那时候目录已经不完整了，
    使用者必须立刻知道这件事，而不是看一段 Python 堆栈。
    """
    resolved = target.resolve()
    if resolved.parent == resolved:  # 根目录之类的，坚决不碰
        raise WorkspaceError(f"拒绝重置这个位置：{resolved}", hint="给一个具体的项目目录")
    if not (resolved / DEMO_MARKER).is_file():
        raise WorkspaceError(
            f"拒绝清空 {resolved}：它不是本工具建的示范项目",
            hint=(
                f"示范项目里会有一个 {DEMO_MARKER} 标记文件；这里没有。"
                "真要清空它，请自己动手删——这条命令不做这件事"
            ),
        )
    _remove_tree(resolved)


def _remove_tree(root: Path) -> int:
    """删掉整棵树，返回删掉的项数；半途失败时如实报出已经删了多少。

    不用 ``shutil.rmtree`` 的原因就一条：它失败时抛的是原始 ``OSError``，
    使用者既看不懂，也不知道目录现在是不是完整的。
    """
    removed = 0
    # 深的先删：子项的处理顺序必须排在它的父目录之前
    for path in sorted(root.rglob("*"), key=lambda item: len(item.parts), reverse=True):
        try:
            if path.is_dir() and not path.is_symlink():
                path.rmdir()
            else:
                path.unlink()
        except OSError as exc:
            raise WorkspaceError(
                f"清空 {root} 时失败：已经删掉 {removed} 项，"
                f"卡在 {exc.filename or '（不知道是哪个）'}",
                hint=(
                    "这个目录现在**不是完整的**——先看清少了什么再决定怎么办。"
                    "常见原因是文件被占用或没有删除权限；关掉占用它的程序（编辑器、"
                    "git 客户端、终端）再试一次"
                ),
            ) from exc
        removed += 1
    try:
        root.rmdir()
    except OSError as exc:
        raise WorkspaceError(
            f"清空 {root} 时失败：里面已经删了 {removed} 项，但目录本身没删掉",
            hint="关掉占用它的程序再试一次",
        ) from exc
    return removed


def _demo_spec() -> str:
    return render_markdown(
        {"status": "draft", "version": 1},
        """# 待办清单（示范） —— 功能需求规范

## 4. 功能需求

### A. 记录

- **FR-001** 能新增一条待办，字段含标题与是否完成。
- **FR-002** 能按天回看已完成的待办。

### B. 边界

- **FR-003** 标题长度上限还没定。[待澄清] 待办标题最长允许多少字？
""",
    )


def _demo_tasks() -> str:
    return """# 待办清单（示范） —— 任务清单

## M1 · 记录

- [x] **T001**（— / FR-001）把待办存下来。**完成标准**：新增一条后能读回。**优先级**：P1。**依赖**：无。**状态**：完成。**更新**：2026-09-18 09:00。**证据**：提交 a1b2c3d：待办表与读写。
- [ ] **T002**（— / FR-001）给待办加标题校验。**完成标准**：空标题被拒绝保存。**优先级**：P2。**依赖**：T001。**状态**：进行中。**更新**：2026-09-19 16:00。**结论**：校验放在写入口更省事。

## M2 · 回看

- [ ] **T003**（— / FR-002）做按天回看。**完成标准**：能按天列出已完成的待办。**优先级**：P1。**依赖**：T001。**状态**：未开始。
"""
