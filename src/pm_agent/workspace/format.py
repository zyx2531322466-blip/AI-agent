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

from ..errors import FormatError
from .files import split_frontmatter

SCHEMA_VERSION = "1"
SUPPORTED_SCHEMA_VERSIONS = frozenset({SCHEMA_VERSION})

# 文件名：与 plan.md §4.2 的项目工作区目录结构一一对应
PROJECT_FILE = "project.yaml"
SPEC_FILE = "spec.md"
PLAN_FILE = "plan.md"
TASKS_FILE = "tasks.md"

REQUIRED_FILES = (PROJECT_FILE, SPEC_FILE)
OPTIONAL_FILES = (PLAN_FILE, TASKS_FILE)

#: 交付物与证据的存放目录：AI 执行任务的产出（FR-053）与完成证据（FR-014）都落这里
EVIDENCE_DIR = "evidence"
#: 变更历史目录，由 workspace/changes.py 使用（撤回靠它）
HISTORY_DIR = "history"
#: 能力单元目录：内置的随程序走，项目自己沉淀的放这里
SKILLS_DIR = "skills"
DATA_DIRECTORIES = (
    EVIDENCE_DIR,
    "decisions",
    "sessions",
    "reports",
    SKILLS_DIR,
    HISTORY_DIR,
)

#: 一个能力单元 = 一个目录，里面是 SKILL.md（+ 可选的 reference/）
SKILL_FILE = "SKILL.md"
SKILL_REFERENCE_DIR = "reference"

#: FR-026 的六要素 + FR-050 的 why。**步骤要点不在这里——它就是正文本身。**
SKILL_REQUIRED_FIELDS = (
    "name",
    "description",
    "when_to_use",
    "when_not_to_use",
    "inputs",
    "outputs",
    "why",
)

PROJECT_STATUSES = ("active", "paused", "done")
SESSION_STATUSES = ("ok", "conflict", "aborted")

# 需求条目：**以 ``- **FR-xxx**`` 开头的一行**，后面是条目正文。
# 这是隐式约定，写在这里，别让它只活在解析器的正则里。
REQUIREMENT_LINE_RE = re.compile(r"^- \*\*(?P<req_id>FR-\d{3})\*\*[ \t]*(?P<text>.*)$")
#: 看起来像条目、但编号不合规的行（FR-1、FR001、FR-0001…）。
#: 必须报出来——静默忽略会让使用者看着明明有一条、程序却说没有。
SUSPECT_ENTRY_RE = re.compile(r"^-\s*\*\*FR[^*]*\*\*")
#: 正文标题，用来判断条目归在哪个分组
HEADING_RE = re.compile(r"^(?P<level>#{2,3})[ \t]+(?P<title>\S.*?)[ \t]*$")
#: frontmatter 里的编号水位线：只增不减，防止编号被复用
WATERMARK_KEY = "next_requirement"
#: frontmatter 里记录"已逐条确认的条目编号"（FR-006）
CONFIRMED_KEY = "confirmed"
#: 待澄清标记：条目正文或列表里出现它，就算一处待澄清（FR-004）
CLARIFICATION_MARKER = "[待澄清]"

# 任务勾选框的识别规则；正式解析属于 T018
TASK_LINE_RE = re.compile(
    r"^- \[(?P<mark>[ xX])\](?P<parallel> \[P\])? "
    r"\*\*(?P<task_id>T\d{3})\*\*(?P<rest>.*)$"
)
#: 看起来像任务、但编号不合规的行（T1、T0001…）——报出来，别静默忽略
SUSPECT_TASK_RE = re.compile(r"^- \[[ xX]\]\s*(?:\[P\]\s*)?\*\*T[^*]*\*\*")
#: 行内字段：``**标签**：值``，值到下一个字段或行尾为止
TASK_FIELD_RE = re.compile(
    r"\*\*(?P<label>[^*]+)\*\*：(?P<value>.*?)(?=(?:\*\*[^*]+\*\*：)|$)"
)
#: 任务行开头括号里的引用，例如（US-2 / FR-008）、（— / —）
TASK_REFERENCE_RE = re.compile(r"^（(?P<reference>[^）]*)）")
#: 在引用片段里挑出需求条目编号
FR_ID_RE = re.compile(r"\bFR-\d{3}\b")
#: 在引用片段里挑出成功标准编号——任务也可以直接对着验收标准干活
SC_ID_RE = re.compile(r"\bSC-\d{3}\b")
#: 任务编号
TASK_ID_RE = re.compile(r"\bT\d{3}\b")

#: FR-009 要求每个任务都得有的要素（校验与创建都按它来）
REQUIRED_TASK_FIELDS = ("完成标准", "优先级", "依赖")

#: FR-015 要求的四种任务状态
TASK_STATUSES = ("未开始", "进行中", "阻塞", "完成")

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
    #: 已经处置过的风险（FR-023）：处置过的同类预警不再重复提醒
    acknowledged_risks: list[str] = field(default_factory=list)
    #: 能力单元的采纳记录（FR-028）：每项含 name / outcome / at
    skill_usage: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "schema_version": self.schema_version,
            "name": self.name,
            "goal": self.goal,
            "created": self.created,
            "status": self.status,
            "learning_goals": list(self.learning_goals),
        }
        # 空的不写进文件：project.yaml 是给人看的，没内容就别占一行
        if self.acknowledged_risks:
            data["acknowledged_risks"] = list(self.acknowledged_risks)
        if self.skill_usage:
            data["skill_usage"] = [dict(item) for item in self.skill_usage]
        return data


@dataclass(frozen=True)
class Requirement:
    """一条需求条目——FR-003 说的"规范的最小单元"。

    ``line`` 是它在被解析那段文本里的行号（1 起）。定点修改要用到它，
    所以它是解析结果的一部分，不是装饰。
    """

    id: str
    text: str
    section: str
    line: int


#: Markdown 的注释标记。注释里的内容是**写给读文档的人看的说明**，不是文档内容。
COMMENT_OPEN = "<!--"
COMMENT_CLOSE = "-->"


def blank_comments(text: str) -> str:
    """把 HTML 注释里的字符抹成空格，**行数与行号逐字不变**。

    为什么要有这一步：我们自己的模板里就带着示例条目
    （``<!-- 示例：- **FR-001** 系统 MUST …… -->``）。注释必须整段不算内容，
    否则一份刚 ``init`` 出来的空项目会在 ``show`` 里立刻报"看起来是需求条目，
    但编号不合规"——而那句话正是我们自己写进去的示例。使用者把自己不要的条目
    注释掉也是同一个道理：注释掉就该当它不存在。

    抹成空格而不是删掉，是因为解析结果里的 ``line`` 要用来做行级手术
    （定点改一条需求、把新任务插在某个里程碑下）。行号一旦偏移，
    改的就不是那一行了。
    """
    lines: list[str] = []
    inside = False
    for line in text.split("\n"):
        if not inside and COMMENT_OPEN not in line:
            lines.append(line)
            continue
        chars = list(line)
        index = 0
        while index < len(chars):
            if not inside and line.startswith(COMMENT_OPEN, index):
                inside = True
                for position in range(index, index + len(COMMENT_OPEN)):
                    chars[position] = " "
                index += len(COMMENT_OPEN)
                continue
            if inside:
                if line.startswith(COMMENT_CLOSE, index):
                    inside = False
                    for position in range(index, index + len(COMMENT_CLOSE)):
                        chars[position] = " "
                    index += len(COMMENT_CLOSE)
                    continue
                chars[index] = " "
            index += 1
        lines.append("".join(chars))
    return "\n".join(lines)


def parse_requirements(text: str) -> list[Requirement]:
    """解析出规范里的全部需求条目，按出现顺序。

    只认 ``- **FR-xxx** 内容`` 这种行——正文里提到的编号（"见 FR-014"）
    不算条目。这比早先那句全文正则统计准确：引用不会被误算成需求。
    """
    items: list[Requirement] = []
    section = ""
    for number, raw in enumerate(blank_comments(text).split("\n"), start=1):
        heading = HEADING_RE.match(raw)
        if heading:
            section = heading.group("title").strip()
            continue
        found = REQUIREMENT_LINE_RE.match(raw)
        if found:
            items.append(
                Requirement(
                    id=found.group("req_id"),
                    text=found.group("text").strip(),
                    section=section,
                    line=number,
                )
            )
    return items


def check_requirements(text: str) -> list[Problem]:
    """检查条目本身的问题：编号重复、疑似条目但格式不合规。

    两者都是 ``warn``：它们确实说明规范有问题，但不该让项目打不开——
    否则使用者连 ``show`` 都跑不了，反而看不到问题出在哪。
    """
    problems: list[Problem] = []

    seen: dict[str, int] = {}
    for item in parse_requirements(text):
        if item.id in seen:
            problems.append(
                Problem(
                    SPEC_FILE,
                    f"{item.id} 出现了两次（第 {seen[item.id]} 行和第 {item.line} 行）",
                    "编号是引用锚点，必须唯一；给其中一条换一个新号",
                    level=LEVEL_WARN,
                )
            )
        else:
            seen[item.id] = item.line

    for number, raw in enumerate(blank_comments(text).split("\n"), start=1):
        stripped = raw.strip()
        if REQUIREMENT_LINE_RE.match(raw) or not SUSPECT_ENTRY_RE.match(stripped):
            continue
        problems.append(
            Problem(
                SPEC_FILE,
                f"第 {number} 行看起来是需求条目，但编号不合规：{stripped[:40]}",
                "编号要写成 FR-001 这样三位数字，否则它不会被当成条目",
                level=LEVEL_WARN,
            )
        )
    return problems


@dataclass(frozen=True)
class SkillMeta:
    """能力单元的**元数据**——只有元数据，没有正文（T047 的第一级）。

    会话开始时只需要把它放进上下文：让 Agent 知道"有这么个做法、什么时候用"，
    等真要用的时候再去读正文（第二级）、读引用文件（第三级）。
    """

    name: str
    description: str
    when_to_use: str
    when_not_to_use: str
    inputs: str
    outputs: str
    why: str
    version: str
    #: "内置" 还是 "项目"
    source: str
    #: SKILL.md 所在位置，读正文时用
    path: Path

    def one_line(self) -> str:
        """放进上下文的**一行**。整段正文不该出现在这里。"""
        return f"{self.name}：{self.description}（适用：{self.when_to_use}）"


def parse_skill_meta(
    text: str, *, source: str, path: Path
) -> SkillMeta:
    """解析 SKILL.md 的元数据；缺要素就报错（FR-026）。

    正文（步骤要点）另算：它不能为空，而且至少要有一条列表项——
    "步骤要点"就是这个能力单元正文该有的样子。
    """
    meta, body, has_frontmatter = split_frontmatter(text)
    where = f"{SKILLS_DIR}/{path.name}/{SKILL_FILE}"

    if not has_frontmatter:
        raise FormatError(
            f"{where} 缺少 frontmatter",
            hint="文件开头要有两行 --- 包住的元数据；对照内置能力单元看格式",
        )

    missing = [field for field in SKILL_REQUIRED_FIELDS if not str(meta.get(field) or "").strip()]
    if missing:
        raise FormatError(
            f"{where} 缺要素：{'、'.join(missing)}",
            hint=(
                "FR-026 要求六要素齐全（name / description / when_to_use / "
                "when_not_to_use / inputs / outputs），FR-050 还要求 why"
            ),
        )

    if "- " not in body:
        raise FormatError(
            f"{where} 的正文里没有步骤要点",
            hint="正文至少要写成一条条要点，用「- 」开头",
        )

    return SkillMeta(
        name=str(meta["name"]).strip(),
        description=str(meta["description"]).strip(),
        when_to_use=str(meta["when_to_use"]).strip(),
        when_not_to_use=str(meta["when_not_to_use"]).strip(),
        inputs=str(meta["inputs"]).strip(),
        outputs=str(meta["outputs"]).strip(),
        why=str(meta["why"]).strip(),
        version=str(meta.get("version") or "1").strip(),
        source=source,
        path=path,
    )


@dataclass(frozen=True)
class Clarification:
    """一处待澄清：问题本身 + 它来自哪（条目编号或章节标题）。"""

    text: str
    source: str
    line: int


def parse_clarifications(text: str) -> list[Clarification]:
    """扫描规范里的 ``[待澄清]`` 标记。

    两个来源都算：需求条目正文里的标记，以及"待澄清问题"那一节的列表项。
    只做**读取**：它不生成问题、也不替使用者回答——信息不足时的产出就是问题本身
    （FR-004：不得自行填补）。
    """
    items: list[Clarification] = []
    section = ""
    for number, raw in enumerate(blank_comments(text).split("\n"), start=1):
        heading = HEADING_RE.match(raw)
        if heading:
            section = heading.group("title").strip()
            continue
        if CLARIFICATION_MARKER not in raw:
            continue
        index = raw.find(CLARIFICATION_MARKER)
        # 行内代码里的标记是在**讨论这个约定**，不是在提问题：
        # 例如"统一用 `[待澄清]` 标出"。反引号数量为奇数说明它在代码里。
        if raw.count("`", 0, index) % 2 == 1:
            continue
        body = raw[index + len(CLARIFICATION_MARKER) :].strip()
        body = body.lstrip("*：: -·").strip()
        if not body:
            continue
        found = REQUIREMENT_LINE_RE.match(raw)
        source = found.group("req_id") if found else (section or "（无标题）")
        items.append(Clarification(text=body, source=source, line=number))
    return items


@dataclass(frozen=True)
class Task:
    """一条任务。字段对应 FR-008（追溯）与 FR-009（三要素）。"""

    id: str
    title: str
    done: bool
    #: 可并行标记（``[P]``）：与同里程碑内其他 [P] 任务没有先后依赖
    parallel: bool
    milestone: str
    #: 括号里的原始引用，例如 ``US-2 / FR-008``、``— / —``
    reference: str
    #: 这一行实际写了哪些字段标签——用来区分"写了无"和"根本没写这个字段"
    fields: frozenset[str]
    requirements: tuple[str, ...]
    #: 引用里的成功标准编号（例如 `US-1 / SC-001`）
    criteria: tuple[str, ...]
    standard: str
    priority: str
    depends_on: tuple[str, ...]
    evidence: str
    #: ``**状态**：`` 里写的原值（可能是空串——那就按勾选框推）
    status_field: str
    #: ``**更新**：`` 里记的状态变更时间
    updated: str
    #: ``**结论**：`` 里留的中间结论（FR-020）
    conclusion: str
    #: ``**截止**：`` 里记的预期完成日期；没有就不算超期
    due: str
    line: int

    @property
    def status(self) -> str:
        """四种状态之一。没写 ``**状态**`` 就按勾选框推。"""
        return self.status_field or ("完成" if self.done else "未开始")

    @property
    def has_source(self) -> bool:
        """有没有交代来源。

        两种都算交代了：链接到需求条目，或者明确写了 ``—``
        （基础设施类任务确实不属于任何一条需求）。
        **漏写**引用才叫找不到来源。
        """
        return bool(self.requirements) or bool(self.criteria) or "—" in self.reference


def parse_tasks(text: str) -> list[Task]:
    """解析任务清单。只认 ``- [ ] **T001** …`` 这种行。"""
    tasks: list[Task] = []
    milestone = ""
    for number, raw in enumerate(blank_comments(text).split("\n"), start=1):
        heading = HEADING_RE.match(raw)
        if heading:
            # 只把二级标题当里程碑；### 归它下面管
            if len(heading.group("level")) == 2:
                milestone = heading.group("title").strip()
            continue
        match = TASK_LINE_RE.match(raw)
        if not match:
            continue
        reference, fields, title = _split_task(match.group("rest"))
        tasks.append(
            Task(
                id=match.group("task_id"),
                title=title,
                done=match.group("mark").lower() == "x",
                parallel=bool(match.group("parallel")),
                milestone=milestone,
                reference=reference,
                fields=frozenset(fields),
                requirements=tuple(sorted(set(FR_ID_RE.findall(reference)))),
                criteria=tuple(sorted(set(SC_ID_RE.findall(reference)))),
                standard=fields.get("完成标准", ""),
                priority=fields.get("优先级", ""),
                depends_on=tuple(
                    sorted(set(TASK_ID_RE.findall(fields.get("依赖", ""))))
                ),
                evidence=fields.get("证据", ""),
                status_field=fields.get("状态", ""),
                updated=fields.get("更新", ""),
                conclusion=fields.get("结论", ""),
                due=fields.get("截止", ""),
                line=number,
            )
        )
    return tasks


def check_tasks(text: str) -> list[Problem]:
    """检查任务清单本身：编号重复、编号不合规、依赖悬空。

    都是 ``warn``——有问题但不该让项目打不开（和需求条目一个道理）。
    覆盖缺口（FR-010）不在这里：那要同时看需求和任务，属于 workspace/tasks.py。
    """
    problems: list[Problem] = []
    tasks = parse_tasks(text)
    known = {task.id for task in tasks}

    seen: dict[str, int] = {}
    for task in tasks:
        if task.id in seen:
            problems.append(
                Problem(
                    TASKS_FILE,
                    f"{task.id} 出现了两次（第 {seen[task.id]} 行和第 {task.line} 行）",
                    "任务编号是引用锚点，必须唯一",
                    level=LEVEL_WARN,
                )
            )
        else:
            seen[task.id] = task.line
        for dependency in task.depends_on:
            if dependency not in known:
                problems.append(
                    Problem(
                        TASKS_FILE,
                        f"{task.id} 依赖的 {dependency} 不存在",
                        "改掉这条依赖，或补上被依赖的任务（FR-012：不出现悬空依赖）",
                        level=LEVEL_WARN,
                    )
                )
        if task.status_field and task.status_field not in TASK_STATUSES:
            problems.append(
                Problem(
                    TASKS_FILE,
                    f"{task.id} 的状态取值不合法：{task.status_field!r}",
                    f"从 {'、'.join(TASK_STATUSES)} 中选一个",
                    level=LEVEL_WARN,
                )
            )
        elif task.status == "完成" and not task.done:
            problems.append(
                Problem(
                    TASKS_FILE,
                    f"{task.id} 写着「完成」，但勾选框没打勾",
                    "两处说的不一致；用 pm-agent track 或手工改齐",
                    level=LEVEL_WARN,
                )
            )

    for number, raw in enumerate(blank_comments(text).split("\n"), start=1):
        stripped = raw.strip()
        if TASK_LINE_RE.match(raw) or not SUSPECT_TASK_RE.match(stripped):
            continue
        problems.append(
            Problem(
                TASKS_FILE,
                f"第 {number} 行看起来是任务，但编号不合规：{stripped[:40]}",
                "编号要写成 T001 这样三位数字，否则它不会被当成任务",
                level=LEVEL_WARN,
            )
        )
    return problems


def bigram_overlap(sentence: str, title: str) -> int:
    """两段中文之间共享的字符片段数——不引依赖的最简匹配。

    为什么不用整串包含：中文没有空格，任务是"做回看页"而人说的是"回看页这块卡住了"，
    整串匹配会漏。字符 bigram 重叠够用，而且零依赖（plan §11 定的办法）。

    标题很短（一个字符）时退回整串比较。
    """
    text = title.strip()
    if not text:
        return 0
    if len(text) < 2:
        return 1 if text in sentence else 0
    grams = {text[index : index + 2] for index in range(len(text) - 1)}
    return sum(1 for gram in grams if gram in sentence)


def _split_task(rest: str) -> tuple[str, dict[str, str], str]:
    """拆一行任务：``(引用, {字段: 值}, 动作)``。"""
    text = rest.strip()
    reference = ""
    found = TASK_REFERENCE_RE.match(text)
    if found:
        reference = found.group("reference").strip()
        text = text[found.end() :]

    fields: dict[str, str] = {}
    first_start: int | None = None
    for match in TASK_FIELD_RE.finditer(text):
        if first_start is None:
            first_start = match.start()
        # 字段值到下一个字段为止，末尾那个句号是标点、不是内容。
        # 不剥掉的话 `**优先级**：P1。` 会解析出 "P1。"，按优先级排序就失效了。
        fields[match.group("label").strip()] = match.group("value").strip().rstrip("。")

    title = text[:first_start] if first_start is not None else text
    return reference, fields, title.strip().strip("。．.· ").strip()


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
        acknowledged_risks=[
            str(item).strip() for item in data.get("acknowledged_risks") or []
        ],
        skill_usage=[
            {str(key): str(value) for key, value in dict(item).items()}
            for item in data.get("skill_usage") or []
            if isinstance(item, dict)
        ],
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
            Problem(
                PROJECT_FILE,
                "缺少项目元信息文件",
                "这大概不是一个项目目录；运行 pm-agent init 生成，第一次用就先看 pm-agent guide",
            )
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
        else:
            spec_text = text or ""
            problems.extend(check_requirements(spec_text))
            if not parse_requirements(spec_text):
                problems.append(
                    Problem(
                        SPEC_FILE,
                        "还没有需求条目",
                        "一条需求写一行：`- **FR-001** 系统 MUST ……`，任务才能追溯到需求（FR-003）",
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
        else:
            tasks_text = text or ""
            problems.extend(check_tasks(tasks_text))
            if not parse_tasks(tasks_text):
                problems.append(
                    Problem(
                        TASKS_FILE,
                        "任务清单里还没有任务",
                        "一条任务写一行：`- [ ] **T001** 做什么。**完成标准**：……`",
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
