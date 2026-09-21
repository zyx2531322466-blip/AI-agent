"""项目工作区的格式定义与校验规则。

这里是「项目即目录」这个决定的落点（plan.md §2）：

- 格式定义写在本文件，人可读的模板放在 ``pm_agent/templates/``；
- 两处必须一致，改了一处就要改另一处——校验规则会替你发现不一致；
- 校验结果分两级：``error`` 会阻止项目被打开，``warn`` 只提示不影响使用。

为什么要把"格式"独立成一个模块：格式一旦分散在各处，
使用者手工改坏一个字段后，程序只会抛一句没人看得懂的错误。
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1"
SUPPORTED_SCHEMA_VERSIONS = frozenset({SCHEMA_VERSION})

# 文件名：与 plan.md §4.2 的项目工作区目录结构一一对应
PROJECT_FILE = "project.yaml"
SPEC_FILE = "spec.md"
PLAN_FILE = "plan.md"
TASKS_FILE = "tasks.md"

REQUIRED_FILES = (PROJECT_FILE, SPEC_FILE)
OPTIONAL_FILES = (PLAN_FILE, TASKS_FILE)
DATA_DIRECTORIES = ("evidence", "decisions", "sessions", "reports", "skills", "history")

PROJECT_STATUSES = ("active", "paused", "done")

# 需求条目编号与任务勾选框的识别规则。
# 目前只用于"有没有"的粗略判断与统计；正式解析属于 T012 / T018。
REQUIREMENT_ID_RE = re.compile(r"\bFR-\d{3}\b")
TASK_LINE_RE = re.compile(r"^- \[([ xX])\]", re.MULTILINE)

LEVEL_ERROR = "error"
LEVEL_WARN = "warn"


@dataclass(frozen=True)
class Problem:
    """一条校验问题：出在哪里、出了什么事、该怎么办。"""

    where: str
    message: str
    fix: str
    level: str = LEVEL_ERROR

    def render(self) -> str:
        return f"{self.where}：{self.message} → {self.fix}"


@dataclass
class ProjectMeta:
    """``project.yaml`` 的结构化表示。"""

    schema_version: str
    name: str
    goal: str
    created: str
    status: str
    learning_goals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "name": self.name,
            "goal": self.goal,
            "created": self.created,
            "status": self.status,
            "learning_goals": list(self.learning_goals),
        }


def new_project_meta(
    *,
    name: str,
    goal: str,
    learning_goals: list[str] | None = None,
    created: str | None = None,
    status: str = "active",
) -> ProjectMeta:
    """按当前格式生成一份项目元信息（T003 的格式定义在这里被固化）。"""
    return ProjectMeta(
        schema_version=SCHEMA_VERSION,
        name=name.strip(),
        goal=goal.strip(),
        created=created or dt.date.today().isoformat(),
        status=status,
        learning_goals=[item.strip() for item in (learning_goals or []) if item.strip()],
    )


def _is_nonempty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def coerce_iso_date(value: Any) -> str | None:
    """把日期统一成 ``YYYY-MM-DD`` 字符串；不是日期就返回 None。

    为什么要单独写这个：**YAML 会把未加引号的 ``2026-09-13`` 解析成
    ``datetime.date``**，如果只接受字符串，使用者手工写下的日期反而会被
    判成非法——而"手工能改"正是原则 2 的底线（见 tests/test_format.py 的
    回归用例）。所以字符串与日期对象都接受，统一归一化。
    """
    if isinstance(value, dt.datetime):
        return value.date().isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if isinstance(value, str) and value.strip():
        try:
            return dt.date.fromisoformat(value.strip()).isoformat()
        except ValueError:
            return None
    return None


def validate_meta(data: Any) -> list[Problem]:
    """校验 project.yaml 的内容，返回全部问题（不提前退出）。"""
    where = PROJECT_FILE
    problems: list[Problem] = []

    if not isinstance(data, dict):
        problems.append(
            Problem(where, "顶层必须是「键: 值」结构", "检查是否写成了列表或纯文本")
        )
        return problems

    schema_version = data.get("schema_version")
    if schema_version is None:
        problems.append(
            Problem(where, "缺少 schema_version", f'补上 schema_version: "{SCHEMA_VERSION}"')
        )
    elif str(schema_version) not in SUPPORTED_SCHEMA_VERSIONS:
        problems.append(
            Problem(
                where,
                f"不支持的 schema_version：{schema_version}",
                "当前程序只支持 1；若是更新版本的文件，请升级程序",
            )
        )

    if not _is_nonempty_str(data.get("name")):
        problems.append(Problem(where, "缺少 name，或 name 为空", "补上这个项目的名称"))

    if not _is_nonempty_str(data.get("goal")):
        problems.append(
            Problem(where, "缺少 goal，或 goal 为空", "用一句话写清这个项目要达成什么")
        )

    created = data.get("created")
    if created is None or (isinstance(created, str) and not created.strip()):
        problems.append(
            Problem(where, "缺少 created", "补上创建日期，格式 YYYY-MM-DD")
        )
    elif coerce_iso_date(created) is None:
        problems.append(
            Problem(
                where,
                f"created 不是合法日期：{created}",
                "改成 YYYY-MM-DD，例如 2026-09-13",
            )
        )

    status = data.get("status")
    if not _is_nonempty_str(status):
        problems.append(
            Problem(where, "缺少 status", f"从 {'、'.join(PROJECT_STATUSES)} 中选一个")
        )
    elif str(status).strip() not in PROJECT_STATUSES:
        problems.append(
            Problem(
                where,
                f"status 取值不合法：{status}",
                f"改成 {'、'.join(PROJECT_STATUSES)} 之一",
            )
        )

    learning_goals = data.get("learning_goals")
    if learning_goals is None:
        problems.append(
            Problem(
                where,
                "缺少 learning_goals",
                '这是 FR-051 要求的「这个项目我想学到什么」，没有可写成 "learning_goals: []"',
            )
        )
    elif not isinstance(learning_goals, list):
        problems.append(
            Problem(where, "learning_goals 必须是列表", "- 每条学习目标写一行，前面加减号")
        )
    else:
        bad = [i for i, item in enumerate(learning_goals) if not _is_nonempty_str(item)]
        if bad:
            problems.append(
                Problem(
                    where,
                    f"learning_goals 第 {', '.join(str(i + 1) for i in bad)} 项为空或不是文本",
                    "删掉空项，或补上内容",
                )
            )
        elif not learning_goals:
            problems.append(
                Problem(
                    where,
                    "learning_goals 为空",
                    "至少写一条：这个项目你想学到什么（FR-051）",
                    level=LEVEL_WARN,
                )
            )

    return problems


def meta_from_dict(data: dict[str, Any]) -> ProjectMeta:
    """把已通过校验的字典转成 :class:`ProjectMeta`。"""
    return ProjectMeta(
        schema_version=str(data["schema_version"]),
        name=str(data["name"]).strip(),
        goal=str(data["goal"]).strip(),
        created=coerce_iso_date(data["created"]) or str(data["created"]).strip(),
        status=str(data["status"]).strip(),
        learning_goals=[str(item).strip() for item in data.get("learning_goals") or []],
    )


def errors(problems: list[Problem]) -> list[Problem]:
    return [item for item in problems if item.level == LEVEL_ERROR]


def warnings(problems: list[Problem]) -> list[Problem]:
    return [item for item in problems if item.level == LEVEL_WARN]


def render_problems(problems: list[Problem]) -> str:
    return "\n".join(f"- {item.render()}" for item in problems)


def _read_text(path: Path) -> tuple[str | None, Problem | None]:
    try:
        return path.read_text(encoding="utf-8"), None
    except UnicodeDecodeError:
        return None, Problem(
            path.name,
            "不是 UTF-8 编码，读不出来",
            "用支持 UTF-8 的编辑器另存一次（VS Code 右下角可切换编码）",
        )
    except OSError as exc:
        return None, Problem(path.name, f"读不了这个文件：{exc}", "检查文件权限与是否被占用")


def check_workspace(root: Path) -> list[Problem]:
    """检查一个项目工作区，返回全部问题（``error`` 会阻止项目被打开）。

    只读，不修改任何东西；自动修复在 CLI 的 ``check --fix`` 里做。
    """
    root = Path(root)
    problems: list[Problem] = []

    if not root.exists():
        return [Problem(str(root), "目录不存在", "运行 pm-agent init 创建这个项目")]
    if not root.is_dir():
        return [Problem(str(root), "不是一个目录", "指向一个文件夹，而不是文件")]

    project_path = root / PROJECT_FILE
    if not project_path.is_file():
        problems.append(
            Problem(PROJECT_FILE, "缺少项目元信息文件", "运行 pm-agent init 生成")
        )
    else:
        text, read_problem = _read_text(project_path)
        if read_problem is not None:
            problems.append(read_problem)
        else:
            problems.extend(_validate_project_text(text or ""))

    spec_path = root / SPEC_FILE
    if not spec_path.is_file():
        problems.append(Problem(SPEC_FILE, "缺少规范文件", "运行 pm-agent init 生成，或自己写一份"))
    else:
        text, read_problem = _read_text(spec_path)
        if read_problem is not None:
            problems.append(read_problem)
        elif not REQUIREMENT_ID_RE.search(text or ""):
            problems.append(
                Problem(
                    SPEC_FILE,
                    "没有找到形如 FR-001 的需求条目编号",
                    "给每条需求编号，任务才能追溯到需求（FR-003）",
                    level=LEVEL_WARN,
                )
            )

    tasks_path = root / TASKS_FILE
    if not tasks_path.is_file():
        problems.append(
            Problem(TASKS_FILE, "还没有任务清单", "等规范确认后，用 pm-agent plan/tasks 生成", level=LEVEL_WARN)
        )
    else:
        text, read_problem = _read_text(tasks_path)
        if read_problem is not None:
            problems.append(read_problem)
        elif not TASK_LINE_RE.search(text or ""):
            problems.append(
                Problem(
                    TASKS_FILE,
                    "任务清单里没有形如「- [ ]」的条目",
                    "每个任务写一行复选框，便于标记完成（FR-015）",
                    level=LEVEL_WARN,
                )
            )

    for name in DATA_DIRECTORIES:
        if not (root / name).is_dir():
            problems.append(
                Problem(name, "缺少数据目录", "运行 pm-agent check --fix 自动创建")
            )

    return problems


def _validate_project_text(text: str) -> list[Problem]:
    """解析并校验 project.yaml 的文本内容。"""
    import yaml  # 局部导入：让本模块的其余部分是纯逻辑，便于阅读与测试

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return [
            Problem(
                PROJECT_FILE,
                f"YAML 解析失败：{exc}",
                "常见原因：缩进不齐、冒号后缺空格、引号没有配对",
            )
        ]
    if data is None:
        return [Problem(PROJECT_FILE, "文件是空的", "至少补上 name、goal、created、status、learning_goals")]
    return validate_meta(data)
