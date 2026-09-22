"""交接记录：跨会话接上的那一份"交接班说明"（对应 tasks.md 的 T007）。

四条设计约束，都来自 plan.md §5.3 与 spec.md 的 FR-015 ~ FR-020：

1. **落在项目工作区的 ``sessions/`` 里**，一个会话一个文件。文件名就是会话键
   （``YYYY-MM-DD-HH-MM-SS``），所以"按文件名排序"等于"按时间排序"。
2. **走 ``Project`` 与 ``workspace/files.py``**：不自己实现 frontmatter 解析，
   也不绕过 ``Project.prepare_write()`` / ``apply()`` —— 那是 T008 定下的
   唯一写入路径（先出预览、落盘前留快照、可撤回）。
3. **引用而非复制**：目标写需求条目编号、决策写文件名，不抄正文。
4. **空会话也要合法**：三个必需段落都在，内容如实写"无进展"，
   而不是把字段留空（FR-016 要求三要素，FR-033 要求不编造填充内容）。
5. **写入路径不依赖解析旧记录**：``prev`` 只需要上一份的**键**，所以只看
   文件名，不去读它的内容——上一份坏了该由读取路径报错，不该拦住你写新的。
   （读校验与写门禁是两件事：读坏数据要拦住，写新数据不该被旧数据绑架。）

断链检测（``prev`` 指向的记录已被删除）留给 T029 的冲突校验，本模块不做。
"""

from __future__ import annotations

import datetime as dt
import re

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from ..errors import FormatError, WorkspaceError
from . import format as fmt
from .files import render_markdown, split_frontmatter
from .store import Project

SESSIONS_DIR = "sessions"

#: 会话键的格式。用短横线而不是冒号，因为在 Windows 上冒号不能进文件名。
SESSION_KEY_FMT = "%Y-%m-%d-%H-%M-%S"
SESSION_KEY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}$")

#: 正文的段落定义：字段名 → 标题。**字典顺序就是渲染顺序**，
#: 段落只在这里定义一次——顺序和标题各存一份迟早会漂。
SECTION_TITLES: dict[str, str] = {
    "did": "本轮做了什么",
    "state": "当前状态",
    "next_steps": "下一步建议",
    "open_questions": "未决问题",
    "references": "引用",
}

#: FR-016 要求的三个必需段落；其余都是可选段落
#: （可选段落不是 FR 要求的，但没有它们，记录会像快照而不像记录）
REQUIRED_SECTIONS: tuple[str, ...] = ("state", "next_steps", "open_questions")
_OPTIONAL_NAMES = frozenset(SECTION_TITLES) - set(REQUIRED_SECTIONS)
_TITLE_TO_FIELD = {title: name for name, title in SECTION_TITLES.items()}

_SECTION_RE = re.compile(r"^##[ \t]+(.+?)[ \t]*$", re.MULTILINE)


@dataclass(frozen=True)
class Handoff:
    """一份交接记录。

    前四个字段进 frontmatter（程序读），后面的构成正文（人读）。
    ``prev`` 可选：第一份记录没有前驱，留空。
    """

    session: str
    created: str
    project: str
    status: str
    state: str
    next_steps: str
    open_questions: str
    did: str = ""
    references: str = ""
    prev: str | None = None


# ---- 校验 --------------------------------------------------------------


def check_handoff(
    handoff: Handoff,
    *,
    session_key: str | None = None,
    unknown_titles: Sequence[str] = (),
) -> list[fmt.Problem]:
    """检查一份记录是否合法，返回全部问题（不提前退出）。

    传入 ``session_key``（文件名里的会话键）时，会额外检查"记录自称的 session
    与文件名是否一致"——"最新一份"靠文件名排序，两者不一致会让排序失真。

    ``unknown_titles`` 是正文里认不出的 ``##`` 标题。**故意排在"缺内容"之前报**：
    标题写错往往正是"缺内容"的成因，先说原因、后说症状，人才知道往哪改。
    """
    where = f"{SESSIONS_DIR}/{session_key or handoff.session}.md"
    problems: list[fmt.Problem] = []

    for title in unknown_titles:
        problems.append(
            fmt.Problem(
                where,
                f"认不出的段落标题：「{title}」",
                f"可用标题：{'、'.join(SECTION_TITLES.values())}",
            )
        )

    if not SESSION_KEY_RE.match(handoff.session or ""):
        problems.append(
            fmt.Problem(
                where,
                f"session 不是合法的时间键：{handoff.session!r}",
                f"用 {SESSION_KEY_FMT}，例如 2026-09-22-21-17-04",
            )
        )

    if session_key is not None and handoff.session != session_key:
        problems.append(
            fmt.Problem(
                where,
                f"记录里的 session（{handoff.session}）与文件名（{session_key}）不一致",
                "两者必须一致——判断'最新一份'靠的是文件名排序",
            )
        )

    if fmt.coerce_iso_date(handoff.created) is None:
        problems.append(
            fmt.Problem(
                where, f"created 不是合法日期：{handoff.created!r}", "用 YYYY-MM-DD"
            )
        )

    if handoff.status not in fmt.SESSION_STATUSES:
        problems.append(
            fmt.Problem(
                where,
                f"status 取值不合法：{handoff.status!r}",
                f"从 {'、'.join(fmt.SESSION_STATUSES)} 中选一个",
            )
        )

    if not handoff.project.strip():
        problems.append(
            fmt.Problem(where, "project 为空", "写入时会自动取自 project.yaml 的名称")
        )

    for name in REQUIRED_SECTIONS:
        title = SECTION_TITLES[name]
        value = getattr(handoff, name)
        if not isinstance(value, str) or not value.strip():
            problems.append(
                fmt.Problem(
                    where,
                    f"缺少「{title}」的内容",
                    '如实写；没有进展就写"无进展"，别留空（FR-016 / FR-033）',
                )
            )

    if handoff.prev and not SESSION_KEY_RE.match(handoff.prev):
        problems.append(
            fmt.Problem(
                where,
                f"prev 不是合法的时间键：{handoff.prev!r}",
                "填上一份记录的 session，或留空（第一份记录没有前驱）",
            )
        )

    return problems


def _require_valid(
    handoff: Handoff,
    *,
    session_key: str | None = None,
    unknown_titles: Sequence[str] = (),
) -> None:
    problems = fmt.errors(
        check_handoff(handoff, session_key=session_key, unknown_titles=unknown_titles)
    )
    if problems:
        raise FormatError(
            "交接记录不合法：\n" + fmt.render_problems(problems),
            hint="修好再写入；对照 sessions/ 里既有的记录看格式",
        )


# ---- 渲染与解析 --------------------------------------------------------


def render_handoff(handoff: Handoff) -> str:
    """把记录渲染成「frontmatter + 正文」的 Markdown 文本。"""
    meta: dict[str, str] = {
        "session": handoff.session,
        "created": handoff.created,
        "project": handoff.project,
        "status": handoff.status,
    }
    if handoff.prev:
        meta["prev"] = handoff.prev

    parts = [f"# 交接记录 · {handoff.session}"]
    for name, title in SECTION_TITLES.items():
        value = getattr(handoff, name)
        if name in _OPTIONAL_NAMES and not str(value).strip():
            continue
        parts.append(f"## {title}\n\n{str(value).strip()}")

    return render_markdown(meta, "\n\n".join(parts))


def _split_sections(body: str) -> tuple[dict[str, str], list[str]]:
    """把正文按 ``## 标题`` 切成 ``{字段名: 内容}``，并报告认不出的标题。

    认不出的标题**不能静默丢弃**：那样使用者会看到"缺少「当前状态」的内容"，
    可他明明写了那一段、只是标题打错了——错误信息会把他引到错误的地方（FR-037）。
    """
    matches = list(_SECTION_RE.finditer(body))
    sections: dict[str, str] = {}
    unknown: list[str] = []
    for index, match in enumerate(matches):
        title = match.group(1).strip()
        field = _TITLE_TO_FIELD.get(title)
        if field is None:
            unknown.append(title)
            continue
        # 内容到下一个 ## 标题为止——不管下一个标题认不认识
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        sections[field] = body[match.end() : end].strip()
    return sections, unknown


def parse_handoff(text: str, *, session_key: str) -> Handoff:
    """把一份交接记录的 Markdown 文本解析成 :class:`Handoff` 并校验。"""
    where = f"{SESSIONS_DIR}/{session_key}.md"
    meta, body, has_frontmatter = split_frontmatter(text)

    if not has_frontmatter:
        raise FormatError(
            f"交接记录不合法：\n- {where}：缺少 frontmatter → "
            "文件开头应有两行 --- 包住的元数据",
            hint="对照 sessions/ 里既有的记录改一下",
        )

    sections, unknown_titles = _split_sections(body)
    handoff = Handoff(
        session=str(meta.get("session") or "").strip(),
        created=str(meta.get("created") or "").strip(),
        project=str(meta.get("project") or "").strip(),
        status=str(meta.get("status") or "").strip(),
        state=sections.get("state", ""),
        next_steps=sections.get("next_steps", ""),
        open_questions=sections.get("open_questions", ""),
        did=sections.get("did", ""),
        references=sections.get("references", ""),
        # 手写 `prev:`（不写值）时 YAML 给出 None，不能直接 str() 成 "None"
        prev=str(meta["prev"]).strip() if meta.get("prev") else None,
    )
    _require_valid(handoff, session_key=session_key, unknown_titles=unknown_titles)
    return handoff


# ---- 读写 --------------------------------------------------------------


def list_handoffs(project: Project) -> list[Path]:
    """列出全部交接记录，最新的在前。

    文件名是定长时间键，所以**按文件名字符串排序就等于按时间排序**。
    目录不存在时返回空列表；不符合命名的文件被忽略。
    """
    folder = project.path(SESSIONS_DIR)
    if not folder.is_dir():
        return []
    return sorted(
        (path for path in folder.glob("*.md") if SESSION_KEY_RE.match(path.stem)),
        key=lambda path: path.stem,
        reverse=True,
    )


def read_handoff(project: Project, session_key: str) -> Handoff:
    """读一份指定的交接记录。"""
    path = project.path(SESSIONS_DIR, f"{session_key}.md")
    if not path.is_file():
        raise WorkspaceError(
            f"找不到这份交接记录：{SESSIONS_DIR}/{session_key}.md",
            hint="用 list_handoffs() 看看有哪些；文件名就是会话键",
        )
    return parse_handoff(path.read_text(encoding="utf-8"), session_key=session_key)


def read_latest_handoff(project: Project) -> Handoff | None:
    """读最新的一份；一份都没有时返回 ``None``（第一次会话就是这种情况）。"""
    paths = list_handoffs(project)
    if not paths:
        return None
    return read_handoff(project, paths[0].stem)


def new_handoff(
    project: Project,
    *,
    state: str,
    next_steps: str,
    open_questions: str,
    did: str = "",
    references: str = "",
    status: str = "ok",
    moment: dt.datetime | None = None,
) -> Handoff:
    """按当前时间与既有记录，组装一份待写入的交接记录。

    - ``session`` / ``created`` 由 ``moment``（默认现在）决定；
    - ``prev`` 自动指向当前最新的一份，没有则为 ``None``。**只取文件名，
      不解析它的内容**——上一份坏了是读取路径要报的错，不该拦住写入；
    - 同一秒已被占用时**往后挪一秒**，这样文件名永远是纯时间键，
      不需要 ``-1`` 这类后缀（否则"最新一份"的正则会变得复杂易错）；
    - ``status`` 等字段当场校验，早失败。
    """
    moment = moment or dt.datetime.now()
    folder = project.path(SESSIONS_DIR)
    session = moment.strftime(SESSION_KEY_FMT)
    while (folder / f"{session}.md").exists():
        moment += dt.timedelta(seconds=1)
        session = moment.strftime(SESSION_KEY_FMT)

    existing = list_handoffs(project)
    handoff = Handoff(
        session=session,
        created=fmt.coerce_iso_date(moment) or "",
        project=project.meta.name,
        status=status,
        state=state,
        next_steps=next_steps,
        open_questions=open_questions,
        did=did,
        references=references,
        prev=existing[0].stem if existing else None,
    )
    _require_valid(handoff)
    return handoff


def write_handoff(project: Project, handoff: Handoff) -> Path:
    """写入一份交接记录，返回文件路径。

    已存在同名记录时**拒绝覆盖**——"绝不覆盖"是原则 4 的底线；要新写一份，
    用 :func:`new_handoff` 生成新的会话键。
    """
    _require_valid(handoff)
    relative = f"{SESSIONS_DIR}/{handoff.session}.md"
    target = project.path(relative)
    if target.exists():
        raise FormatError(
            f"这份交接记录已经存在，拒绝覆盖：{relative}",
            hint="用 new_handoff() 生成新的会话键，不要改旧记录",
        )
    # 走 T008 的变更机制：先产出 Change（预览用），再由它统一落盘并留历史
    change = project.prepare_write(
        relative, render_handoff(handoff), reason=f"写入交接记录 {handoff.session}"
    )
    project.apply(change)
    return target
