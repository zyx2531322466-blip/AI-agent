"""演示与试用的测试（T060 ~ T064）。

三条性质最要紧：

- **导出 → 恢复后一致**（逐文件比对字节）；
- **副本独立**：演示怎么折腾都不回流；
- **重置回到初始状态**：不是"看着差不多"，是**逐字节一致**。
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from pm_agent.errors import WorkspaceError
from pm_agent.templates import load as load_template
from pm_agent.workspace import format as fmt
from pm_agent.workspace.handoff import SESSIONS_DIR
from pm_agent.workspace.store import Project, create_project
from pm_agent.workspace.tasks import set_task_status
from pm_agent.workspace.transfer import (
    DEMO_MARKER,
    build_demo,
    copy_for_demo,
    export_project,
    restore_project,
)


def fingerprint(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if ".git" in path.parts or path.is_dir():
            continue
        result[str(path.relative_to(root))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


@pytest.fixture
def project(tmp_path: Path) -> Project:
    return create_project(tmp_path / "真实", name="真实项目", goal="做真的事").project


# ---- T060 导出与恢复 ----------------------------------------------------


def test_export_then_restore_keeps_everything(project: Project, tmp_path: Path) -> None:
    exported = export_project(project, tmp_path / "带走的一份")
    restored = restore_project(exported, tmp_path / "另一台机器")

    assert fingerprint(project.root) == fingerprint(restored.root)
    assert restored.meta.name == project.meta.name


def test_export_refuses_to_overwrite(project: Project, tmp_path: Path) -> None:
    target = tmp_path / "已经有了"
    target.mkdir()
    with pytest.raises(WorkspaceError):
        export_project(project, target)


def test_restore_refuses_something_that_is_not_a_project(tmp_path: Path) -> None:
    source = tmp_path / "随便一个目录"
    source.mkdir()
    with pytest.raises(WorkspaceError):
        restore_project(source, tmp_path / "目标")


# ---- T061 示范项目与重置 ------------------------------------------------


def test_demo_has_something_to_show(tmp_path: Path) -> None:
    demo = build_demo(tmp_path / "示范")

    assert demo.requirements(), "示范项目要有规范"
    assert demo.tasks(), "示范项目要有任务"
    assert (demo.root / SESSIONS_DIR).is_dir()
    assert list((demo.root / SESSIONS_DIR).glob("*.md")), "示范项目要有交接记录，才演示得了 resume"


def test_reset_returns_to_the_initial_state(tmp_path: Path) -> None:
    """重置后**逐字节一致**——不是"看着差不多"。"""
    target = tmp_path / "示范"
    build_demo(target)
    before = fingerprint(target)

    # 试用者折腾一番
    project = Project.open(target)
    project.apply(set_task_status(project, "T002", "完成", evidence="提交 xyz"))
    assert fingerprint(target) != before

    build_demo(target, reset=True)
    assert fingerprint(target) == before


def test_demo_refuses_a_directory_with_content(tmp_path: Path) -> None:
    target = tmp_path / "不是空的"
    target.mkdir()
    (target / "别人的东西.txt").write_text("别动我\n", encoding="utf-8")
    with pytest.raises(WorkspaceError):
        build_demo(target)


def test_reset_refuses_a_directory_that_is_not_a_demo(tmp_path: Path) -> None:
    """`--reset` 只认本工具建的示范项目——别人的目录一个字节都不许动。

    T072 走查踩到的真实事故：`demo --reset` 没给路径，落在工具自己的仓库根目录，
    它真的开始删了（先清掉 `.git/hooks` 与 `.git/logs`，再被权限拦住）。
    """
    target = tmp_path / "别人的项目"
    target.mkdir()
    sentinel = target / "重要文件.txt"
    sentinel.write_text("别动我\n", encoding="utf-8")
    (target / "project.yaml").write_text("name: 真的项目\n", encoding="utf-8")
    nested = target / ".git" / "config"
    nested.parent.mkdir()
    nested.write_text("[core]\n", encoding="utf-8")

    with pytest.raises(WorkspaceError) as excinfo:
        build_demo(target, reset=True)

    assert DEMO_MARKER in excinfo.value.hint
    assert sentinel.read_text(encoding="utf-8") == "别动我\n"
    assert (target / "project.yaml").is_file() and nested.is_file()


def test_demo_marks_itself_so_reset_has_something_to_trust(tmp_path: Path) -> None:
    """标记文件是 `--reset` 的唯一凭据，所以建完必须留下它。"""
    demo = build_demo(tmp_path / "示范")

    marker = demo.root / DEMO_MARKER
    assert marker.is_file(), "没有标记，--reset 下次就会拒绝自己建的项目"
    assert "--reset" in marker.read_text(encoding="utf-8")


def test_reset_reports_what_it_already_deleted(tmp_path: Path, monkeypatch) -> None:
    """删到一半失败时，必须说清"已经删了什么"——半途失败比失败更糟。

    这里把删 `project.yaml` 的动作改成失败，模拟"删除权限不够"（真实事故里
    卡住的是一次 `os.unlink`）。
    """
    target = tmp_path / "示范"
    build_demo(target)
    real_unlink = Path.unlink

    def refuses(self: Path, *args: object, **kwargs: object) -> None:
        if self.name == "project.yaml":
            raise PermissionError(5, "拒绝访问", str(self))
        real_unlink(self, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", refuses)

    with pytest.raises(WorkspaceError) as excinfo:
        build_demo(target, reset=True)

    message = str(excinfo.value.message)
    assert "已经删掉" in message and "project.yaml" in message
    assert target.is_dir(), "失败时不该连目录本身都没了"
    assert (target / "project.yaml").is_file()


# ---- T062 / T063 演示副本与试用残留 -------------------------------------


def test_demo_copy_is_independent(project: Project, tmp_path: Path) -> None:
    """副本与真实项目相互独立：在副本里怎么折腾都不回流（FR-044）。"""
    before = fingerprint(project.root)
    copy = copy_for_demo(project, tmp_path / "演示副本")

    demo = Project.open(copy)
    demo.apply(
        demo.prepare_write(fmt.SPEC_FILE, "# 被试用者改过了\n", reason="试用者动手")
    )

    assert fingerprint(project.root) == before, "真实项目一个字节都不该变"
    assert "被试用者改过了" in demo.spec_text()


def test_trial_leftovers_can_be_discarded_whole(project: Project, tmp_path: Path) -> None:
    """试用留下的东西可以整体丢掉——因为试用只发生在那份独立副本里（FR-045）。"""
    import shutil

    copy = copy_for_demo(project, tmp_path / "试用空间")
    trial = Project.open(copy)
    trial.apply(trial.prepare_write("试用笔记.md", "随便记点\n", reason="试用"))

    shutil.rmtree(copy)

    assert not copy.exists()
    assert project.root.is_dir() and Project.open(project.root).meta.name == "真实项目"


# ---- T064 引导式首次使用 ------------------------------------------------


def test_guide_walks_through_the_whole_flow() -> None:
    """未受训者照着走就能跑完整条链路——所以每一步都得是真命令。"""
    text = load_template("guide.md")

    for command in ("demo", "resume", "stage", "specify", "breakdown", "track", "report"):
        assert command in text, f"引导里缺了 {command}"
    assert "删掉" in text, "要告诉试用者收尾怎么做"


def test_guide_only_names_real_commands() -> None:
    """引导里出现的每条命令都得能敲通。

    T072 走查发现的：原文写成 `pm-agent <命令>`，而仓库里没有这么个可执行文件，
    照着抄一条都跑不起来。所以这里**逐条对账**——引导里提到的命令名，
    必须是 Typer 真注册过的。
    """
    from pm_agent.cli import app

    known = {
        command.name or command.callback.__name__.replace("_", "-")
        for command in app.registered_commands
    }
    named = {
        match.group(1)
        for match in re.finditer(r"pm-agent\s+([^\s`]+)", load_template("guide.md"))
        if not match.group(1).startswith(("-", "<", "`"))
    }

    assert named, "一条命令都没对上，多半是正则失效了"
    assert named <= known, f"引导里写了不存在的命令：{sorted(named - known)}"


def test_guide_shows_how_to_create_a_project() -> None:
    """T072 走查发现的第二件事：要建项目时找不到入口，参数也没解释。"""
    text = load_template("guide.md")

    assert "pm-agent init" in text, "建项目的命令必须出现在引导里"
    assert "pm-agent demo" in text, "只想练手的路子也要给"
    for option in ("--name", "--goal", "--learning-goal"):
        assert option in text, f"没解释 {option} 是干什么的"
    assert "--help" in text, "要告诉使用者参数去哪查"
