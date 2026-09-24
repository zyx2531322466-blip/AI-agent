"""项目工作区的读写层（对应 tasks.md 的 T004）。

两条约定，后续所有功能都建在它们上面：

1. **读之前先校验**。格式不对就早失败、并说清怎么修（FR-037）。
2. **写必须先准备**。T008 之后没有"直接写"这个动作了：想落盘就得先
   :meth:`Project.prepare_write` 产出 :class:`~pm_agent.workspace.changes.Change`，
   再由 :meth:`Project.apply` 统一写入并留下可撤回的历史。
   这样"先出预览"就不是纪律，是类型（FR-034 / FR-035）。
"""

from __future__ import annotations

import shutil
import subprocess
import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from ..errors import FormatError, WorkspaceError
from ..templates import render_template
from . import changes
from . import format as fmt

if TYPE_CHECKING:
    from .changes import ApplyResult, Change, UndoResult


@dataclass
class Project:
    """一个已打开、且已通过格式校验的项目工作区。"""

    root: Path
    meta: fmt.ProjectMeta

    @classmethod
    def open(cls, root: str | Path) -> "Project":
        """打开项目；有 error 级问题时直接失败并列出全部问题。"""
        path = Path(root).expanduser()
        problems = fmt.check_workspace(path)
        blocking = fmt.errors(problems)
        if blocking:
            raise FormatError(
                f"项目工作区有问题，无法打开：\n{fmt.render_problems(blocking)}",
                hint="按上面的提示修一下；缺目录可以用 pm-agent check --fix",
            )
        resolved = path.resolve()
        return cls(root=resolved, meta=load_project_meta(resolved / fmt.PROJECT_FILE))

    # ---- 路径 ----------------------------------------------------------

    def path(self, *parts: str) -> Path:
        """项目内的相对路径。拒绝越出项目目录，避免误写到外面。"""
        candidate = (self.root.joinpath(*parts)).resolve()
        if candidate != self.root and self.root not in candidate.parents:
            raise WorkspaceError(
                f"路径越出了项目目录：{candidate}",
                hint="只能读写项目目录内的文件",
            )
        return candidate

    # ---- 读 ------------------------------------------------------------

    def read_text(self, *parts: str) -> str:
        target = self.path(*parts)
        if not target.is_file():
            raise WorkspaceError(f"文件不存在：{target.relative_to(self.root)}", hint="先创建它")
        return target.read_text(encoding="utf-8")

    def spec_text(self) -> str:
        return self.read_text(fmt.SPEC_FILE)

    def requirements(self) -> list[fmt.Requirement]:
        """规范里的需求条目（按出现顺序）。"""
        return fmt.parse_requirements(self.spec_text())

    def requirement_ids(self) -> list[str]:
        """需求条目编号（去重、按编号排序）。"""
        return sorted({item.id for item in self.requirements()})

    def tasks(self) -> list[fmt.Task]:
        """任务清单里的任务（按出现顺序）。"""
        if not self.path(fmt.TASKS_FILE).is_file():
            return []
        return fmt.parse_tasks(self.read_text(fmt.TASKS_FILE))

    def tasks_summary(self) -> tuple[int, int]:
        """任务清单的 (总数, 已完成数)。"""
        items = self.tasks()
        return len(items), sum(1 for item in items if item.done)

    # ---- 写（预览 → 落盘 → 可撤回，见 changes.py）------------------------

    def prepare_write(self, relative: str, text: str, *, reason: str = "") -> "Change":
        """准备一次写入：产出预览，**不碰磁盘**（FR-034）。"""
        return changes.prepare_write(self, relative, text, reason=reason)

    def prepare_meta_change(self, *, reason: str = "更新项目元信息", **fields: object) -> "Change":
        """改 ``project.yaml`` 里的字段，产出一份待确认的变更。

        元数据归程序维护（和 spec.md 的 frontmatter 一个道理），所以这里统一按
        当前 meta 重新渲染整个文件——它没有"人写的内容"需要保护。
        """
        data = self.meta.to_dict()
        data.update(fields)
        return self.prepare_write(
            fmt.PROJECT_FILE,
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
            reason=reason,
        )

    def apply(self, change: "Change", *, moment: dt.datetime | None = None) -> "ApplyResult":
        """落盘；写入前把原内容存进 ``history/``（FR-035）。

        ``moment`` 只在需要可复现的场合给（比如建示范项目）：
        历史目录名带时间戳，不给就按现在算。
        """
        result = changes.apply_change(self, change, moment=moment)
        # project.yaml 可能刚被改过：把内存里的元信息刷新一下。
        # 不刷新的话，同一进程里后续的判断（比如"这条预警处置过没有"）还会用旧值。
        if any(entry.path == fmt.PROJECT_FILE for entry in change.changed_entries):
            self.meta = load_project_meta(self.root / fmt.PROJECT_FILE)
        return result

    def undo_last(self) -> "UndoResult":
        """撤回最近一次尚未撤回的变更。"""
        return changes.undo_last(self)


def load_project_meta(path: Path) -> fmt.ProjectMeta:
    """读取并解析 project.yaml（假定已通过校验）。"""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise FormatError(
            f"{fmt.PROJECT_FILE} 解析失败：{exc}",
            hint="检查缩进与冒号；也可以运行 pm-agent check 看具体位置",
        ) from exc
    return fmt.meta_from_dict(data)


@dataclass
class CreationResult:
    """``create_project`` 的结果：建了什么、跳过了什么。"""

    project: Project
    created: list[str]
    skipped: list[str]
    #: git 初始化的结果：initialized / existing / unavailable / failed / skipped
    git_status: str = "skipped"
    #: git 没做成时的说明（对应 FR-037：说清楚，不静默跳过）
    git_note: str | None = None


def create_project(
    root: str | Path,
    *,
    name: str,
    goal: str,
    learning_goals: list[str] | None = None,
    created: str | None = None,
    init_git: bool = True,
) -> CreationResult:
    """增量创建一个项目工作区。

    **已存在的文件一律跳过，绝不覆盖**——这是原则 4「改动可预览」在
    初始化路径上的体现：使用者已经写好的 spec.md 不会被模板冲掉。

    ``init_git`` 默认开启（plan.md §11 的决策）：有了版本库，
    交接记录与提交历史就构成"跨会话证据"，也是后续冲突校验的依据。
    """
    path = Path(root).expanduser()
    path.mkdir(parents=True, exist_ok=True)

    created_items: list[str] = []
    skipped_items: list[str] = []

    meta = fmt.new_project_meta(
        name=name, goal=goal, learning_goals=learning_goals, created=created
    )
    project_yaml = yaml.safe_dump(
        meta.to_dict(), allow_unicode=True, sort_keys=False, default_flow_style=False
    )
    _write_if_absent(path / fmt.PROJECT_FILE, project_yaml, created_items, skipped_items)

    context = {
        "name": meta.name,
        "goal": meta.goal,
        "created": meta.created,
        "status": meta.status,
    }
    for template_name, target in (
        ("spec.md", fmt.SPEC_FILE),
        ("plan.md", fmt.PLAN_FILE),
        ("tasks.md", fmt.TASKS_FILE),
    ):
        _write_if_absent(
            path / target,
            render_template(template_name, context),
            created_items,
            skipped_items,
        )

    for directory in fmt.DATA_DIRECTORIES:
        target = path / directory
        if target.is_dir():
            skipped_items.append(f"{directory}/")
        else:
            target.mkdir(parents=True, exist_ok=True)
            created_items.append(f"{directory}/")

    git_status, git_note = ("skipped", None) if not init_git else ensure_git_repo(path)

    project = Project.open(path)

    # 自检：如果生成出来的东西自己不合法，说明模板与 format.py 已经不一致了，
    # 这时候必须立刻报错，而不是把坏格式留给使用者（FR-037）。
    blocking = fmt.errors(fmt.check_workspace(project.root))
    if blocking:
        raise FormatError(
            "生成的项目没有通过自检，说明模板与格式定义不一致（这是程序的问题）：\n"
            + fmt.render_problems(blocking),
            hint="请修 pm_agent/templates/ 下的模板，或调整 workspace/format.py 的校验规则",
        )

    return CreationResult(
        project=project,
        created=created_items,
        skipped=skipped_items,
        git_status=git_status,
        git_note=git_note,
    )


def ensure_git_repo(path: Path) -> tuple[str, str | None]:
    """确保目录是个 git 版本库；做完不成时如实说明，不静默跳过。

    返回 ``(状态, 说明)``，状态取值：

    - ``initialized``：新建了版本库
    - ``existing``：已经是版本库，没动它
    - ``unavailable``：这台机器上没有 git
    - ``failed``：git 在，但执行失败
    """
    if (path / ".git").exists():
        return "existing", None

    if shutil.which("git") is None:
        return (
            "unavailable",
            "这台机器上没找到 git，已跳过版本库初始化；"
            "装好 git 后在这个目录里执行 git init 即可，其余功能不受影响",
        )

    try:
        completed = subprocess.run(
            ["git", "init", "-q"],
            cwd=path,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return "failed", f"执行 git init 时出错：{exc}"

    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[:200]
        return "failed", f"git init 返回 {completed.returncode}：{detail}"

    return "initialized", None


def _write_if_absent(
    target: Path, text: str, created_items: list[str], skipped_items: list[str]
) -> None:
    if target.exists():
        skipped_items.append(target.name)
        return
    # 按字节写入：文本模式在 Windows 上会把 \n 翻译成 \r\n，那样
    # "读出来原样写回去"就成了字节级改动——撤回的"完全一致"和无变化判断都会失真。
    target.write_bytes(text.encode("utf-8"))
    created_items.append(target.name)
