"""读写层的测试（T004）。

重点验证 T004 的完成标准：**用文本编辑器手工改一个字段，
程序重新读取时仍然是正确的**——这正是"数据属于使用者"（原则 2）
能不能成立的技术底线。
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from pm_agent.errors import FormatError, WorkspaceError
from pm_agent.workspace import create_project
from pm_agent.workspace import format as fmt
from pm_agent.workspace.store import Project, ensure_git_repo

has_git = shutil.which("git") is not None


@pytest.fixture
def project(tmp_path: Path) -> Project:
    result = create_project(
        tmp_path / "demo",
        name="演示项目",
        goal="验证工作区能不能建起来并被正确读回",
        learning_goals=["学会写规范", "学会拆任务"],
    )
    return result.project


def test_create_project_makes_required_structure(project: Project) -> None:
    assert (project.root / fmt.PROJECT_FILE).is_file()
    assert (project.root / fmt.SPEC_FILE).is_file()
    for name in fmt.DATA_DIRECTORIES:
        assert (project.root / name).is_dir()


def test_created_project_passes_check(project: Project) -> None:
    assert fmt.errors(fmt.check_workspace(project.root)) == []


def test_open_reads_metadata(project: Project) -> None:
    assert project.meta.name == "演示项目"
    assert project.meta.status == "active"
    assert project.meta.learning_goals == ["学会写规范", "学会拆任务"]


def test_created_project_has_creation_date_today(project: Project) -> None:
    import datetime as dt

    assert project.meta.created == dt.date.today().isoformat()


@pytest.mark.skipif(not has_git, reason="这台机器上没有 git")
def test_git_is_initialized_by_default(project: Project) -> None:
    """plan.md §11 的决策：项目工作区默认初始化 git，开箱可追溯。"""
    assert (project.root / ".git").exists()


def test_git_can_be_skipped(tmp_path: Path) -> None:
    result = create_project(tmp_path / "没有版本库", name="n", goal="g", init_git=False)
    assert result.git_status == "skipped"
    assert not (result.project.root / ".git").exists()


@pytest.mark.skipif(not has_git, reason="这台机器上没有 git")
def test_ensure_git_repo_reports_existing(tmp_path: Path) -> None:
    assert ensure_git_repo(tmp_path)[0] == "initialized"
    assert ensure_git_repo(tmp_path)[0] == "existing"


def test_hand_edit_is_read_back(project: Project) -> None:
    """T004 的完成标准：手工改一个字段，程序仍能正确读取。"""
    path = project.root / fmt.PROJECT_FILE
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["status"] = "paused"
    data["learning_goals"] = ["学会写规范", "手工改过这一条"]
    path.write_text(
        yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )

    reopened = Project.open(project.root)
    assert reopened.meta.status == "paused"
    assert reopened.meta.learning_goals[-1] == "手工改过这一条"


def test_create_project_never_overwrites(tmp_path: Path) -> None:
    """已存在的文件必须原样保留（原则 4：不静默覆盖）。"""
    target = tmp_path / "demo"
    target.mkdir()
    spec = target / fmt.SPEC_FILE
    spec.write_text("# 我自己写的规范\n\n- **FR-001** 不能被覆盖\n", encoding="utf-8")

    result = create_project(target, name="演示", goal="验证不覆盖")

    assert spec.read_text(encoding="utf-8").startswith("# 我自己写的规范")
    assert fmt.SPEC_FILE in result.skipped


def test_open_fails_when_spec_missing(project: Project) -> None:
    (project.root / fmt.SPEC_FILE).unlink()
    with pytest.raises(FormatError) as excinfo:
        Project.open(project.root)
    assert "spec.md" in str(excinfo.value)


def test_open_fails_when_yaml_broken(project: Project) -> None:
    (project.root / fmt.PROJECT_FILE).write_text("name: [未闭合\n", encoding="utf-8")
    with pytest.raises(FormatError) as excinfo:
        Project.open(project.root)
    assert "YAML" in str(excinfo.value)


def test_missing_data_directory_is_reported(project: Project) -> None:
    (project.root / "sessions").rmdir()
    problems = fmt.errors(fmt.check_workspace(project.root))
    assert any("sessions" in item.where for item in problems)


def test_path_escape_is_rejected(project: Project) -> None:
    with pytest.raises(WorkspaceError):
        project.path("..", "跑到外面去了.md")


def test_requirement_ids_and_task_summary(project: Project) -> None:
    (project.root / fmt.SPEC_FILE).write_text(
        "# 规范\n\n- **FR-002** 第二条\n- **FR-001** 第一条\n- **FR-002** 重复引用\n",
        encoding="utf-8",
    )
    (project.root / fmt.TASKS_FILE).write_text(
        "- [x] **T001** 做完了\n- [ ] **T002** 还没做\n", encoding="utf-8"
    )

    reopened = Project.open(project.root)
    assert reopened.requirement_ids() == ["FR-001", "FR-002"]
    assert reopened.tasks_summary() == (2, 1)
