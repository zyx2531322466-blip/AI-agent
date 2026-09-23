"""specify 阶段：把一句话目标整理成结构化规范（对应 tasks.md 的 T011）。

这个阶段**是什么**写在 stages.yaml 的 specify 条目里（给人看的说明），
这里负责**怎么做**。四条设计约束：

1. **只产出数据**：不打印、不询问、不写文件——预览与确认归 CLI
   （T006 定下的规矩：副作用留在最外层）。
2. **落盘必须经过 Change**：写 spec.md 走 Project.prepare_write / apply，
   所以"先出预览"是白拿的（T008）。
3. **不信模型输出**：先校验再落盘；不合格就报错并把原文交回给人看，
   而不是把半成品写进规范（FR-037 / FR-002）。
4. **规则与数据分开**：提示词拆成 system（规则）与 user（数据）两份，
   理由见 prompts/__init__.py。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import FormatError
from ..model import Message, ModelProvider
from ..model.echo import ECHO_MARKER
from ..prompts import render as render_prompt
from ..workspace import format as fmt
from ..workspace.changes import Change
from ..workspace.files import render_markdown, split_frontmatter
from ..workspace.store import Project

# FR-002 要求规范至少包含的五项。校验按关键词判断——模型可以用自己的措辞
# 写标题，但这五个词只要有一个完全没出现，就说明它漏了东西。
REQUIRED_TOPICS: tuple[str, ...] = ("目标", "使用者", "范围", "成功标准", "待澄清")

# 太短的回复多半不是规范，而是聊天话术（例如"抱歉，我不太确定"）
MIN_LENGTH = 200

# 校验失败时，错误信息里带上多少字的模型原文，便于人判断出了什么事
RAW_EXCERPT = 300


@dataclass(frozen=True)
class SpecDraft:
    """模型产出的一份规范草稿（尚未落盘）。"""

    text: str
    # 产出它的模型实现说明，用于预览与追溯（例如 "DeepSeek：deepseek-chat…"）
    source: str = ""


def draft_spec(
    project: Project, provider: ModelProvider, *, goal: str | None = None
) -> SpecDraft:
    """调一次模型，产出一份规范草稿。只读项目，不写文件。"""
    context = {
        "name": project.meta.name,
        "goal": (goal or project.meta.goal).strip(),
        "learning_goals": "；".join(project.meta.learning_goals) or "（未填写）",
        "created": project.meta.created,
    }
    messages = [
        Message(role="system", content=render_prompt("specify.system.md", context)),
        Message(role="user", content=render_prompt("specify.user.md", context)),
    ]

    reply = provider.complete(messages)
    return SpecDraft(text=_clean(reply), source=provider.describe())


def check_draft(draft: SpecDraft) -> list[fmt.Problem]:
    """检查草稿是否达标，返回全部问题（不提前退出）。"""
    where = fmt.SPEC_FILE
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
        # 回声实现会把提示词原样吐回来，而提示词里恰好含那五个关键词，
        # 不专门拦一下就会被当成"合格规范"写进 spec.md（FR-037：不静默降级）。
        problems.append(
            fmt.Problem(
                where,
                "拿到的是回声实现的输出，不是模型产出的规范",
                "检查是不是误用了 --provider echo 或 PM_AGENT_MODEL_PROVIDER=echo",
            )
        )
    if len(text) < MIN_LENGTH:
        problems.append(
            fmt.Problem(
                where,
                f"模型只返回了 {len(text)} 个字，不像是规范",
                "多半是聊天话术；重跑一次，或改 prompts/specify.user.md",
            )
        )
    for topic in REQUIRED_TOPICS:
        if topic not in text:
            problems.append(
                fmt.Problem(
                    where,
                    f"规范里没有出现「{topic}」",
                    "FR-002 要求包含这一项；重跑一次，或把 prompts/specify.user.md 的要求写得更硬",
                )
            )
    return problems


def compose_spec(project: Project, draft: SpecDraft) -> str:
    """把草稿组装成最终的 spec.md 文本。

    **保留原有的 frontmatter**：status / version 这类元数据归程序维护，
    正文归模型产出，两者别互相覆盖。
    """
    meta, _, has_frontmatter = split_frontmatter(project.spec_text())
    return render_markdown(meta if has_frontmatter else None, draft.text)


def prepare_spec_change(
    project: Project, draft: SpecDraft, *, reason: str = "生成规范草稿"
) -> Change:
    """校验草稿并组装成一份待确认的变更。

    不合格就抛错、**不产出变更**——调用方因此没有任何机会把半成品写进去。
    这比"记得先校验"可靠：写不进去，是因为压根没有东西可写。
    """
    problems = check_draft(draft)
    if problems:
        raise FormatError(
            "模型产出的规范不合格，没有写入任何文件：\n"
            + fmt.render_problems(problems)
            + f"\n\n模型原文（前 {RAW_EXCERPT} 字）：\n{draft.text[:RAW_EXCERPT]}",
            hint="重跑一次通常就好；反复失败就改 prompts/specify.user.md",
        )
    return project.prepare_write(
        fmt.SPEC_FILE, compose_spec(project, draft), reason=reason
    )


def _clean(reply: str) -> str:
    """把模型回复清理成干净的正文。

    模型常干两件多余的事：自己加上 frontmatter、把整篇包在代码围栏里。
    两者混进 spec.md 都会让人看到不该有的东西，先剥掉。
    """
    _, body, _ = split_frontmatter(reply)
    return _strip_code_fence(body).strip("\n") + "\n"


def _strip_code_fence(text: str) -> str:
    """去掉最外层的一对代码围栏（如果有）。"""
    fence = "`" * 3
    stripped = text.strip()
    if not (stripped.startswith(fence) and stripped.endswith(fence)):
        return text
    first_newline = stripped.find("\n")
    if first_newline == -1:
        return text
    return stripped[first_newline + 1 : -len(fence)]
