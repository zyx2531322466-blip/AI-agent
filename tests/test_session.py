"""跨会话交接的测试（T026 ~ T031）。

这一段要证明的核心是 FR-017：**会话开始时先重建状态，再执行新指令**。
配合 FR-018 的冲突校验——记录和实际对不上时**先停下来**。
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pm_agent.cli import app
from pm_agent.errors import WorkspaceError
from pm_agent.harness.session import session_brief
from pm_agent.workspace import format as fmt
from pm_agent.workspace.handoff import (
    draft_handoff,
    find_conflicts,
    read_latest_handoff,
    write_handoff,
)
from pm_agent.workspace.store import Project, create_project
from pm_agent.workspace.tasks import (
    complete_task,
    parse_status_update,
    set_task_status,
    update_task,
)

MOMENT = dt.datetime(2026, 9, 23, 10, 0, 0)

SPEC = """---
status: draft
version: 1
---

# 演示项目 —— 功能需求规范

## 4. 功能需求

- **FR-001** 能记一条待办。
- **FR-002** 能按天回看。
"""

TASKS = """# 演示项目 —— 任务清单

## M1 · 记录

- [ ] **T001**（— / FR-001）把待办存下来。**完成标准**：新增一条后能读回。**优先级**：P1。**依赖**：无。
- [ ] **T002**（— / FR-002）做回看页。**完成标准**：能按天列出。**优先级**：P2。**依赖**：T001。
"""

runner = CliRunner()


@pytest.fixture
def project(tmp_path: Path) -> Project:
    project = create_project(tmp_path / "demo", name="演示项目", goal="记待办").project
    project.apply(project.prepare_write(fmt.SPEC_FILE, SPEC, reason="铺规范"))
    project.apply(project.prepare_write(fmt.TASKS_FILE, TASKS, reason="铺任务"))
    return project


# ---- T026 四种状态与变更时间 -------------------------------------------


def test_status_change_records_state_and_time(project: Project) -> None:
    project.apply(
        set_task_status(project, "T001", "进行中", moment=MOMENT)
    )

    task = {item.id: item for item in project.tasks()}["T001"]
    assert task.status == "进行中"
    assert task.updated == "2026-09-23 10:00", "FR-015 要求留下变更时间"
    assert task.done is False, "没完成就不该打勾"


def test_done_ticks_the_box_and_keeps_evidence(project: Project) -> None:
    project.apply(complete_task(project, "T001", evidence="提交 abc123"))

    task = {item.id: item for item in project.tasks()}["T001"]
    assert task.status == "完成" and task.done is True
    assert task.evidence == "提交 abc123"


def test_setting_back_from_done_clears_the_box(project: Project) -> None:
    project.apply(complete_task(project, "T001", evidence="提交 abc123"))
    project.apply(set_task_status(project, "T001", "阻塞"))

    task = {item.id: item for item in project.tasks()}["T001"]
    assert task.status == "阻塞" and task.done is False


def test_done_still_requires_evidence(project: Project) -> None:
    with pytest.raises(WorkspaceError):
        set_task_status(project, "T001", "完成")


def test_unknown_status_is_rejected(project: Project) -> None:
    with pytest.raises(WorkspaceError) as excinfo:
        set_task_status(project, "T001", "随便写的状态")
    assert "进行中" in (excinfo.value.hint or "")


# ---- T031 中间结论 ------------------------------------------------------


def test_conclusion_is_kept_and_shows_up_in_the_draft(project: Project) -> None:
    project.apply(set_task_status(project, "T001", "进行中"))
    project.apply(update_task(project, "T001", conclusion="校验放在写入口更省事"))

    task = {item.id: item for item in project.tasks()}["T001"]
    assert task.conclusion == "校验放在写入口更省事"

    draft = draft_handoff(project, moment=MOMENT)
    assert "校验放在写入口更省事" in draft.state, "中间结论要进摘要，新会话才接得上"


# ---- T028 交接记录草稿 --------------------------------------------------


def test_draft_fills_the_three_elements(project: Project) -> None:
    draft = draft_handoff(project, moment=MOMENT)

    assert draft.state.strip(), "当前状态不能空"
    assert draft.next_steps.strip(), "下一步建议不能空"
    assert draft.open_questions.strip(), "未决问题不能空（没有就写'无'）"
    assert "T001" in draft.next_steps, "就绪任务应当出现在下一步里"
    assert "（这一轮做了什么" in draft.did, "需要人补的那句要留白，不要编"


def test_draft_mentions_open_clarifications(project: Project) -> None:
    text = project.read_text(fmt.SPEC_FILE) + "\n- [待澄清] 要不要做提醒？\n"
    project.apply(project.prepare_write(fmt.SPEC_FILE, text, reason="加一条待澄清"))

    assert "要不要做提醒？" in draft_handoff(project, moment=MOMENT).open_questions


# ---- T027 会话开始重建状态 ----------------------------------------------


def test_brief_works_before_any_handoff(project: Project) -> None:
    brief = session_brief(project)

    assert brief.last_handoff is None
    assert "第一次会话" in brief.render()
    assert [task.id for task in brief.ready] == ["T001"]


def test_brief_rebuilds_from_the_last_handoff(project: Project) -> None:
    project.apply(set_task_status(project, "T001", "进行中"))
    project.apply(update_task(project, "T001", conclusion="还差一个写入口"))
    write_handoff(project, draft_handoff(project, moment=MOMENT))

    brief = session_brief(project)
    text = brief.render()

    assert brief.last_handoff is not None
    assert "上次到哪" in text and "下一步建议" in text
    assert "T001" in text and "还差一个写入口" in text, "进行中任务的结论要能看到"
    assert "任务：完成 0 / 进行中 1" in text


def test_brief_lists_ready_tasks_by_priority(project: Project) -> None:
    brief = session_brief(project)
    assert [task.id for task in brief.ready] == ["T001"]
    assert "现在能动手" in brief.render()


# ---- T029 冲突校验 ------------------------------------------------------


def test_conflict_when_record_mentions_a_missing_task(project: Project) -> None:
    handoff = draft_handoff(project, moment=MOMENT)
    handoff = handoff.__class__(**{**handoff.__dict__, "state": "下一步：T099 收尾"})

    problems = find_conflicts(project, handoff)
    assert any("T099" in problem.message for problem in problems)
    assert fmt.errors(problems), "指向不存在的任务属于必须裁决的冲突"


def test_conflict_when_record_mentions_a_missing_requirement(project: Project) -> None:
    handoff = draft_handoff(project, moment=MOMENT)
    handoff = handoff.__class__(**{**handoff.__dict__, "next_steps": "继续做 FR-099"})

    assert fmt.errors(find_conflicts(project, handoff))


def test_warning_when_record_is_older_than_the_latest_change(project: Project) -> None:
    """记录写完之后又改过东西——不算冲突，但摘要可能已经过期。"""
    write_handoff(project, draft_handoff(project, moment=dt.datetime(2026, 9, 16, 9, 0, 0)))
    project.apply(set_task_status(project, "T001", "进行中", moment=MOMENT))

    handoff = read_latest_handoff(project)
    assert handoff is not None
    problems = find_conflicts(project, handoff)

    assert not fmt.errors(problems), "过期只是提示，不是必须裁决的冲突"
    assert any("之后还有" in problem.message for problem in fmt.warnings(problems))


# ---- T030 一句话更新状态 ------------------------------------------------


def test_track_finds_the_task_by_id(project: Project) -> None:
    update = parse_status_update(project, "T001 做完了，提交 abc123")

    assert update is not None
    assert update.task.id == "T001"
    assert update.status == "完成"
    assert "abc123" in update.evidence


def test_track_finds_the_task_by_title(project: Project) -> None:
    update = parse_status_update(project, "回看页这块卡住了，在等接口")

    assert update is not None
    assert update.task.id == "T002"
    assert update.status == "阻塞"


def test_track_handles_simple_negation(project: Project) -> None:
    update = parse_status_update(project, "T001 还没做完")
    assert update is not None and update.status == "进行中"


def test_track_gives_up_when_it_cannot_tell(project: Project) -> None:
    """认不出来就返回 None——宁可问，不要猜。"""
    assert parse_status_update(project, "今天天气不错") is None
    assert parse_status_update(project, "T099 做完了") is None


# ---- 命令行 ------------------------------------------------------------


def test_cli_track_and_handoff_and_resume(tmp_path: Path) -> None:
    target = tmp_path / "会话项目"
    runner.invoke(app, ["init", str(target), "--name", "会话项目", "--goal", "g", "--no-git"])
    project = Project.open(target)
    project.apply(project.prepare_write(fmt.SPEC_FILE, SPEC, reason="铺规范"))
    project.apply(project.prepare_write(fmt.TASKS_FILE, TASKS, reason="铺任务"))

    tracked = runner.invoke(
        app,
        ["track", "T001 做完了，提交 abc123", "--path", str(target), "--yes"],
    )
    assert tracked.exit_code == 0, tracked.stdout
    assert "我听懂的是" in tracked.stdout and "已更新" in tracked.stdout

    written = runner.invoke(app, ["handoff", str(target), "--yes"])
    assert written.exit_code == 0, written.stdout
    assert "已写出" in written.stdout

    resumed = runner.invoke(app, ["resume", str(target)])
    assert resumed.exit_code == 0, resumed.stdout
    assert "上次到哪" in resumed.stdout
    assert "任务：完成 1" in resumed.stdout


def test_cli_track_reports_when_it_cannot_tell(tmp_path: Path) -> None:
    target = tmp_path / "会话项目"
    runner.invoke(app, ["init", str(target), "--name", "n", "--goal", "g", "--no-git"])

    result = runner.invoke(app, ["track", "随便说点什么", "--path", str(target)])

    assert result.exit_code == 1
    assert "没听出" in result.stdout
