"""CLI 的端到端测试（T002 的完成标准：程序能跑、--help 正常）。

用 Typer 自带的 CliRunner，不真起进程，跑得快。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from pm_agent.cli import app
from pm_agent.model.openai_compat import API_KEY_ENV, PROVIDER_ENV

runner = CliRunner()


def test_help_lists_all_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("version", "init", "show", "check", "ask","stage"):
        assert command in result.stdout


def test_version_prints_number() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "pm-agent" in result.stdout


def test_init_then_check_then_show(tmp_path: Path) -> None:
    target = tmp_path / "项目"
    result = runner.invoke(
        app,
        [
            "init",
            str(target),
            "--name",
            "演示项目",
            "--goal",
            "验证端到端能不能跑通",
            "--learning-goal",
            "学会写规范",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert (target / "project.yaml").is_file()
    assert (target / "sessions").is_dir()

    check = runner.invoke(app, ["check", str(target)])
    assert check.exit_code == 0, check.stdout

    show = runner.invoke(app, ["show", str(target)])
    assert show.exit_code == 0, show.stdout
    assert "演示项目" in show.stdout
    assert "学会写规范" in show.stdout


def test_init_requires_name_and_goal(tmp_path: Path) -> None:
    result = runner.invoke(app, ["init", str(tmp_path / "项目")])
    assert result.exit_code != 0


def test_init_with_no_git(tmp_path: Path) -> None:
    target = tmp_path / "不要版本库"
    result = runner.invoke(
        app,
        ["init", str(target), "--name", "n", "--goal", "g", "--no-git"],
    )
    assert result.exit_code == 0, result.stdout
    assert not (target / ".git").exists()
    assert "跳过" in result.stdout


def test_check_reports_missing_project(tmp_path: Path) -> None:
    result = runner.invoke(app, ["check", str(tmp_path / "还没有")])
    assert result.exit_code == 1
    assert "目录不存在" in result.stdout


def test_check_fix_creates_data_directories(tmp_path: Path) -> None:
    target = tmp_path / "缺失目录的项目"
    target.mkdir()
    (target / "project.yaml").write_text(
        "schema_version: '1'\n"
        "name: 手工项目\n"
        "goal: 验证 --fix\n"
        "created: 2026-09-13\n"
        "status: active\n"
        "learning_goals:\n  - 手工建的项目也要能修\n",
        encoding="utf-8",
    )
    (target / "spec.md").write_text("- **FR-001** 一条需求\n", encoding="utf-8")

    assert runner.invoke(app, ["check", str(target)]).exit_code == 1
    assert runner.invoke(app, ["check", str(target), "--fix"]).exit_code == 0
    assert (target / "sessions").is_dir()


def test_ask_echo_keeps_its_marker() -> None:
    """回声标记不能被 Rich 当成样式标签吃掉（否则破坏 FR-037）。"""
    result = runner.invoke(app, ["ask", "--provider", "echo", "在吗"])
    assert result.exit_code == 0
    assert "[echo]" in result.stdout


def test_ask_without_key_fails_with_actionable_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    monkeypatch.delenv(PROVIDER_ENV, raising=False)
    result = runner.invoke(app, ["ask", "在吗"])
    assert result.exit_code == 1
    assert API_KEY_ENV in result.stdout
    assert "echo" in result.stdout

