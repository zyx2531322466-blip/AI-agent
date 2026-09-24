"""可讲解的测试（T033 ~ T036）。

这一段的重点是两件事：

- **每条判断都带依据**（FR-048）：阶段说明里有"依据"一行，且依据指向的东西是真的；
- **讲解模式给出取舍与备选**（FR-049）：不只会说"我这么做了"，还会说"我还考虑过什么"。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pm_agent.explain.design import build_design_document, export_design
from pm_agent.explain.goals import goal_review
from pm_agent.stages import announce, get_stage, load_stages
from pm_agent.workspace import format as fmt
from pm_agent.workspace.store import Project, create_project


@pytest.fixture
def project(tmp_path: Path) -> Project:
    return create_project(
        tmp_path / "demo",
        name="演示项目",
        goal="把待办集中起来",
        learning_goals=["学会写规范", "学会拆任务"],
    ).project


# ---- T033 依据来源标注 --------------------------------------------------


def test_every_stage_declares_a_basis() -> None:
    for key, stage in load_stages().items():
        assert stage.basis.strip(), f"{key} 没有写依据"


def test_announce_shows_the_basis() -> None:
    for key in load_stages():
        assert "依据：" in announce(key), f"{key} 的说明里没有依据这一行"


def test_basis_references_real_requirements() -> None:
    """依据里引用的需求编号，必须真在本仓库的 spec.md 里——否则就是编的。"""
    spec_text = (Path(__file__).parents[1] / "spec.md").read_text(encoding="utf-8")
    known = {item.id for item in fmt.parse_requirements(spec_text)}

    for key, stage in load_stages().items():
        for requirement_id in fmt.FR_ID_RE.findall(stage.basis):
            assert requirement_id in known, f"{key} 的依据引用了不存在的 {requirement_id}"


# ---- T034 讲解模式 ------------------------------------------------------


def test_explain_mode_adds_tradeoffs_and_alternatives() -> None:
    for key in load_stages():
        text = announce(key, explain=True)
        assert "取舍：" in text, f"{key} 没说取舍"
        assert "被放弃的备选：" in text, f"{key} 没说放弃了什么"


def test_plain_mode_stays_short() -> None:
    """不讲解的时候别把取舍也倒出来——默认输出要保持能一眼看完。"""
    text = announce("specify")
    assert "依据：" in text
    assert "取舍：" not in text and "被放弃的备选：" not in text


def test_stage_explain_is_reachable_by_name() -> None:
    stage = get_stage("track")
    assert stage.tradeoffs.strip() and stage.alternatives.strip()


# ---- T035 学习目标对照 --------------------------------------------------


def test_goal_review_without_goals_says_so(tmp_path: Path) -> None:
    bare = create_project(tmp_path / "bare", name="空项目", goal="g").project
    assert "还没有写 learning_goals" in goal_review(bare).render()


def test_goal_review_lists_progress_and_labels_guesses(project: Project) -> None:
    project.apply(
        project.prepare_write(
            fmt.SPEC_FILE,
            "# 规范\n\n- **FR-001** 能记待办。\n",
            reason="铺规范",
        )
    )
    project.apply(
        project.prepare_write(
            fmt.TASKS_FILE,
            "# 任务\n\n## M1 · 记录\n\n"
            "- [x] **T001**（— / FR-001）把待办存下来。**完成标准**：能读回。"
            "**优先级**：P1。**依赖**：无。**状态**：完成。**证据**：提交 abc。\n",
            reason="铺任务",
        )
    )

    review = goal_review(project)
    text = review.render()

    assert review.learning_goals == ("学会写规范", "学会拆任务")
    assert "已走通：规范 1 条需求" in text, "进展要写明依据（几条需求）"
    assert "规范" in text and "任务 1 个任务，完成 1 个" in text
    assert "（推测，自己判断）" in text or "没找到明显重合的" in text


def test_goal_review_marks_matches_as_guesses(project: Project) -> None:
    """匹配是推测不是事实：目标文本和任务标题之间没有权威对应关系。"""
    project.apply(
        project.prepare_write(
            fmt.TASKS_FILE,
            "# 任务\n\n## M1 · 记录\n\n"
            "- [x] **T001**（— / FR-001）学会写规范。**完成标准**：能评审。"
            "**优先级**：P1。**依赖**：无。**状态**：完成。**证据**：提交 abc。\n",
            reason="铺任务",
        )
    )

    text = goal_review(project).render()
    assert "学会写规范" in text
    if "标题重合" in text:
        assert "推测" in text, "推测必须标明是推测（FR-024）"


# ---- T036 设计说明 ------------------------------------------------------


def test_design_document_covers_every_stage(project: Project) -> None:
    doc = build_design_document(project, today="2026-09-23")

    assert "设计说明" in doc
    for key, stage in load_stages().items():
        assert stage.title in doc, f"设计说明里缺阶段「{stage.title}」"
        assert stage.purpose[:20] in doc
        assert stage.tradeoffs[:20] in doc
        assert stage.alternatives[:20] in doc
    assert "## 一、这个项目想学到什么" in doc and "学会写规范" in doc


def test_design_document_points_at_where_the_whys_live(project: Project) -> None:
    doc = build_design_document(project)
    assert "stages/stages.yaml" in doc
    assert "plan.md" in doc and "spec.md" in doc and "sessions/" in doc


def test_export_design_writes_under_reports(project: Project) -> None:
    result = project.apply(export_design(project))

    assert result.written[0].startswith("reports/设计说明-")
    assert (project.root / result.written[0]).is_file()


def test_design_export_is_only_a_preview(project: Project) -> None:
    before = sorted(path.name for path in project.path("reports").glob("*"))
    export_design(project)
    after = sorted(path.name for path in project.path("reports").glob("*"))
    assert before == after, "准备阶段不该写文件"
