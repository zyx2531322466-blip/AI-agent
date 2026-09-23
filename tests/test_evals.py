"""金样本回放（T017）。

固定输入 + 一份**录制**的真实模型输出。回放它，就能在没有网络、不花钱的情况下
验证整条链路：清理 → 校验 → 组装 → 落盘，并守住 SC-001。

录制怎么来的、什么时候重做，见 evals/README.md。
"""

from __future__ import annotations

from pathlib import Path

import yaml

from pm_agent.stages.specify import (
    REQUIRED_TOPICS,
    SpecDraft,
    check_draft,
    prepare_spec_change,
)
from pm_agent.stages.tasks import TaskDraft, check_draft as check_tasks_draft
from pm_agent.stages.tasks import prepare_tasks_change
from pm_agent.workspace import format as fmt
from pm_agent.workspace.store import create_project
from pm_agent.workspace.tasks import coverage_gaps

CASE_DIR = Path(__file__).parents[1] / "evals" / "specify"
CASE_FILE = CASE_DIR / "case-001.yaml"
RECORDING = CASE_DIR / "case-001.recorded.md"

TASK_CASE_DIR = Path(__file__).parents[1] / "evals" / "tasks"


def test_recorded_case_satisfies_sc001(tmp_path: Path) -> None:
    """一次会话内产出可评审规范，且不需要人工补结构。"""
    case = yaml.safe_load(CASE_FILE.read_text(encoding="utf-8"))
    recorded = RECORDING.read_text(encoding="utf-8")

    project = create_project(
        tmp_path / "case-001",
        name=case["name"],
        goal=case["goal"],
        learning_goals=list(case.get("learning_goals") or []),
    ).project

    draft = SpecDraft(text=recorded, source="录制（evals/specify/case-001.recorded.md）")
    assert check_draft(draft) == [], "录制的输出必须是合格规范"

    project.apply(prepare_spec_change(project, draft, reason="金样本回放"))
    written = project.read_text(fmt.SPEC_FILE)

    for topic in REQUIRED_TOPICS:
        assert topic in written, f"规范缺少「{topic}」"

    items = fmt.parse_requirements(written)
    assert items, "至少要有需求条目，否则谈不上'结构化规范'"
    assert all(item.text.strip() for item in items), "不能有空条目"

    assert written.startswith("---"), "程序维护的 frontmatter 应当保留"
    assert fmt.errors(fmt.check_workspace(project.root)) == [], "产出应当通过工作区校验"


def test_recorded_breakdown_covers_every_requirement(tmp_path: Path) -> None:
    """SC-002：拆解覆盖率 100%——没有遗漏的需求，也没有找不到来源的任务。"""
    spec_text = (TASK_CASE_DIR / "case-001.spec.md").read_text(encoding="utf-8")
    recorded = (TASK_CASE_DIR / "case-001.recorded.md").read_text(encoding="utf-8")

    project = create_project(tmp_path / "task-case", name="待办清单", goal="记待办").project
    project.apply(project.prepare_write(fmt.SPEC_FILE, spec_text, reason="铺规范"))

    draft = TaskDraft(text=recorded, source="录制（evals/tasks/case-001.recorded.md）")
    assert check_tasks_draft(project, draft) == [], "录制的拆解必须是合格任务清单"

    project.apply(prepare_tasks_change(project, draft, reason="金样本回放"))

    report = coverage_gaps(project)
    assert report.ok, "覆盖率必须 100%：\n" + report.render()

    tasks = project.tasks()
    assert tasks, "至少要有任务"
    assert all(task.standard for task in tasks), "每条任务都要有完成标准"
    assert all(task.priority for task in tasks), "每条任务都要有优先级"
    assert all("依赖" in task.fields for task in tasks), "每条任务都要交代依赖"
