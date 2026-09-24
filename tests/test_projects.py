"""多项目并行的测试（T055 ~ T058）。

这一段的重点不是"能管理多个项目"，而是**它们之间不串味**：

- 切换项目不残留上一个项目的上下文（FR-038）；
- 一个项目的数据不会出现在另一个项目里（FR-039）；
- 总览是**只读扫描**，不产生任何跨项目写入（FR-040）；
- 共享能力单元不改变来源项目的归属与使用历史（FR-041）。
"""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path

import pytest

from pm_agent.errors import WorkspaceError
from pm_agent.harness.projects import find_projects, overview
from pm_agent.workspace import format as fmt
from pm_agent.workspace.skills import (
    get_skill,
    load_skill,
    record_usage,
    share_skill,
    usage_summary,
)
from pm_agent.workspace.store import Project, create_project

NOW = dt.datetime(2026, 9, 23, 17, 0, 0)


def make_project(root: Path, name: str, task_text: str) -> Project:
    project = create_project(root, name=name, goal=f"{name} 的目标").project
    project.apply(
        project.prepare_write(
            fmt.SPEC_FILE,
            f"# {name} 的规范\n\n- **FR-001** {name} 的需求。\n",
            reason="铺规范",
        )
    )
    project.apply(
        project.prepare_write(
            fmt.TASKS_FILE,
            f"# {name} 的任务\n\n## M1 · 记录\n\n"
            f"- [ ] **T001**（— / FR-001）{task_text}。**完成标准**：能跑。"
            f"**优先级**：P1。**依赖**：无。\n",
            reason="铺任务",
        )
    )
    return project


@pytest.fixture
def two_projects(tmp_path: Path) -> tuple[Project, Project]:
    shelf = tmp_path / "项目架"
    return (
        make_project(shelf / "甲", "甲项目", "甲项目独有的任务"),
        make_project(shelf / "乙", "乙项目", "乙项目独有的任务"),
    )


def tree_fingerprint(root: Path) -> dict[str, str]:
    """把整棵目录树的内容做成指纹，用来证明"扫描没有写东西"。"""
    fingerprint: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if ".git" in path.parts or path.is_dir():
            continue
        fingerprint[str(path.relative_to(root))] = hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
    return fingerprint


# ---- T055 多项目与切换 --------------------------------------------------


def test_find_projects_scans_one_level(two_projects: tuple[Project, Project]) -> None:
    shelf = two_projects[0].root.parent
    found = find_projects(shelf)

    assert {path.name for path in found} == {"甲", "乙"}


def test_switching_projects_leaves_no_leftovers(
    two_projects: tuple[Project, Project],
) -> None:
    """先看甲、再看乙：乙的输出里不该出现甲的任何东西。"""
    jia, yi = two_projects
    assert "甲项目独有的任务" in jia.read_text(fmt.TASKS_FILE)

    reopened = Project.open(yi.root)
    assert "甲项目独有的任务" not in reopened.read_text(fmt.TASKS_FILE)
    assert "甲项目" not in reopened.spec_text()
    assert reopened.meta.name == "乙项目"


def test_each_command_opens_only_its_own_project(
    two_projects: tuple[Project, Project],
) -> None:
    jia, yi = two_projects
    assert jia.requirements()[0].text == "甲项目 的需求。"
    assert yi.requirements()[0].text == "乙项目 的需求。"


# ---- T056 数据隔离 ------------------------------------------------------


def test_cross_project_paths_are_refused(
    two_projects: tuple[Project, Project],
) -> None:
    """一个项目不可能读到另一个项目的文件——路径守卫直接拒绝。"""
    jia, yi = two_projects
    with pytest.raises(WorkspaceError):
        jia.path("..", "乙", "spec.md")
    with pytest.raises(WorkspaceError):
        jia.read_text("../乙/spec.md")


def test_shared_skill_does_not_touch_the_source(
    two_projects: tuple[Project, Project],
) -> None:
    """FR-041：复制到别的项目，来源的归属与使用历史一动不动。"""
    jia, yi = two_projects
    jia.apply(record_usage(jia, "requirement-review", "accepted", moment=NOW))
    source_usage = dict(usage_summary(jia)["requirement-review"])
    before = tree_fingerprint(jia.root)

    yi.apply(share_skill(jia, yi, "requirement-review"))

    assert get_skill(yi, "requirement-review").source == "项目"
    assert get_skill(jia, "requirement-review").source == "内置"
    assert usage_summary(jia)["requirement-review"] == source_usage
    assert "requirement-review" not in usage_summary(yi), "副本的使用历史是它自己的"
    assert tree_fingerprint(jia.root) == before, "来源项目一个字节都不该被改动"


def test_shared_skill_is_editable_on_the_target_only(
    two_projects: tuple[Project, Project],
) -> None:
    jia, yi = two_projects
    yi.apply(share_skill(jia, yi, "requirement-review"))
    assert "逐条评审" in load_skill(yi, "requirement-review")
    assert "逐条评审" in load_skill(jia, "requirement-review"), "两边各是各的"


def test_sharing_into_a_name_that_exists_is_refused(
    two_projects: tuple[Project, Project],
) -> None:
    jia, yi = two_projects
    yi.apply(share_skill(jia, yi, "requirement-review"))
    with pytest.raises(WorkspaceError):
        share_skill(jia, yi, "requirement-review")


def test_shared_skill_can_be_renamed(
    two_projects: tuple[Project, Project],
) -> None:
    jia, yi = two_projects
    yi.apply(share_skill(jia, yi, "requirement-review", new_name="我们的需求评审"))

    meta = get_skill(yi, "我们的需求评审")
    assert meta.source == "项目"
    assert meta.name == "我们的需求评审"
    # 正文里的一级标题是**内容**，改名不改它——名字是标识符，标题是文档自己的说法
    assert "逐条评审规范" in load_skill(yi, "我们的需求评审")


# ---- T057 跨项目总览 ----------------------------------------------------


def test_overview_lists_both_projects(two_projects: tuple[Project, Project]) -> None:
    shelf = two_projects[0].root.parent
    items = overview(shelf, now=NOW)

    assert {item.name for item in items} == {"甲项目", "乙项目"}
    assert all(item.counts["未开始"] == 1 for item in items)
    jia = next(item for item in items if item.name == "甲项目")
    assert "甲项目" in jia.one_line() and "还没有交接记录" in jia.one_line()


def test_overview_is_read_only(two_projects: tuple[Project, Project]) -> None:
    """FR-040：只读扫描——扫完两个项目的文件一个字节都不该变。"""
    jia, yi = two_projects
    before = (tree_fingerprint(jia.root), tree_fingerprint(yi.root))

    overview(two_projects[0].root.parent, now=NOW)

    assert (tree_fingerprint(jia.root), tree_fingerprint(yi.root)) == before
