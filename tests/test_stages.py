"""阶段框架的测试（T006）。

这一层只干一件事：把 stages.yaml 变成人能读的三行。
所以测试只关心两样东西——**数据能不能读出来**、**渲染出来是不是人话**。
不测模型、不测文件写入，那些不属于这一层。
"""

from __future__ import annotations

import pytest

from pm_agent.errors import PMAgentError
from pm_agent.stages import announce, get_stage, load_stages

# 四个阶段的 key，写死在这里是故意的：改名字必须有人先改测试。
EXPECTED_KEYS = {"specify", "plan", "tasks", "track"}


def test_keys_are_the_four_stages_we_expect() -> None:
    """key 改名必须被测试拦住——比如有人把 tasks 写回 task。"""
    assert set(load_stages()) == EXPECTED_KEYS


def test_all_stages_have_four_non_empty_fields() -> None:
    """数据完整性：每个阶段的四个字段都不能为空。"""
    for key, stage in load_stages().items():
        for field in ("title", "purpose", "inputs", "outputs"):
            value = getattr(stage, field)
            assert isinstance(value, str) and value.strip(), f"{key}.{field} 是空的"


def test_announce_returns_at_least_three_lines() -> None:
    """目的 / 输入 / 预期产出，至少三行。"""
    for key in EXPECTED_KEYS:
        text = announce(key)
        lines = [line for line in text.splitlines() if line.strip()]
        assert len(lines) >= 3, f"{key} 的输出不足三行：{text!r}"


def test_announce_content_really_comes_from_the_file() -> None:
    """输出里要出现 YAML 里的原文——否则说明内容被硬编码进了代码。"""
    for key in EXPECTED_KEYS:
        stage = get_stage(key)
        text = announce(key)
        assert stage.title in text
        assert stage.purpose in text


def test_unknown_stage_raises_with_hint() -> None:
    """未知 key 要报错，而且 hint 里得告诉人有哪些可选。"""
    with pytest.raises(PMAgentError) as excinfo:
        get_stage("没有这个阶段")
    hint = excinfo.value.hint or ""
    for key in EXPECTED_KEYS:
        assert key in hint, f"hint 里应该列出可选 key：{hint!r}"


def test_announce_does_not_print(capsys: pytest.CaptureFixture[str]) -> None:
    """announce 只返回文本，不打印——打印归 CLI 管。"""
    announce("specify")
    assert capsys.readouterr().out == ""