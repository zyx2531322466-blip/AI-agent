"""CLI 的端到端测试（T002 的完成标准：程序能跑、--help 正常）。

用 Typer 自带的 CliRunner，不真起进程，跑得快。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pm_agent.cli import app
from pm_agent.model.openai_compat import API_KEY_ENV, PROVIDER_ENV
from pm_agent.workspace.store import Project

runner = CliRunner()


def test_help_lists_all_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in (
        "version",
        "init",
        "show",
        "check",
        "ask",
        "stage",
        "specify",
        "requirements",
        "history",
        "undo",
        "questions",
        "confirm",
        "review",
        "tasks",
        "breakdown",
    ):
        assert command in result.stdout


def test_version_prints_number() -> None:
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "pm-agent" in result.stdout


# ---- 文档里的命令必须真能敲（T072 走查的产物） -------------------------------
#
# 走查时踩到三次同一类错：文档写了一条敲不通的命令。
#   * `guide` 里写 `pm-agent demo`，但仓库根目录没有 `pm-agent` 这个文件；
#   * README 同一个写法，一整段都敲不通；
#   * README 写 `pm-agent review --path X`，而 `review` 的项目目录是**位置参数**，
#     `--path` 直接是 "No such option"。
# 靠人眼盯不住，所以这里拿 Typer 自己注册的命令与参数**逐条对账**。

#: 要一起对账的文档（都是给人照着敲的）
GUIDED_DOCS = ("README.md", "演示脚本.md", "简历材料.md", "使用指南.md")


def _command_names() -> set[str]:
    return {
        command.name or command.callback.__name__.replace("_", "-")
        for command in app.registered_commands
    }


def _accepted_flags(command: str) -> set[str]:
    """拿该命令的 `--help` 当账本——它就是给使用者看的那份参数说明。"""
    result = runner.invoke(app, [command, "--help"])
    assert result.exit_code == 0, f"{command} --help 都跑不起来"
    return set(re.findall(r"--[a-z][a-z-]*", result.stdout))


@pytest.mark.parametrize("doc", GUIDED_DOCS)
def test_documented_commands_are_real(doc: str) -> None:
    root = Path(__file__).resolve().parents[1]
    text = (root / doc).read_text(encoding="utf-8")
    known = _command_names()

    assert ".\\pm-agent" not in text, (
        f"{doc} 里写了 `.\\pm-agent`：仓库根目录没有这个文件，"
        "要么写全路径 `.\\\\.venv\\\\bin\\\\pm-agent.exe`，要么用 `pm-agent`"
    )

    seen = 0
    for number, line in enumerate(text.split("\n"), start=1):
        stripped = line.strip()
        # 文档里两种写法都算：直接敲 `pm-agent …`，或者先定义 $pm 再 `& $pm …`
        parts = stripped.split()
        if stripped.startswith("pm-agent "):
            command = parts[1]
        elif stripped.startswith("& $pm ") and len(parts) > 2:
            command = parts[2]
        else:
            continue
        where = f"{doc} 第 {number} 行"
        assert command in known, f"{where}：没有 {command} 这个命令"
        accepted: set[str] | None = None
        for token in parts[2:]:
            if not token.startswith("--"):
                continue
            flag = token.split("=", 1)[0]
            accepted = _accepted_flags(command) if accepted is None else accepted
            assert flag in accepted, (
                f"{where}：{command} 不接受 {flag}"
                f"（它接受：{'、'.join(sorted(accepted))}）"
            )
        seen += 1
    assert seen, f"{doc} 里一条命令都没扫到，多半是格式变了"


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


def test_history_on_fresh_project_says_empty(tmp_path: Path) -> None:
    target = tmp_path / "新的"
    runner.invoke(app, ["init", str(target), "--name", "n", "--goal", "g", "--no-git"])

    result = runner.invoke(app, ["history", str(target)])
    assert result.exit_code == 0, result.stdout
    assert "还没有任何变更记录" in result.stdout


def test_history_and_undo_commands(tmp_path: Path) -> None:
    target = tmp_path / "项目"
    runner.invoke(app, ["init", str(target), "--name", "n", "--goal", "g", "--no-git"])

    # 制造一次变更（写一个新文件）
    project = Project.open(target)
    project.apply(project.prepare_write("notes.md", "内容\n", reason="测试变更"))

    listed = runner.invoke(app, ["history", str(target)])
    assert listed.exit_code == 0, listed.stdout
    assert "测试变更" in listed.stdout

    undone = runner.invoke(app, ["undo", str(target)])
    assert undone.exit_code == 0, undone.stdout
    assert "notes.md" in undone.stdout
    assert not (target / "notes.md").exists(), "撤回新建的文件应当把它删掉"

    after = runner.invoke(app, ["history", str(target)])
    assert "已撤回" in after.stdout


def test_specify_with_echo_fails_and_writes_nothing(tmp_path: Path) -> None:
    """回声实现的输出不能被当成规范写进去（离线可跑的失败路径）。"""
    target = tmp_path / "规范项目"
    runner.invoke(app, ["init", str(target), "--name", "n", "--goal", "g", "--no-git"])
    before = (target / "spec.md").read_bytes()

    result = runner.invoke(app, ["specify", str(target), "--provider", "echo", "--yes"])

    assert result.exit_code == 1
    assert "回声" in result.stdout
    assert (target / "spec.md").read_bytes() == before, "失败时不能留下半成品"


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
