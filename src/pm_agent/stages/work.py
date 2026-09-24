"""work 阶段：让 AI 接手一条任务，产出交付物并留成证据（T078 / FR-053）。

使用者说这是最核心的需求——只有规范与拆解，链路停在文档层，
任务清单不产生价值，**任务被做掉**才产生价值。所以这一步补的是"动手"。

四条设计约束（与 specify 阶段同源）：

1. **只产出数据**：不打印、不询问、不写文件——预览与确认归 CLI（副作用留在最外层）。
2. **落盘必须经过 Change**：证据文件走 ``Project.prepare_write`` / ``apply``，
   所以"先出预览""能撤回"是白拿的。
3. **不信模型输出**：先校验再落盘；不合格就抛错并把原文交回，而不是把半成品留成证据。
4. **上下文来自项目**：任务、来源需求、相关决策、相关能力单元全部从项目里读出来，
   不需要使用者再讲一遍背景——这正是它比"手工复制粘贴给模型"强的地方，
   也是 FR-053 要求"自动装配上下文"的落点。

产出**直接落进项目工作区的文件**（v0.8 修订 FR-053）：交付物里以
``### 文件：<相对路径>`` 给出的内容，会被写进项目目录；同时留一条记录说明这次
产出了哪些文件、依据什么上下文。

三道闸必须同时成立（少一条都可能毁数据）：

1. **同一条变更**：文件与记录走同一个 :class:`Change`，所以能**整体**撤回，
   不会只退回一半；
2. **路径限制在项目目录内**：路径统一走 ``Project.path``（见 workspace/changes.py）；
3. **受保护文件不许碰**：``project.yaml`` / ``spec.md`` / ``plan.md`` / ``tasks.md``
   归各自的命令管，``history/`` 是撤回的地基——写进去会毁状态机。

仍然不改任务状态："这条任务算不算完成"由使用者看过、给出证据后拍板（FR-014）。
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

from ..errors import FormatError, WorkspaceError
from ..model import Message, ModelProvider
from ..model.echo import ECHO_MARKER
from ..prompts import render as render_prompt
from ..workspace import format as fmt
from ..workspace.changes import Change, merge, prepare_writes
from ..workspace.files import clean_model_reply, render_markdown, split_frontmatter
from ..workspace.skills import load_skill, suggest_skills
from ..workspace.store import Project
from ..workspace.tasks import ready_tasks, set_task_status

# 产出必须交代的四件事。校验按关键词判断——模型可以用自己的措辞，
# 但这四件事只要有一件完全没出现，就说明它漏了东西、或者只是在聊天。
REQUIRED_SECTIONS: tuple[str, ...] = ("做法", "交付物", "验证", "没做什么")

#: 太短的回复多半不是交付物，而是客套话
MIN_LENGTH = 200

#: 校验失败时带多少字的模型原文给人看
RAW_EXCERPT = 300

#: 上下文里最多带几个能力单元的正文（三级加载的第二级：用到才读）
MAX_SKILLS = 2

#: 交付物里"这个文件要落盘"的标题写法。提示词里写死了这个格式，解析按它来。
FILE_HEADING_RE = re.compile(r"^#{3,4}\s*(?:\*\*)?文件(?:\*\*)?\s*[：:]\s*(?P<path>.+?)\s*$")

#: 不许 `work` 直接写的文件：它们各有各的命令与格式，由这条命令代写会绕开校验
PROTECTED_FILES = frozenset(
    (fmt.PROJECT_FILE, fmt.SPEC_FILE, fmt.PLAN_FILE, fmt.TASKS_FILE)
)
#: 不许 `work` 直接写的目录：`.git` 是版本库，`history` 是撤回的地基
PROTECTED_PREFIXES = (".git/", f"{fmt.HISTORY_DIR}/")


@dataclass(frozen=True)
class Artifact:
    """交付物里给出的一个文件：写到哪、写什么。"""

    path: str
    content: str


@dataclass(frozen=True)
class PastDelivery:
    """这条任务以前的一次产出记录（从 ``evidence/`` 里读回来的事实）。"""

    record: str
    at: str
    files: tuple[str, ...]

    def render(self) -> str:
        files = "、".join(self.files) or "（没记文件）"
        return f"{self.at}（{self.record}）→ {files}"


@dataclass(frozen=True)
class WorkDraft:
    """模型为某条任务产出的一份交付物草稿（尚未落盘）。"""

    task_id: str
    text: str
    #: 产出它的模型实现说明，用于预览与追溯（例如 "DeepSeek：deepseek-chat…"）
    source: str = ""
    #: 这次装配进了哪些上下文——打印出来就是 FR-048 要的"这条产出依据了什么"
    requirements: tuple[str, ...] = ()
    decisions: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()


def pick_task(project: Project, task_id: str | None = None) -> tuple[fmt.Task, str]:
    """挑出这次要执行的任务，返回 (任务, 为什么挑它)。

    不给编号就自己挑：从"现在能动手的"里取优先级最高的那条（FR-013：先做最小切片）。
    依赖没完成的绝不硬上——绕过依赖做出来的东西，后面必然重做。
    """
    tasks = {task.id: task for task in project.tasks()}
    if not tasks:
        raise WorkspaceError(
            "任务清单里还没有任务",
            hint="先跑 pm-agent breakdown 把规范拆成任务，或手工往 tasks.md 里写",
        )

    if task_id is None:
        ready = ready_tasks(project)
        if not ready:
            blocked = "、".join(
                f"{task.id}（依赖 {'、'.join(task.depends_on)}）"
                for task in tasks.values()
                if task.status != "完成" and task.depends_on
            )
            raise WorkspaceError(
                "现在没有能动手的任务",
                hint=(
                    f"要么都做完了，要么都被依赖卡住：{blocked or '（没有依赖信息）'}。"
                    "把卡住的那条先做掉，或者先 pm-agent tasks 看看全貌"
                ),
            )
        chosen = ready[0]
        others = "、".join(task.id for task in ready[1:])
        why = f"依赖已满足；优先级 {chosen.priority or '未标'}；同批能动手的还有：{others or '无'}"
        return chosen, why

    if task_id not in tasks:
        available = "、".join(sorted(tasks))
        raise WorkspaceError(
            f"任务清单里没有 {task_id}",
            hint=f"现有任务：{available}",
        )
    chosen = tasks[task_id]
    if chosen.status == "完成":
        raise WorkspaceError(
            f"{task_id} 已经完成了（证据：{chosen.evidence or '没写'}）",
            hint="已完成的任务不必重做；要改就先把它的结论改掉，或者挑别的任务",
        )

    blocking = [
        dependency
        for dependency in chosen.depends_on
        if tasks.get(dependency) is None or tasks[dependency].status != "完成"
    ]
    if blocking:
        detail = "、".join(
            f"{item}（{tasks[item].status}）" if item in tasks else f"{item}（清单里没有）"
            for item in blocking
        )
        # 被挡住的依赖里如果有"其实已经产出过"的，就把那件事说出来并给出命令——
        # 只说"依赖未完成"会把人卡在死路上（真实发生过：T001 有产出却仍是未开始）。
        hint_lines = [f"先做掉：{detail}（FR-012）"]
        for item in blocking:
            if item not in tasks:
                continue
            produced = past_deliveries(project, item)
            if not produced:
                continue
            files = "、".join(produced[-1].files) or "（记录里没写文件）"
            hint_lines.append(
                f"注意 {item} 其实已经有产出了（{produced[-1].at}：{files}），"
                f'如果它确实做完了就标一下：pm-agent track "{item} 做完了，提交 <提交号>"'
                " --path <项目目录>"
            )
        raise WorkspaceError(
            f"{task_id} 的依赖还没完成，不能动手",
            hint="\n".join(hint_lines),
        )
    return chosen, f"你指定的；依赖已满足；优先级 {chosen.priority or '未标'}"


def past_deliveries(project: Project, task_id: str) -> tuple[PastDelivery, ...]:
    """这条任务以前产出过什么——从 ``evidence/`` 里的历次记录读回来（只读）。

    为什么要读它：同一条任务被跑第二遍时，如果没人拦、又没人告诉模型"上次产出了哪些文件"，
    它多半会另起一套命名（真实事故：一条任务跑 6 次，留下 `docs/T001-确认记录.md`、
    `css/style.css`、`styles.css` 等 9 个并存文件，`index.html` 的引用被反复改向）。
    记录里本来就写着 ``files``，读回来就能把这件事讲清楚。
    """
    folder = project.path(fmt.EVIDENCE_DIR)
    if not folder.is_dir():
        return ()
    found: list[PastDelivery] = []
    for path in sorted(folder.glob(f"{task_id}-*.md")):
        meta, _, has_frontmatter = split_frontmatter(path.read_text(encoding="utf-8"))
        if not has_frontmatter:
            continue
        raw = meta.get("files") or []
        files = tuple(str(item) for item in raw) if isinstance(raw, list) else ()
        found.append(
            PastDelivery(
                record=path.name,
                at=str(meta.get("at") or "（没写时间）"),
                files=files,
            )
        )
    return tuple(found)


def gather_context(project: Project, task: fmt.Task) -> dict[str, str]:
    """把这条任务需要的上下文从项目里读齐（只读）。

    四样东西各司其职：**它要达成什么**（完成标准）、**它为什么存在**（来源需求）、
    **这个项目定过什么调子**（决策）、**以前有没有类似做法**（能力单元）。
    """
    from ..harness.impact import trace_task  # 局部导入，避免把 harness 拉到 stages 的常态依赖里

    trace = trace_task(project, task.id)
    requirements = (
        "\n".join(f"- {item.id}：{item.text}" for item in trace.requirements)
        or "（这条任务没有关联到具体需求条目）"
    )
    decisions = (
        "\n".join(f"- {item.title}（{item.date}）：选了「{item.choice}」；理由：{item.why}" for item in trace.decisions)
        or "（还没有与它相关的决策记录）"
    )

    matched = suggest_skills(project, f"{task.title} {task.standard}", limit=MAX_SKILLS)
    skills = (
        "\n\n".join(
            f"### {item.meta.name}（{item.reason}）\n{load_skill(project, item.meta.name)}"
            for item in matched
        )
        or "（没有找到明显相关的做法）"
    )

    past = past_deliveries(project, task.id)
    previous = (
        "\n".join(f"- {item.render()}" for item in past)
        or "（没有：这是这条任务第一次做）"
    )
    return {
        "name": project.meta.name,
        "goal": project.meta.goal,
        "learning_goals": "；".join(project.meta.learning_goals) or "（未填写）",
        "task_id": task.id,
        "task_title": task.title,
        "task_milestone": task.milestone or "（未归入里程碑）",
        "task_reference": task.reference or "（没写引用）",
        "task_standard": task.standard or "（这条任务没写完成标准——先补上再让它动手）",
        "task_priority": task.priority or "未标",
        "task_depends": "、".join(task.depends_on) or "无",
        "task_status": task.status,
        "requirements": requirements,
        "decisions": decisions,
        "skills": skills,
        "previous_files": previous,
        # 下面两个只为 WorkDraft 记录用，不进提示词正文
        "_requirement_ids": "、".join(item.id for item in trace.requirements),
        "_decision_titles": "；".join(item.title for item in trace.decisions),
        "_skill_names": "、".join(item.meta.name for item in matched),
    }


def draft_work(project: Project, task: fmt.Task, provider: ModelProvider) -> WorkDraft:
    """调一次模型，为这条任务产出交付物草稿。只读项目，不写任何文件。"""
    context = gather_context(project, task)
    messages = [
        Message(role="system", content=render_prompt("work.system.md", context)),
        Message(role="user", content=render_prompt("work.user.md", context)),
    ]
    reply = provider.complete(messages)
    return WorkDraft(
        task_id=task.id,
        text=clean_model_reply(reply),
        source=provider.describe(),
        requirements=tuple(filter(None, context["_requirement_ids"].split("、"))),
        decisions=tuple(filter(None, context["_decision_titles"].split("；"))),
        skills=tuple(filter(None, context["_skill_names"].split("、"))),
    )


def check_draft(draft: WorkDraft) -> list[fmt.Problem]:
    """检查交付物草稿是否达标，返回全部问题（不提前退出）。"""
    where = f"{fmt.EVIDENCE_DIR}/{draft.task_id}"
    text = draft.text.strip()
    if not text:
        return [
            fmt.Problem(
                where,
                "模型返回了空内容",
                "重跑一次；反复为空就检查模型接入（先跑 pm-agent ask 试试）",
            )
        ]

    problems: list[fmt.Problem] = []
    if ECHO_MARKER in text:
        # 回声实现会把提示词原样吐回来，而提示词里恰好含那四个关键词，
        # 不专门拦一下就会被当成"合格交付物"留成证据（FR-037：不静默降级）。
        problems.append(
            fmt.Problem(
                where,
                "拿到的是回声实现的输出，不是模型做的交付物",
                "检查是不是误用了 --provider echo 或 PM_AGENT_MODEL_PROVIDER=echo",
            )
        )
    if len(text) < MIN_LENGTH:
        problems.append(
            fmt.Problem(
                where,
                f"模型只返回了 {len(text)} 个字，不像是交付物",
                "多半是客套话；重跑一次，或把 prompts/work.user.md 的要求写得更硬",
            )
        )
    for section in REQUIRED_SECTIONS:
        if section not in text:
            problems.append(
                fmt.Problem(
                    where,
                    f"交付物里没有交代「{section}」",
                    "FR-053 要求产出说明做法、交付物本身、怎么验证、以及没做什么；"
                    "重跑一次，或把 prompts/work.user.md 的格式要求写得更硬",
                )
            )
    return problems


def evidence_filename(task_id: str, moment: dt.datetime) -> str:
    """证据文件名：``<任务编号>-<时间戳>.md``，与 sessions/ 的命名习惯一致。"""
    return f"{task_id}-{moment.strftime('%Y-%m-%d-%H-%M-%S')}.md"


def parse_deliverables(text: str) -> tuple[Artifact, ...]:
    """从交付物正文里解析出"要落盘的文件"。

    约定的写法（提示词里写死了）：

    ```
    ### 文件：todo.py
    ```python
    ...
    ```
    ```

    标题后面必须紧跟一个代码围栏——**没跟就是格式错**，直接报错而不是猜，
    因为"猜错了"的代价是把内容写进错误的路径。
    """
    fence = "`" * 3
    lines = text.split("\n")
    found: list[Artifact] = []
    index = 0
    while index < len(lines):
        heading = FILE_HEADING_RE.match(lines[index])
        if not heading:
            index += 1
            continue

        raw_path = heading.group("path").strip().strip("`").strip()
        # 标题后面的空行不算内容，跳过
        cursor = index + 1
        while cursor < len(lines) and not lines[cursor].strip():
            cursor += 1
        if cursor >= len(lines) or not lines[cursor].strip().startswith(fence):
            raise FormatError(
                f"「文件：{raw_path}」后面没有代码块，看不出要写什么内容",
                hint="每个文件块写成：`### 文件：相对路径`，紧跟一个三反引号围栏包住内容",
            )
        start = cursor + 1
        end = start
        while end < len(lines) and not lines[end].strip().startswith(fence):
            end += 1
        if end >= len(lines):
            raise FormatError(
                f"「文件：{raw_path}」的代码块没有闭合",
                hint="补上结尾的三反引号；内容要完整闭合",
            )
        found.append(Artifact(path=raw_path, content="\n".join(lines[start:end]).rstrip("\n") + "\n"))
        index = end + 1
    return tuple(found)


def check_artifacts(project: Project, artifacts: tuple[Artifact, ...]) -> list[fmt.Problem]:
    """检查"要落盘的文件"能不能写：路径、保护名单、重复与空内容（不提前退出）。"""
    where = f"{fmt.EVIDENCE_DIR}/{project.meta.name}"
    problems: list[fmt.Problem] = []

    if not artifacts:
        problems.append(
            fmt.Problem(
                where,
                "交付物里没有任何文件块，没东西可写进项目",
                "FR-053 要求产出直接落进项目文件：每个文件写成"
                " `### 文件：相对路径` + 一个代码围栏（见 prompts/work.user.md）",
            )
        )
        return problems

    seen: set[str] = set()
    for item in artifacts:
        path = item.path.replace("\\", "/").strip()
        if not path:
            problems.append(fmt.Problem(where, "有一个文件块没写路径", "补成 `### 文件：相对路径`"))
            continue
        if path.startswith("/") or re.match(r"^[A-Za-z]:", path):
            problems.append(
                fmt.Problem(
                    where,
                    f"「{path}」是绝对路径",
                    "只接受项目目录内的相对路径，例如 `todo.py`、`docs/调研.md`",
                )
            )
            continue
        if ".." in path.split("/"):
            problems.append(
                fmt.Problem(
                    where,
                    f"「{path}」想往项目外面写",
                    "路径里不许出现 `..`；要写得看得到的东西，就在项目里建个文件",
                )
            )
            continue
        if path in PROTECTED_FILES:
            problems.append(
                fmt.Problem(
                    where,
                    f"不许由 work 直接改「{path}」",
                    "这几个文件归各自的命令管：规范用 pm-agent specify、任务用 pm-agent breakdown、"
                    "元信息用 pm-agent init/手工改；要改它们就明说，别让执行任务的命令顺手改",
                )
            )
            continue
        if any(path.startswith(prefix) for prefix in PROTECTED_PREFIXES):
            problems.append(
                fmt.Problem(
                    where,
                    f"不许写进「{path}」",
                    "那是程序自己的状态目录（history/ 是撤回的地基），写进去会毁追溯",
                )
            )
            continue
        if path in seen:
            problems.append(
                fmt.Problem(
                    where,
                    f"「{path}」出现了两次",
                    "同一个文件只该有一个文件块；把两处内容合并掉再重跑",
                )
            )
            continue
        if not item.content.strip():
            problems.append(
                fmt.Problem(where, f"「{path}」的内容是空的", "空文件没有交付价值；补上内容或去掉这个块")
            )
            continue
        seen.add(path)
    return problems


def compose_evidence(
    project: Project,
    task: fmt.Task,
    draft: WorkDraft,
    *,
    moment: dt.datetime,
    files: tuple[str, ...] = (),
) -> str:
    """把草稿组装成证据文件：程序维护的 frontmatter + 模型产出的正文。"""
    meta = {
        "task": task.id,
        "project": project.meta.name,
        "at": moment.strftime("%Y-%m-%d %H:%M"),
        "model": draft.source,
        "requirements": list(draft.requirements),
        "files": list(files),
    }
    return render_markdown(meta, draft.text)


def prepare_work_change(
    project: Project,
    task: fmt.Task,
    draft: WorkDraft,
    *,
    moment: dt.datetime | None = None,
    reason: str = "",
) -> Change:
    """校验交付物，组装成一份"写进项目"的变更（**不落盘**）。

    一次变更里同时包含：**交付物里的各个文件** + **一条记录**。两者同属一个
    :class:`Change`，所以能整体撤回——不会出现"文件退回去了、记录还在"这种半拉子状态。

    不合格就抛错、不产出变更：调用方因此没有任何机会把半成品写进项目。
    """
    problems = check_draft(draft)
    if not problems:
        try:
            artifacts = parse_deliverables(draft.text)
        except FormatError as exc:
            raise FormatError(
                f"交付物的文件块格式不对，没有写入任何文件：{exc.message}",
                hint=exc.hint,
            ) from exc
        problems = check_artifacts(project, artifacts)
    else:
        artifacts = ()

    if problems:
        raise FormatError(
            "模型产出的交付物不合格，没有写入任何文件：\n"
            + fmt.render_problems(problems)
            + f"\n\n模型原文（前 {RAW_EXCERPT} 字）：\n{draft.text[:RAW_EXCERPT]}",
            hint="重跑一次通常就好；反复失败就改 prompts/work.user.md",
        )

    stamp = moment or dt.datetime.now()
    record_path = f"{fmt.EVIDENCE_DIR}/{evidence_filename(task.id, stamp)}"
    wants = [(item.path, item.content) for item in artifacts]
    wants.append(
        (record_path, compose_evidence(project, task, draft, moment=stamp, files=tuple(item.path for item in artifacts)))
    )
    note = reason or f"{task.id} 交付物（{len(artifacts)} 个文件）"
    files_change = prepare_writes(project, wants, reason=note)

    # 产出落进项目了，任务就不该还写着"未开始"——状态要说实话（FR-056）。
    # 只推进到"进行中"：**"完成"仍由使用者确认**（FR-014）。
    # 两条变更并成一条，所以撤回时文件和状态一起退回去。
    if task.status == "未开始":
        status_change = set_task_status(
            project, task.id, "进行中", moment=stamp, reason=f"{task.id} → 进行中"
        )
        return merge((files_change, status_change), reason=note)
    return files_change
