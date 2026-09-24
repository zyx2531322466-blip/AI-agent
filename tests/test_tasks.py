"""任务拆解的测试（T018 ~ T024）。

几条最要紧的性质：

- **双向关联**：任务能指回需求，需求能列出任务（FR-008）；
- **三要素缺一不可**：缺完成标准/优先级/依赖的任务写不进去（FR-009）；
- **覆盖缺口只报告不挡**（FR-010）；
- **没有证据不算完成**（FR-014）；
- 改任务要素是**定点替换**，行里其它内容逐字不动。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pm_agent.errors import WorkspaceError
from pm_agent.workspace import format as fmt
from pm_agent.workspace.store import Project, create_project
from pm_agent.workspace.tasks import (
    add_task,
    complete_task,
    coverage_gaps,
    ready_tasks,
    tasks_by_milestone,
    update_task,
)

SPEC = """---
status: draft
version: 1
---

# 演示项目 —— 功能需求规范

## 4. 功能需求

### A. 记录

- **FR-001** 能记一条待办。
- **FR-002** 能按天回看。
"""

TASKS = """# 演示项目 —— 任务清单

## M1 · 记录

- [ ] **T001**（— / FR-001）把待办存下来。**完成标准**：新增一条后能读回。**优先级**：P1。**依赖**：无。
- [x] [P] **T002**（— / FR-001）给待办加标题字段。**完成标准**：标题为空时拒绝保存。**优先级**：P2。**依赖**：无。
- [ ] **T003**（— / FR-002）做回看页。**完成标准**：能按天列出。**优先级**：P1。**依赖**：T001。
"""


@pytest.fixture
def project(tmp_path: Path) -> Project:
    project = create_project(tmp_path / "demo", name="演示项目", goal="记待办").project
    project.apply(project.prepare_write(fmt.SPEC_FILE, SPEC, reason="铺规范"))
    project.apply(project.prepare_write(fmt.TASKS_FILE, TASKS, reason="铺任务"))
    return project


# ---- 解析 --------------------------------------------------------------


def test_parse_reads_every_field() -> None:
    tasks = {task.id: task for task in fmt.parse_tasks(TASKS)}

    first = tasks["T001"]
    assert first.title == "把待办存下来"
    assert first.done is False
    assert first.parallel is False
    assert first.milestone == "M1 · 记录"
    assert first.requirements == ("FR-001",)
    assert first.standard == "新增一条后能读回"
    assert first.priority == "P1", "末尾那个句号是标点，不该混进字段值"
    assert first.depends_on == ()
    assert first.has_source

    assert tasks["T002"].done is True
    assert tasks["T002"].parallel is True
    assert tasks["T003"].depends_on == ("T001",)


def test_parse_counts_the_whole_repo_task_file() -> None:
    """拿本仓库自己的 tasks.md 试：它必须能完整解析（含 [P] 那些行）。"""
    text = (Path(__file__).parents[1] / "tasks.md").read_text(encoding="utf-8")
    tasks = fmt.parse_tasks(text)

    # 不写死条数：那样每加一条任务都得改测试。断言的是**完整性**——
    # 每一条勾选行都要被解析出来，不能有默默漏掉的。
    checklist = [line for line in text.split("\n") if line.startswith("- [")]
    assert len(tasks) == len(checklist), "勾选行与解析出的任务数对不上，有行被漏掉了"
    assert sum(1 for task in tasks if task.parallel) == 15
    assert all(task.standard for task in tasks), "每条任务都该有完成标准"


def test_check_tasks_reports_dangling_dependency() -> None:
    text = TASKS + "- [ ] **T004**（— / FR-002）别的活。**完成标准**：x。**优先级**：P1。**依赖**：T099。\n"
    problems = fmt.check_tasks(text)

    assert any("T099" in problem.message for problem in problems)


def test_check_tasks_reports_duplicate_and_malformed() -> None:
    text = TASKS + "- [ ] **T001**（— / FR-001）重复。**完成标准**：x。\n"
    text += "- [ ] **T9**（— / FR-001）编号不合规。\n"
    problems = fmt.check_tasks(text)

    assert any("两次" in problem.message for problem in problems)
    assert any("不合规" in problem.message for problem in problems)


# ---- 覆盖与就绪（T020 / T023）-----------------------------------------


def test_coverage_is_complete_when_every_requirement_has_a_task(project: Project) -> None:
    report = coverage_gaps(project)
    assert report.ok, report.render()


def test_coverage_reports_uncovered_requirement(project: Project) -> None:
    without_second = "\n".join(
        line for line in TASKS.split("\n") if "T003" not in line
    )
    project.apply(project.prepare_write(fmt.TASKS_FILE, without_second, reason="拿掉一条"))

    report = coverage_gaps(project)
    assert [item.id for item in report.uncovered_requirements] == ["FR-002"]
    assert not report.ok


def test_explicit_dash_is_not_a_coverage_gap(project: Project) -> None:
    """写了（— / —）的任务算"明确没有来源"，不算缺口；漏写引用才算。"""
    project.apply(
        project.prepare_write(
            fmt.TASKS_FILE,
            TASKS + "- [ ] **T004**（— / —）搭骨架。**完成标准**：能跑。**优先级**：P1。**依赖**：无。\n",
            reason="加一个无来源任务",
        )
    )
    assert coverage_gaps(project).ok

    project.apply(
        project.prepare_write(
            fmt.TASKS_FILE,
            TASKS + "- [ ] **T005**搭骨架但忘了写来源。**完成标准**：能跑。**优先级**：P1。**依赖**：无。\n",
            reason="加一个漏写来源的任务",
        )
    )
    report = coverage_gaps(project)
    assert [item.id for item in report.sourceless_tasks] == ["T005"]


def test_success_criterion_counts_as_a_source(project: Project) -> None:
    """来源不只需求一种：直接对着验收标准干活的任务（`US-1 / SC-001`）也算交代了来源。"""
    text = TASKS + "- [ ] **T006**（US-1 / SC-001）补一个金样本。**完成标准**：能重放。**优先级**：P2。**依赖**：无。\n"
    task = {item.id: item for item in fmt.parse_tasks(text)}["T006"]

    assert task.requirements == ()
    assert task.criteria == ("SC-001",)
    assert task.has_source


def test_repo_task_file_has_no_sourceless_tasks() -> None:
    """拿本仓库自己的 tasks.md 试：不该有"找不到来源"的任务。

    金样本任务引用的是成功标准而不是需求条目，如果只认 FR-xxx，
    它们会被误判成漏写来源。
    """
    text = (Path(__file__).parents[1] / "tasks.md").read_text(encoding="utf-8")
    sourceless = [task.id for task in fmt.parse_tasks(text) if not task.has_source]
    assert sourceless == []


def test_ready_tasks_waits_for_dependencies(project: Project) -> None:
    """T003 依赖 T001，而 T001 还没完成 → 它现在不能动手。"""
    ready = ready_tasks(project)

    assert [task.id for task in ready] == ["T001"], "T001 是 P1 且无依赖"


def test_ready_tasks_sorts_by_priority(project: Project) -> None:
    project.apply(complete_task(project, "T001", evidence="提交 abc123"))
    ready = ready_tasks(project)

    assert [task.id for task in ready] == ["T003"], "T001 完成后，依赖它的 T003 就绪"
    assert ready[0].priority == "P1"


def test_tasks_by_milestone(project: Project) -> None:
    grouped = tasks_by_milestone(project)
    assert list(grouped) == ["M1 · 记录"]
    assert [task.id for task in grouped["M1 · 记录"]] == ["T001", "T002", "T003"]


# ---- 新建与调整（T019 / T022）-----------------------------------------


@pytest.mark.parametrize(
    "kwargs",
    [
        {"standard": "", "priority": "P1"},
        {"standard": "能跑", "priority": ""},
    ],
)
def test_add_task_refuses_to_save_without_required_elements(
    project: Project, kwargs: dict[str, str]
) -> None:
    """FR-009：缺任一要素就不产出变更——不是提醒，是写不进去。"""
    with pytest.raises(WorkspaceError):
        add_task(project, title="缺要素的任务", **kwargs)


def test_add_task_refuses_dangling_references(project: Project) -> None:
    with pytest.raises(WorkspaceError):
        add_task(project, title="x", standard="s", priority="P1", depends_on=["T099"])
    with pytest.raises(WorkspaceError):
        add_task(project, title="x", standard="s", priority="P1", requirements=["FR-099"])


def test_add_task_lands_at_the_end_of_the_milestone(project: Project) -> None:
    project.apply(
        add_task(
            project,
            title="能搜索待办",
            standard="输入关键字能筛出对应条目",
            priority="P2",
            depends_on=["T001"],
            requirements=["FR-001"],
            milestone="M1 · 记录",
        )
    )

    tasks = project.tasks()
    assert tasks[-1].id == "T004"
    assert tasks[-1].milestone == "M1 · 记录"
    assert tasks[-1].depends_on == ("T001",)


def test_add_task_rejects_unknown_milestone(project: Project) -> None:
    with pytest.raises(WorkspaceError) as excinfo:
        add_task(
            project, title="x", standard="s", priority="P1", milestone="M9 · 不存在"
        )
    assert "里程碑" in str(excinfo.value)


def test_update_task_rewrites_only_that_field(project: Project) -> None:
    before = project.read_text(fmt.TASKS_FILE).split("\n")
    project.apply(update_task(project, "T002", priority="P1"))
    after = project.read_text(fmt.TASKS_FILE).split("\n")

    assert len(before) == len(after)
    changed = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
    assert len(changed) == 1
    assert "**优先级**：P1。" in after[changed[0]]
    assert "**完成标准**：标题为空时拒绝保存。" in after[changed[0]], "别的字段逐字不动"


def test_update_task_rejects_self_and_dangling_dependency(project: Project) -> None:
    with pytest.raises(WorkspaceError):
        update_task(project, "T002", depends_on=["T002"])
    with pytest.raises(WorkspaceError):
        update_task(project, "T002", depends_on=["T099"])


def test_update_task_on_unknown_id_lists_tasks(project: Project) -> None:
    with pytest.raises(WorkspaceError) as excinfo:
        update_task(project, "T099", priority="P1")
    assert "T001" in (excinfo.value.hint or "")


# ---- 完成与证据（T024）-------------------------------------------------


def test_complete_task_requires_evidence(project: Project) -> None:
    """FR-014：没有证据不能标记完成——只勾一个框不算做完。"""
    with pytest.raises(WorkspaceError) as excinfo:
        complete_task(project, "T001")
    assert "证据" in str(excinfo.value)
    assert project.tasks()[0].done is False, "拒绝之后不该有任何改动"


def test_complete_task_records_evidence_and_ticks(project: Project) -> None:
    project.apply(complete_task(project, "T001", evidence="提交 abc123：待办表与读写"))

    task = {item.id: item for item in project.tasks()}["T001"]
    assert task.done is True
    assert task.evidence == "提交 abc123：待办表与读写"


def test_complete_task_accepts_evidence_attached_earlier(project: Project) -> None:
    project.apply(update_task(project, "T001", evidence="文档：设计说明 §2"))
    project.apply(complete_task(project, "T001"))

    task = {item.id: item for item in project.tasks()}["T001"]
    assert task.done and task.evidence == "文档：设计说明 §2"


def test_preparing_task_changes_does_not_write(project: Project) -> None:
    before = project.read_text(fmt.TASKS_FILE)
    add_task(project, title="x", standard="s", priority="P1")
    complete_task(project, "T001", evidence="提交 abc")

    assert project.read_text(fmt.TASKS_FILE) == before
