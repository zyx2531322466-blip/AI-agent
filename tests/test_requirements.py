"""需求条目的测试（T012）。

两条性质最要紧，各有一条测试守着：

- **编号只增不复用**：删掉最大号之后，下一个新条目不能把那个号拿回来；
- **改动是定点的**：改一条需求，其他条目逐字不动。

用户故事层的完成标准是"条目可单独引用与修改；插入新条目不打乱已有 ID"。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pm_agent.errors import WorkspaceError
from pm_agent.workspace import format as fmt
from pm_agent.workspace.files import split_frontmatter
from pm_agent.workspace.requirements import (
    add_requirement,
    next_requirement_id,
    update_requirement,
)
from pm_agent.workspace.store import Project, create_project

SPEC_WITH_ITEMS = """---
status: draft
version: 1
---

# 演示项目 —— 功能需求规范

## 4. 功能需求

### A. 记录

- **FR-001** 能记一条待办。
- **FR-002** 能标注完成。

### B. 回顾

- **FR-003** 能按天回看。
"""


@pytest.fixture
def project(tmp_path: Path) -> Project:
    project = create_project(tmp_path / "demo", name="演示项目", goal="记待办").project
    project.apply(
        project.prepare_write(fmt.SPEC_FILE, SPEC_WITH_ITEMS, reason="铺测试数据")
    )
    return project


# ---- 解析 --------------------------------------------------------------


def test_parse_finds_entries_in_order_with_sections() -> None:
    items = fmt.parse_requirements(SPEC_WITH_ITEMS)

    assert [item.id for item in items] == ["FR-001", "FR-002", "FR-003"]
    assert items[0].text == "能记一条待办。"
    assert items[0].section == "A. 记录"
    assert items[2].section == "B. 回顾"
    assert items[0].line == 12, "行号要能被定点修改用上"


def test_a_freshly_created_project_has_no_requirements(tmp_path: Path) -> None:
    """模板里的示例不能算成真需求——否则新建项目就"已有 1 条需求"，
    而且它会在历史里留下一条"从占位文本变成真需求"的假记录。"""
    fresh = create_project(tmp_path / "fresh", name="新项目", goal="g").project

    assert fresh.requirements() == []
    assert fmt.errors(fmt.check_workspace(fresh.root)) == []


def test_references_in_prose_are_not_entries() -> None:
    """正文里提到编号（"详见 FR-001"）不算需求条目——这是真解析胜过正则统计的地方。"""
    text = SPEC_WITH_ITEMS + "\n> 详见 FR-001 与 FR-002 的说明。\n"

    assert len(fmt.parse_requirements(text)) == 3


def test_duplicate_ids_are_reported() -> None:
    text = SPEC_WITH_ITEMS + "- **FR-002** 又是一条。\n"
    problems = fmt.check_requirements(text)

    assert any("两次" in problem.message for problem in problems)


@pytest.mark.parametrize(
    "bad",
    [
        "- **FR-1** 位数不对",
        "- **FR001** 少了连字符",
        "- **FR-0001** 位数太多",
    ],
)
def test_malformed_entries_are_reported(bad: str) -> None:
    """看起来像条目但编号不合规的行必须报出来，不能静默忽略。"""
    problems = fmt.check_requirements(SPEC_WITH_ITEMS + bad + "\n")

    assert any("编号不合规" in problem.message for problem in problems)


def test_duplicates_do_not_block_opening_the_project(project: Project) -> None:
    """重复编号是 warn 不是 error：项目还能打开，否则使用者连 show 都跑不了。"""
    project.apply(
        project.prepare_write(
            fmt.SPEC_FILE, SPEC_WITH_ITEMS + "- **FR-001** 重复。\n", reason="造重复"
        )
    )

    problems = fmt.check_workspace(project.root)
    assert fmt.errors(problems) == []
    assert any("两次" in problem.message for problem in fmt.warnings(problems))


# ---- 编号分配 ----------------------------------------------------------


def test_next_id_follows_the_highest(project: Project) -> None:
    assert next_requirement_id(project.spec_text()) == "FR-004"


def test_next_id_does_not_reuse_a_deleted_number(project: Project) -> None:
    """核心性质：删掉最大号之后再新增，绝不能把那个号发出去。"""
    project.apply(add_requirement(project, "能导出。"))
    assert project.requirement_ids()[-1] == "FR-004"

    # 手工删掉 FR-004（模拟"这条不要了"）
    kept = [line for line in project.spec_text().split("\n") if "- **FR-004**" not in line]
    project.apply(project.prepare_write(fmt.SPEC_FILE, "\n".join(kept), reason="删掉一条"))

    assert next_requirement_id(project.spec_text()) == "FR-005", "FR-004 不能被复用"


def test_add_writes_the_watermark_into_frontmatter(project: Project) -> None:
    project.apply(add_requirement(project, "能导出。"))

    meta, _, has_frontmatter = split_frontmatter(project.spec_text())
    assert has_frontmatter
    assert meta[fmt.WATERMARK_KEY] == 4


def test_add_appends_after_the_last_requirement(project: Project) -> None:
    project.apply(add_requirement(project, "能导出。"))

    items = project.requirements()
    assert [item.id for item in items] == ["FR-001", "FR-002", "FR-003", "FR-004"]
    assert items[-1].text == "能导出。"
    assert items[-1].section == "B. 回顾", "新条目落在最后一条所在的分组里"


def test_add_works_on_a_spec_without_frontmatter(project: Project) -> None:
    project.apply(
        project.prepare_write(
            fmt.SPEC_FILE, "# 规范\n\n- **FR-001** 一条。\n", reason="无 frontmatter"
        )
    )
    project.apply(add_requirement(project, "两条。"))

    text = project.spec_text()
    assert text.startswith("---"), "没有 frontmatter 时补一个，水位线才有地方放"
    assert [item.id for item in project.requirements()] == ["FR-001", "FR-002"]


# ---- 定点修改 ----------------------------------------------------------


def test_update_rewrites_only_that_line(project: Project) -> None:
    before = project.spec_text().split("\n")
    project.apply(update_requirement(project, "FR-002", "能标注完成，并记下完成时间。"))
    after = project.spec_text().split("\n")

    assert len(before) == len(after)
    changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
    assert len(changed) == 1, "只该动一行"
    assert after[changed[0]] == "- **FR-002** 能标注完成，并记下完成时间。"


def test_update_keeps_other_entries_intact(project: Project) -> None:
    before = {item.id: item.text for item in project.requirements()}
    project.apply(update_requirement(project, "FR-001", "改过的第一条。"))
    after = {item.id: item.text for item in project.requirements()}

    for requirement_id, text in before.items():
        expected = "改过的第一条。" if requirement_id == "FR-001" else text
        assert after[requirement_id] == expected


def test_update_unknown_id_lists_what_exists(project: Project) -> None:
    with pytest.raises(WorkspaceError) as excinfo:
        update_requirement(project, "FR-099", "随便写点什么")

    assert "FR-099" in str(excinfo.value)
    assert "FR-001" in (excinfo.value.hint or ""), "报错时要告诉人有哪些条目"


# ---- 不落盘 ------------------------------------------------------------


def test_preparing_changes_does_not_write(project: Project) -> None:
    before = project.spec_text()
    add_requirement(project, "新东西。")
    update_requirement(project, "FR-001", "改了。")

    assert project.spec_text() == before, "准备阶段不该动文件"


def test_empty_text_is_rejected(project: Project) -> None:
    with pytest.raises(WorkspaceError):
        add_requirement(project, "   ")
    with pytest.raises(WorkspaceError):
        update_requirement(project, "FR-001", "   ")
