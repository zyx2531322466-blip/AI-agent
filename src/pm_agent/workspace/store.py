"""项目工作区的读写层（对应 tasks.md 的 T004）。

两条约定，后续所有功能都建在它们上面：

1. **读之前先校验**。格式不对就早失败、并说清怎么修（FR-037）。
2. **写只走这里**。T008 要在写入前加"预览 + 撤回"，所以写入入口
   必须先收敛成一个地方，否则那条需求会很难做。
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml

from ..errors import FormatError, WorkspaceError
from ..templates import render_template
from . import format as fmt


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

    def requirement_ids(self) -> list[str]:
        """规范里出现过的需求条目编号（去重、按编号排序）。

        注意：这是给 ``show`` 用的粗略统计；正式的需求条目解析在 T012。
        """
        return sorted(set(fmt.REQUIREMENT_ID_RE.findall(self.spec_text())))

    def tasks_summary(self) -> tuple[int, int]:
        """任务清单的 (总数, 已完成数)。正式解析在 T018。"""
        if not self.path(fmt.TASKS_FILE).is_file():
            return 0, 0
        text = self.read_text(fmt.TASKS_FILE)
        marks = [match.group(1) for match in fmt.TASK_LINE_RE.finditer(text)]
        done = sum(1 for mark in marks if mark.lower() == "x")
        return len(marks), done

    # ---- 写 ------------------------------------------------------------

    def write_text(self, relative: str, text: str) -> Path:
        """写入项目内的一个文件。

        目前是直接写入；T008 会在这里插入"预览 + 撤回"，
        因此调用方不要绕过这个方法自己写文件。
        """
        target = self.path(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        return target


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
    target.write_text(text, encoding="utf-8")
    created_items.append(target.name)
