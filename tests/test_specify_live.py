"""联网测试：真实调用模型跑一次 specify（T011）。

**默认会被跳过**，因为它要联网、要花钱、输出还不完全确定。想跑就显式打开开关：

    $env:PM_AGENT_RUN_NETWORK_TESTS = "1"
    .\\.venv\\bin\\python.exe -m pytest tests/test_specify_live.py -q -s

MSYS2 上的 Python 可能还需要指定 CA 证书（否则报证书错误）：

    $env:PM_AGENT_CA_BUNDLE = "C:\\msys64\\etc\\pki\\ca-trust\\extracted\\pem\\tls-ca-bundle.pem"

为什么值得留这么一个测试：假 provider 只能证明"我们的管道通"，
证明不了"提示词真能要到合格的输出"——后者只有真模型能回答。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pm_agent.model import get_provider
from pm_agent.model.openai_compat import API_KEY_ENV
from pm_agent.stages.specify import (
    REQUIRED_TOPICS,
    check_draft,
    draft_spec,
    prepare_spec_change,
)
from pm_agent.workspace import format as fmt
from pm_agent.workspace.store import create_project

ENABLE_ENV = "PM_AGENT_RUN_NETWORK_TESTS"

pytestmark = [
    pytest.mark.network,
    pytest.mark.skipif(
        os.environ.get(ENABLE_ENV) != "1",
        reason=f"联网测试默认关闭：设 {ENABLE_ENV}=1 再跑（会真的调用模型并产生费用）",
    ),
    pytest.mark.skipif(
        not os.environ.get(API_KEY_ENV),
        reason=f"没有配置 {API_KEY_ENV}",
    ),
]


def test_live_specify_produces_a_valid_draft(tmp_path: Path) -> None:
    """真实调一次模型：从一句话目标到写进 spec.md 的完整链路。"""
    project = create_project(
        tmp_path / "live",
        name="待办清单",
        goal="做一个只在本地跑的待办清单工具，能记待办、标完成、按天回顾",
        learning_goals=["学会写规范"],
    ).project

    provider = get_provider()  # 默认 DeepSeek
    print(f"\n[联网测试] 模型：{provider.describe()}")

    draft = draft_spec(project, provider)
    print(f"[联网测试] 拿到 {len(draft.text)} 个字的草稿")

    problems = check_draft(draft)
    assert not problems, (
        "模型输出没通过校验：\n"
        + "\n".join(problem.render() for problem in problems)
        + "\n\n原文：\n"
        + draft.text
    )

    project.apply(prepare_spec_change(project, draft, reason="联网测试：生成规范草稿"))

    written = project.read_text(fmt.SPEC_FILE)
    for topic in REQUIRED_TOPICS:
        assert topic in written, f"写进 spec.md 的规范缺少「{topic}」"
    assert written.startswith("---"), "程序维护的 frontmatter 应当保留下来"
    assert "Python" not in written, "提示词要求这一阶段不涉及技术选型"
