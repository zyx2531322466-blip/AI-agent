"""specify 阶段的测试（T011）。

**这里不联网**：用假 provider 顶替模型。假 provider 能测的正好是我们自己那部分——
提示词组装、输出清理、格式校验、失败时不落盘。
至于"真模型能不能给出合格输出"，那是 tests/test_specify_live.py 的事。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pm_agent.errors import FormatError
from pm_agent.model.base import Message, ModelProvider
from pm_agent.stages.specify import (
    REQUIRED_TOPICS,
    SpecDraft,
    check_draft,
    compose_spec,
    draft_spec,
    prepare_spec_change,
)
from pm_agent.workspace import format as fmt
from pm_agent.workspace.changes import history_entries
from pm_agent.workspace.store import Project, create_project

GOOD_REPLY = """# 演示项目 —— 功能需求规范

## 1. 背景与目标
使用者现在把待办记在纸上，容易丢。目标：把零散待办集中到一处，不再靠记忆。

## 2. 使用者
- 主要使用者：只有使用者本人，单人使用。

## 3. 范围边界
### 3.1 本版本包含
- 记录一条待办，标注是否完成。
### 3.2 本版本明确不做
- 多人协作、账号体系、云端同步。

## 4. 功能需求
- **FR-001** [待澄清] 需要确认：待办要有哪些字段（标题？截止时间？优先级？）

## 5. 成功标准
- **SC-001** 记下一条待办不超过 10 秒。

## 6. 待澄清问题
- [待澄清] 要不要做提醒功能？
- [待澄清] 需不需要按天回顾？
"""


class FakeProvider(ModelProvider):
    """把预设回复当模型输出，并记下收到的消息供断言用。"""

    name = "fake"
    is_remote = False

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.seen: list[Message] = []

    def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        self.seen = list(messages)
        return self.reply


@pytest.fixture
def project(tmp_path: Path) -> Project:
    return create_project(
        tmp_path / "demo",
        name="演示项目",
        goal="把零散待办集中起来，不再靠记忆",
        learning_goals=["学会写规范"],
    ).project


# ---- 提示词组装 --------------------------------------------------------


def test_prompt_carries_project_metadata(project: Project) -> None:
    provider = FakeProvider(GOOD_REPLY)
    draft_spec(project, provider)

    assert [message.role for message in provider.seen] == ["system", "user"]
    user = provider.seen[1].content
    assert project.meta.name in user
    assert project.meta.goal in user
    assert "{{" not in user, "占位符必须全部替换掉"


def test_goal_option_overrides_project_goal(project: Project) -> None:
    provider = FakeProvider(GOOD_REPLY)
    draft_spec(project, provider, goal="一个完全不同的目标")

    user = provider.seen[1].content
    assert "一个完全不同的目标" in user
    assert project.meta.goal not in user


def test_draft_records_which_model_produced_it(project: Project) -> None:
    draft = draft_spec(project, FakeProvider(GOOD_REPLY))
    assert draft.source == "fake"


# ---- 输出清理 ----------------------------------------------------------


def test_draft_strips_outer_code_fence(project: Project) -> None:
    fence = "`" * 3
    provider = FakeProvider(f"{fence}markdown\n{GOOD_REPLY}{fence}")

    draft = draft_spec(project, provider)

    assert draft.text.startswith("# 演示项目")
    assert fence not in draft.text


def test_draft_strips_model_supplied_frontmatter(project: Project) -> None:
    provider = FakeProvider(f"---\nstatus: draft\n---\n\n{GOOD_REPLY}")

    draft = draft_spec(project, provider)

    assert draft.text.startswith("# 演示项目")
    assert "status: draft" not in draft.text


# ---- 校验 --------------------------------------------------------------


def test_good_draft_passes_check() -> None:
    assert check_draft(SpecDraft(text=GOOD_REPLY)) == []


@pytest.mark.parametrize("topic", REQUIRED_TOPICS)
def test_missing_topic_is_reported(topic: str) -> None:
    text = GOOD_REPLY.replace(topic, "×××")
    problems = check_draft(SpecDraft(text=text))

    assert any(topic in problem.message for problem in problems), f"应当报出缺少「{topic}」"


def test_chatty_reply_is_rejected() -> None:
    problems = check_draft(SpecDraft(text="你好！我很乐意帮忙，但需要更多信息。"))

    assert problems
    assert any("不像是规范" in problem.message for problem in problems)


def test_empty_reply_is_rejected() -> None:
    problems = check_draft(SpecDraft(text="   \n  "))
    assert problems and "空内容" in problems[0].message


def test_echo_output_is_rejected() -> None:
    """回声实现会把提示词原样吐回来，而提示词里恰好含那五个关键词——
    不专门拦一下，它就会被当成"合格规范"写进 spec.md。"""
    echoed = (
        "[echo] 这是回声实现，不是真实模型输出。\n"
        "共收到 2 条消息，最后一条用户输入是：\n"
        + GOOD_REPLY.replace("×××", "")
    )
    problems = check_draft(SpecDraft(text=echoed))

    assert any("回声" in problem.message for problem in problems)


# ---- 组装与落盘 --------------------------------------------------------


def test_compose_keeps_existing_frontmatter(project: Project) -> None:
    text = compose_spec(project, SpecDraft(text=GOOD_REPLY))

    assert text.startswith("---"), "原有的 frontmatter 应当保留"
    assert "status: draft" in text
    assert GOOD_REPLY.strip() in text


def test_preparing_a_change_does_not_write(project: Project) -> None:
    before = project.spec_text()
    change = prepare_spec_change(project, SpecDraft(text=GOOD_REPLY))

    assert project.spec_text() == before, "准备阶段不该动文件"
    assert not change.is_noop
    assert fmt.SPEC_FILE in change.render()


def test_failed_draft_writes_nothing(project: Project) -> None:
    """关键：校验不过时不能留下半成品。"""
    before = project.spec_text()

    with pytest.raises(FormatError) as excinfo:
        prepare_spec_change(project, SpecDraft(text="抱歉，我不太确定你想做什么。"))

    assert project.spec_text() == before
    assert history_entries(project) == [], "失败不该留下变更记录"
    assert "模型原文" in str(excinfo.value), "报错要带上原文，人才知道出了什么事"


def test_apply_writes_the_spec(project: Project) -> None:
    project.apply(prepare_spec_change(project, SpecDraft(text=GOOD_REPLY)))

    written = project.read_text(fmt.SPEC_FILE)
    for topic in REQUIRED_TOPICS:
        assert topic in written
    assert written.startswith("---")
