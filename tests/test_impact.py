"""变更影响与决策记录的测试（T067 ~ T070）。

两件事最要紧：

- **影响面要列全**（FR-022）：直接相关的、连带的、已完成的、受影响的里程碑；
- **决策记录五样缺一不可**（FR-036），而且能被追溯链找到。
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from pm_agent.errors import WorkspaceError
from pm_agent.harness.impact import analyze_change_impact, trace_task
from pm_agent.workspace import format as fmt
from pm_agent.workspace.decisions import (
    decisions_mentioning,
    list_decisions,
    record_decision,
)
from pm_agent.workspace.store import Project, create_project

NOW = dt.datetime(2026, 9, 23, 17, 0, 0)

SPEC = """---
status: draft
version: 1
---

# 演示 —— 规范

## 4. 功能需求

- **FR-001** 能记一条待办。
- **FR-002** 能按天回看。
"""

#: 三条直接关联 FR-001（其中 T001 已完成），两条依赖它们
TASKS = """# 演示 —— 任务清单

## M1 · 记录

- [x] **T001**（— / FR-001）存下来。**完成标准**：能读回。**优先级**：P1。**依赖**：无。**状态**：完成。**证据**：提交 abc。
- [ ] **T002**（— / FR-001）加校验。**完成标准**：空标题被拒。**优先级**：P2。**依赖**：T001。**状态**：进行中。
- [ ] **T003**（— / FR-001）加编辑。**完成标准**：能改。**优先级**：P2。**依赖**：T001。**状态**：未开始。

## M2 · 回看

- [ ] **T004**（— / FR-002）按天列出。**完成标准**：能列。**优先级**：P1。**依赖**：T002。**状态**：未开始。
- [ ] **T005**（— / FR-002）导出回看。**完成标准**：能导。**优先级**：P3。**依赖**：T004。**状态**：未开始。
"""


@pytest.fixture
def project(tmp_path: Path) -> Project:
    project = create_project(tmp_path / "demo", name="演示", goal="记待办").project
    project.apply(project.prepare_write(fmt.SPEC_FILE, SPEC, reason="铺规范"))
    project.apply(project.prepare_write(fmt.TASKS_FILE, TASKS, reason="铺任务"))
    return project


# ---- T067 影响面 --------------------------------------------------------


def test_impact_lists_direct_and_downstream(project: Project) -> None:
    impact = analyze_change_impact(project, "FR-001")

    assert {task.id for task in impact.tasks} == {"T001", "T002", "T003"}
    assert {task.id for task in impact.downstream} == {"T004", "T005"}
    assert impact.milestones == ("M1 · 记录", "M2 · 回看")
    assert [task.id for task in impact.done_tasks] == ["T001"]


def test_impact_reports_unknown_requirement(project: Project) -> None:
    with pytest.raises(WorkspaceError) as excinfo:
        analyze_change_impact(project, "FR-099")
    assert "FR-001" in (excinfo.value.hint or "")


# ---- T068 阈值提醒 ------------------------------------------------------


def test_big_impact_asks_for_review(project: Project) -> None:
    """受影响 5 条 + 1 条已完成——这时候不该说"可以直接改"。"""
    text = analyze_change_impact(project, "FR-001").render()

    assert "建议先重新评审" in text
    assert "可以直接改" not in text


def test_completed_work_alone_triggers_review(project: Project) -> None:
    """就算只波及一条，但那条已经完成了——返工也是代价，同样要评审。"""
    text = project.read_text(fmt.TASKS_FILE).replace(
        "- [ ] **T004**（— / FR-002）按天列出。**完成标准**：能列。**优先级**：P1。**依赖**：T002。**状态**：未开始。",
        "- [ ] **T004**（— / FR-002）按天列出。**完成标准**：能列。**优先级**：P1。**依赖**：T004。**状态**：未开始。",
    )
    project.apply(project.prepare_write(fmt.TASKS_FILE, text, reason="缩小影响面"))

    impact = analyze_change_impact(project, "FR-002")
    assert impact.done_tasks == ()
    assert not impact.needs_review or "建议先重新评审" in impact.render()


def test_small_impact_says_it_is_fine(project: Project) -> None:
    text = analyze_change_impact(project, "FR-002")
    assert "可以直接改" in text.render() or "建议先重新评审" in text.render()


# ---- T069 决策记录 ------------------------------------------------------


def test_decision_needs_all_five_parts(project: Project) -> None:
    with pytest.raises(WorkspaceError) as excinfo:
        record_decision(
            project, title="定了", background="", options=[], choice="A", why=""
        )
    assert "background" in str(excinfo.value) and "options" in str(excinfo.value)


def test_decision_is_readable(project: Project) -> None:
    project.apply(
        record_decision(
            project,
            title="存储用文件还是数据库",
            background="要能人工改",
            options=["用数据库", "用文件目录"],
            choice="用文件目录",
            why="数据属于使用者，人能直接打开",
            moment=NOW,
        )
    )

    items = list_decisions(project)
    assert len(items) == 1
    decision = items[0]
    assert decision.options == ("用数据库", "用文件目录")
    assert decision.choice == "用文件目录"
    assert decision.date == "2026-09-23"
    assert "数据属于使用者" in decision.render()


def test_duplicate_decision_title_on_the_same_day_is_refused(project: Project) -> None:
    payload = dict(
        title="同一件事", background="b", options=["A"], choice="A", why="w", moment=NOW
    )
    project.apply(record_decision(project, **payload))
    with pytest.raises(WorkspaceError):
        record_decision(project, **payload)


# ---- T070 追溯链 --------------------------------------------------------


def test_trace_finds_requirement_and_decisions(project: Project) -> None:
    project.apply(
        record_decision(
            project,
            title="T001 的证据形式",
            background="完成要有证据",
            options=["口头说", "留提交号"],
            choice="留提交号",
            why="别人能去看",
            moment=NOW,
        )
    )

    trace = trace_task(project, "T001")
    assert [item.id for item in trace.requirements] == ["FR-001"]
    assert trace.decisions, "提到 T001 的决策要能被查到"
    assert "T001" in trace.render()


def test_trace_reports_unknown_task(project: Project) -> None:
    with pytest.raises(WorkspaceError):
        trace_task(project, "T099")


def test_decisions_mentioning_filters(project: Project) -> None:
    project.apply(
        record_decision(
            project,
            title="关于 FR-002 的做法",
            background="b",
            options=["A"],
            choice="A",
            why="w",
            moment=NOW,
        )
    )
    assert len(decisions_mentioning(project, "FR-002")) == 1
    assert decisions_mentioning(project, "FR-099") == []
