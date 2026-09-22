"""写入前预览与撤回的测试（T008）。

完成标准是两句：**任何写入先出预览**、**撤回后文件与写入前完全一致**。
所以这里既有"结构上绕不过预览"的测试，也有逐字节比对的测试——
后者才是真正难满足的那条。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pm_agent.errors import WorkspaceError
from pm_agent.workspace import format as fmt
from pm_agent.workspace.changes import history_entries, read_change_meta
from pm_agent.workspace.store import Project, create_project


@pytest.fixture
def project(tmp_path: Path) -> Project:
    return create_project(tmp_path / "demo", name="演示项目", goal="验证预览与撤回").project


def change_and_apply(project: Project, relative: str, text: str) -> None:
    change = project.prepare_write(relative, text, reason="测试改动")
    project.apply(change)


# ---- 预览 --------------------------------------------------------------


def test_prepare_write_does_not_touch_disk(project: Project) -> None:
    """最关键的一条：准备变更的阶段，磁盘上什么都不能变。"""
    before = sorted(p.relative_to(project.root).as_posix() for p in project.root.rglob("*"))
    change = project.prepare_write(fmt.SPEC_FILE, "新内容\n")
    after = sorted(p.relative_to(project.root).as_posix() for p in project.root.rglob("*"))

    assert before == after, "准备阶段不该产生或改动任何文件"
    assert project.read_text(fmt.SPEC_FILE) != "新内容\n"
    assert change.changed_entries[0].path == fmt.SPEC_FILE


def test_preview_of_new_file_says_new_and_has_no_before(project: Project) -> None:
    relative = "sessions/2026-09-22-22-00-00.md"
    entry = project.prepare_write(relative, "内容\n").entries[0]

    assert entry.kind == "新建"
    assert entry.before_bytes is None
    assert not entry.existed


def test_preview_of_modification_shows_diff_stats(project: Project) -> None:
    original = project.read_text(fmt.SPEC_FILE)
    # original 本身以换行结尾，直接追加就是新增一行
    text = project.prepare_write(fmt.SPEC_FILE, original + "新加一行\n").render()

    assert "修改" in text
    assert "+1" in text
    assert "新加一行" in text, "预览里应当能看到实际改了什么"


def test_noop_change_says_it_will_not_write(project: Project) -> None:
    same = project.read_text(fmt.SPEC_FILE)
    change = project.prepare_write(fmt.SPEC_FILE, same)

    assert change.is_noop
    assert "内容相同" in change.render()


# ---- 落盘 --------------------------------------------------------------


def test_apply_writes_content(project: Project) -> None:
    result = project.apply(project.prepare_write("notes.md", "第一行\n"))

    assert result.written == ("notes.md",)
    assert (project.root / "notes.md").read_bytes() == "第一行\n".encode("utf-8")


def test_apply_leaves_a_readable_history_entry(project: Project) -> None:
    original = project.read_text(fmt.SPEC_FILE)
    result = project.apply(
        project.prepare_write(fmt.SPEC_FILE, original + "补充\n", reason="补充规范")
    )
    assert result.entry_dir is not None

    meta = read_change_meta(result.entry_dir)
    assert meta["reason"] == "补充规范"
    assert meta["files"][0]["path"] == fmt.SPEC_FILE
    assert meta["files"][0]["existed"] is True

    backup = result.entry_dir / meta["files"][0]["backup"]
    assert backup.read_text(encoding="utf-8") == original, "备份要是原文，人能直接打开看"


def test_apply_creates_history_dir_under_history(project: Project) -> None:
    result = project.apply(project.prepare_write("notes.md", "内容\n"))

    assert result.entry_dir is not None
    assert result.entry_dir.parent == project.root / fmt.HISTORY_DIR


def test_noop_apply_writes_nothing_and_leaves_no_history(project: Project) -> None:
    same = project.read_text(fmt.SPEC_FILE)
    result = project.apply(project.prepare_write(fmt.SPEC_FILE, same))

    assert result.entry_dir is None
    assert result.written == ()
    assert history_entries(project) == [], "无变化不该留下历史记录"


# ---- 撤回 --------------------------------------------------------------


def test_undo_restores_previous_content_byte_for_byte(project: Project) -> None:
    """完成标准原文：撤回后文件与写入前完全一致——按字节比，不是"看起来一样"。"""
    target = project.root / "notes.md"
    original = "第一行\r\n第二行\r\n"  # 故意用 CRLF：文本模式会把它改掉
    target.write_bytes(original.encode("utf-8"))

    change_and_apply(project, "notes.md", "改了\n")
    assert target.read_bytes() != original.encode("utf-8")

    project.undo_last()
    assert target.read_bytes() == original.encode("utf-8")


def test_undo_of_new_file_deletes_it(project: Project) -> None:
    """写入前根本不存在时，撤回是删掉它，不是留个空文件。"""
    change_and_apply(project, "notes.md", "新文件\n")
    target = project.root / "notes.md"
    assert target.is_file()

    result = project.undo_last()

    assert not target.exists(), "撤回新建的文件应当把它删掉"
    assert result.removed == ("notes.md",)


def test_undo_without_history_reports_clearly(project: Project) -> None:
    with pytest.raises(WorkspaceError) as excinfo:
        project.undo_last()
    assert "没有可撤回" in str(excinfo.value)


def test_second_undo_walks_back_to_the_earlier_change(project: Project) -> None:
    """撤回一次后再撤一次，应当退到更早那次，而不是重复恢复同一条。"""
    target = project.root / "notes.md"
    target.write_bytes(b"v1\n")

    change_and_apply(project, "notes.md", "v2\n")
    change_and_apply(project, "notes.md", "v3\n")
    assert target.read_bytes() == b"v3\n"

    project.undo_last()
    assert target.read_bytes() == b"v2\n"
    project.undo_last()
    assert target.read_bytes() == b"v1\n"

    with pytest.raises(WorkspaceError):
        project.undo_last()


def test_undone_entry_is_marked_in_meta(project: Project) -> None:
    result = project.apply(project.prepare_write("notes.md", "内容\n"))
    project.undo_last()

    assert result.entry_dir is not None
    assert read_change_meta(result.entry_dir)["undone"], "撤回要在记录里留痕"


# ---- 结构上绕不过预览 ---------------------------------------------------


def test_project_has_no_direct_write_method(project: Project) -> None:
    """T008 之后不该再有"直接写"的入口，否则预览可以被绕过。"""
    assert not hasattr(project, "write_text")
