"""规范评审的测试（T013 ~ T016）。

- T013：待澄清的检测（只读取已有标记，不生成、不替人回答）
- T014：某条需求的"何时变、为何变"——数据来自 T008 留下的 history/
- T015：逐条确认，未确认的能被列出来
- T016：评审稿导出，不依赖本工具
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from pm_agent.cli import app
from pm_agent.errors import WorkspaceError
from pm_agent.workspace import format as fmt
from pm_agent.workspace.requirements import requirement_history, update_requirement
from pm_agent.workspace.review import (
    build_review_document,
    confirm_requirement,
    export_review,
    parse_confirmed,
    pick_clarification,
    resolve_clarification,
    unconfirmed_requirements,
)
from pm_agent.workspace.store import Project, create_project

SPEC_WITH_ITEMS = """---
status: draft
version: 1
---

# 演示项目 —— 功能需求规范

## 4. 功能需求

### A. 记录

- **FR-001** 能记一条待办。[待澄清] 待办要有哪些字段？
- **FR-002** 能标注完成。

## 6. 待澄清问题

- [待澄清] 要不要做提醒功能？
"""

runner = CliRunner()


@pytest.fixture
def project(tmp_path: Path) -> Project:
    project = create_project(tmp_path / "demo", name="演示项目", goal="记待办").project
    project.apply(
        project.prepare_write(fmt.SPEC_FILE, SPEC_WITH_ITEMS, reason="铺测试数据")
    )
    return project


# ---- T084 把结论回填进规范（FR-054）------------------------------------- #


def test_answer_fills_a_question_back_into_the_requirement(project: Project) -> None:
    """条目里的待澄清：标记去掉、**问题原样保留**、后面记上结论。"""
    change, resolved = resolve_clarification(
        project, answer="字段含标题与是否完成", target="FR-001"
    )
    project.apply(change)

    line = project.spec_text().split("\n")[resolved.line - 1]
    assert "[待澄清]" not in line
    assert "待办要有哪些字段？" in line, "当初问的是什么要留着"
    assert "**结论**：字段含标题与是否完成" in line


def test_answer_fills_a_question_in_the_questions_section(project: Project) -> None:
    """问题清单里的待澄清：同样去标记、留问题、追加结论。"""
    change, resolved = resolve_clarification(
        project, answer="不做，v1 范围外", target="待澄清问题"
    )
    project.apply(change)

    line = project.spec_text().split("\n")[resolved.line - 1]
    assert line.startswith("- 要不要做提醒功能？"), line
    assert "[待澄清]" not in line
    assert "**结论**：不做，v1 范围外" in line


def test_answering_removes_it_from_the_open_list(project: Project) -> None:
    """回填后这一处不再算未决——这正是这条命令存在的理由。"""
    before = fmt.parse_clarifications(project.spec_text())
    assert len(before) == 2

    change, _ = resolve_clarification(project, answer="字段含标题与是否完成", target="1")
    project.apply(change)

    after = fmt.parse_clarifications(project.spec_text())
    assert [item.text for item in after] == ["要不要做提醒功能？"]


def test_other_lines_are_untouched(project: Project) -> None:
    """行级手术：只改那一行，其余逐字不动。"""
    before = project.spec_text().split("\n")

    change, resolved = resolve_clarification(project, answer="字段含标题与是否完成", target="FR-001")
    project.apply(change)

    after = project.spec_text().split("\n")
    assert len(before) == len(after)
    assert [
        (index, line)
        for index, line in enumerate(before, start=1)
        if index != resolved.line
    ] == [
        (index, line)
        for index, line in enumerate(after, start=1)
        if index != resolved.line
    ]


def test_changing_a_confirmed_requirement_invalidates_its_confirmation(
    project: Project,
) -> None:
    """内容变了，之前那次"看过了、可以照它做"就失效——同一次变更里摘掉它。"""
    project.apply(confirm_requirement(project, "FR-001"))
    assert parse_confirmed(project.spec_text()) == ["FR-001"]

    change, resolved = resolve_clarification(project, answer="字段含标题与是否完成", target="FR-001")
    project.apply(change)

    assert resolved.unconfirmed == "FR-001"
    assert parse_confirmed(project.spec_text()) == []


def test_answering_is_undoable(project: Project) -> None:
    """回填也走"预览 → 确认 → 可撤回"（FR-034 / FR-035）。"""
    before = project.spec_text()

    change, _ = resolve_clarification(project, answer="字段含标题与是否完成", target="FR-001")
    project.apply(change)
    assert project.spec_text() != before

    project.undo_last()
    assert project.spec_text() == before
    assert len(fmt.parse_clarifications(project.spec_text())) == 2


# ---- T085 定位：序号 / 来源 / 多解与无解 -------------------------------- #


def test_pick_by_index_and_by_source(project: Project) -> None:
    items = fmt.parse_clarifications(project.spec_text())

    assert pick_clarification(items, "1").source == "FR-001"
    assert pick_clarification(items, "FR-001").text == "待办要有哪些字段？"
    assert pick_clarification(items, "待澄清问题").text == "要不要做提醒功能？"


def test_pick_without_target_needs_exactly_one(project: Project) -> None:
    items = fmt.parse_clarifications(project.spec_text())

    with pytest.raises(WorkspaceError) as excinfo:
        pick_clarification(items, None)
    assert "得说清回答的是哪一处" in excinfo.value.message

    assert pick_clarification(items[:1], None).source == "FR-001"


def test_pick_reports_unknown_target_and_bad_index(project: Project) -> None:
    items = fmt.parse_clarifications(project.spec_text())

    with pytest.raises(WorkspaceError):
        pick_clarification(items, "FR-999")
    with pytest.raises(WorkspaceError) as excinfo:
        pick_clarification(items, "9")
    assert "没有第 9 处" in excinfo.value.message


def test_empty_answer_is_refused(project: Project) -> None:
    with pytest.raises(WorkspaceError):
        resolve_clarification(project, answer="   ", target="FR-001")


def test_stale_wording_is_flagged(project: Project) -> None:
    """回填后原话里还留着"还没定"这类字眼，就提示一句。"""
    project.apply(
        project.prepare_write(
            fmt.SPEC_FILE,
            SPEC_WITH_ITEMS.replace(
                "能记一条待办。[待澄清] 待办要有哪些字段？",
                "标题长度上限还没定。[待澄清] 最长多少字？",
            ),
            reason='造一句"还没定"',
        )
    )
    project = Project.open(project.root)

    _, resolved = resolve_clarification(project, answer="80 字", target="FR-001")

    assert "还没定" in resolved.stale


def test_cli_questions_then_clarify(tmp_path: Path) -> None:
    """端到端：questions 里带序号 → clarify 按序号回答 → 未决清单少一条。"""
    target = tmp_path / "demo"
    created = create_project(target, name="演示项目", goal="记待办").project
    created.apply(created.prepare_write(fmt.SPEC_FILE, SPEC_WITH_ITEMS, reason="铺测试数据"))

    listed = runner.invoke(app, ["questions", str(target)])
    assert listed.exit_code == 0
    assert "序号" in listed.stdout and "FR-001" in listed.stdout

    answered = runner.invoke(
        app,
        ["clarify", "字段含标题与是否完成", "--for", "FR-001", "--path", str(target), "--yes"],
    )
    assert answered.exit_code == 0, answered.stdout
    assert "已回填" in answered.stdout

    left = runner.invoke(app, ["questions", str(target)])
    assert "要不要做提醒功能？" in left.stdout
    assert "待办要有哪些字段" not in left.stdout


def test_cli_clarify_can_be_cancelled(tmp_path: Path) -> None:
    target = tmp_path / "demo"
    created = create_project(target, name="演示项目", goal="记待办").project
    created.apply(created.prepare_write(fmt.SPEC_FILE, SPEC_WITH_ITEMS, reason="铺测试数据"))
    before = (target / fmt.SPEC_FILE).read_text(encoding="utf-8")

    result = runner.invoke(
        app, ["clarify", "字段含标题与是否完成", "--for", "FR-001", "--path", str(target)],
        input="n\n",
    )

    assert "已取消" in result.stdout
    assert (target / fmt.SPEC_FILE).read_text(encoding="utf-8") == before


# ---- T013 待澄清 --------------------------------------------------------


def test_clarifications_come_from_both_sources() -> None:
    items = fmt.parse_clarifications(SPEC_WITH_ITEMS)

    assert [item.text for item in items] == ["待办要有哪些字段？", "要不要做提醒功能？"]
    assert items[0].source == "FR-001", "条目里的标记要能指回是哪一条"
    assert items[1].source == "6. 待澄清问题"


def test_no_clarifications_means_empty_list() -> None:
    text = SPEC_WITH_ITEMS.replace("[待澄清]", "").replace("待办要有哪些字段？", "")
    assert fmt.parse_clarifications(text) == []


def test_marker_inside_inline_code_is_not_a_clarification() -> None:
    """行内代码里的标记是在讨论这个约定，不是在提问——
    本仓库的 spec.md 第 0 节就写着"统一用 `[待澄清]` 标出"，它不该被算成一处待澄清。"""
    text = "# 规范\n\n- 写不清的地方统一用 `[待澄清]` 标出；其余照实写。\n"
    assert fmt.parse_clarifications(text) == []


# ---- T014 版本历史 ------------------------------------------------------


def test_requirement_history_records_appearance_and_change(project: Project) -> None:
    project.apply(
        update_requirement(project, "FR-002", "能标注完成，并记下时间。", reason="评审意见")
    )

    revisions = requirement_history(project, "FR-002")

    assert revisions[0].before is None, "第一次出现时它还不存在"
    assert revisions[0].after == "能标注完成。"
    assert revisions[0].reason == "铺测试数据"
    assert revisions[-1].before == "能标注完成。"
    assert revisions[-1].after == "能标注完成，并记下时间。"
    assert revisions[-1].reason == "评审意见", "要能回答'为何变'"


def test_requirement_history_of_an_untouched_entry_is_single(project: Project) -> None:
    revisions = requirement_history(project, "FR-001")
    assert len(revisions) == 1, "没改过就只该有一条'出现'"


def test_requirement_history_without_any_change_records(project: Project) -> None:
    """一条变更记录都没有时，退回"当前状态"而不是报错。"""
    bare = create_project(project.root.parent / "bare", name="空项目", goal="g").project
    revisions = requirement_history(bare, "FR-001")
    assert revisions == [], "空项目里没有这条需求"
    assert requirement_history(bare, "FR-999") == []


# ---- T015 逐条确认 ------------------------------------------------------


def test_confirm_marks_the_requirement(project: Project) -> None:
    project.apply(confirm_requirement(project, "FR-002"))

    assert parse_confirmed(project.spec_text()) == ["FR-002"]
    assert [item.id for item in unconfirmed_requirements(project)] == ["FR-001"]


def test_confirming_twice_is_a_noop(project: Project) -> None:
    """已确认过的条目再确认一次，应当"没有变化"——不写盘、也不留历史。"""
    project.apply(confirm_requirement(project, "FR-002"))

    change = confirm_requirement(project, "FR-002")
    assert change.is_noop
    assert project.apply(change).entry_dir is None


def test_confirm_unknown_id_lists_what_exists(project: Project) -> None:
    with pytest.raises(WorkspaceError) as excinfo:
        confirm_requirement(project, "FR-099")
    assert "FR-001" in (excinfo.value.hint or "")


def test_confirm_does_not_touch_the_body(project: Project) -> None:
    before = project.spec_text()
    project.apply(confirm_requirement(project, "FR-002"))

    body_before = before.split("---", 2)[-1]
    body_after = project.spec_text().split("---", 2)[-1]
    assert body_after == body_before, "确认只该动 frontmatter"


# ---- T016 评审稿 --------------------------------------------------------


def test_review_document_lists_pending_and_questions(project: Project) -> None:
    text = build_review_document(project, exported_on="2026-09-23")

    assert "待确认 2 条" in text
    assert "**FR-001**" in text and "**FR-002**" in text
    assert "要不要做提醒功能？" in text
    assert "## 三、规范全文" in text
    assert text.count("[待澄清]") >= 1, "原文里的标记要保留，人才知道哪句是问题"


def test_review_document_after_confirming_everything(project: Project) -> None:
    project.apply(confirm_requirement(project, "FR-001"))
    project.apply(confirm_requirement(project, "FR-002"))

    text = build_review_document(project)
    assert "待确认 0 条" in text
    assert "（全部条目都已确认）" in text


def test_export_review_writes_under_reports(project: Project) -> None:
    change = export_review(project)
    result = project.apply(change)

    assert result.written == ("reports/评审稿-2026-09-23.md",) or result.written[0].startswith(
        "reports/评审稿-"
    )
    written = project.root / result.written[0]
    assert written.is_file()
    assert "规范评审稿" in written.read_text(encoding="utf-8")


# ---- 命令行 ------------------------------------------------------------


def test_cli_questions_confirm_and_review(tmp_path: Path) -> None:
    target = tmp_path / "评审项目"
    runner.invoke(app, ["init", str(target), "--name", "评审项目", "--goal", "g", "--no-git"])
    project = Project.open(target)
    project.apply(
        project.prepare_write(fmt.SPEC_FILE, SPEC_WITH_ITEMS, reason="铺测试数据")
    )

    asked = runner.invoke(app, ["questions", str(target)])
    assert asked.exit_code == 0, asked.stdout
    assert "要不要做提醒功能？" in asked.stdout

    confirmed = runner.invoke(app, ["confirm", "FR-002", "--path", str(target)])
    assert confirmed.exit_code == 0, confirmed.stdout
    assert "已确认" in confirmed.stdout

    reviewed = runner.invoke(app, ["review", str(target)])
    assert reviewed.exit_code == 0, reviewed.stdout
    assert "已写出" in reviewed.stdout
    assert list((target / "reports").glob("评审稿-*.md"))
