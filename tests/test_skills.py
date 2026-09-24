"""能力单元的测试（T046 ~ T053）。

四件事最要紧：

- **六要素缺一就存不进去**，而且必须有 why（FR-026 / FR-050）；
- **三级渐进式加载**：元数据里不该出现正文；
- **建议可以不采纳，拒绝之后不纠缠**（FR-027）；
- **修订不动使用历史**（FR-029）——这也是把采纳记录放 `project.yaml` 而不是
  能力单元目录里的理由。
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from pm_agent.errors import FormatError, WorkspaceError
from pm_agent.workspace import format as fmt
from pm_agent.workspace.skills import (
    DECLINE_COOLDOWN_DAYS,
    builtin_skills,
    get_skill,
    list_skills,
    load_reference,
    load_skill,
    record_usage,
    revise_skill,
    save_skill,
    suggest_skills,
    usage_summary,
)
from pm_agent.workspace.store import Project, create_project

NOW = dt.datetime(2026, 9, 23, 17, 0, 0)

FIELDS = dict(
    description="把一段口述整理成检查清单",
    when_to_use="需要把口述的流程固化下来时",
    when_not_to_use="流程还没跑通过时",
    inputs="一段口述",
    outputs="一份检查清单",
    why="口头讲过的东西不留下来就会忘",
)


@pytest.fixture
def project(tmp_path: Path) -> Project:
    return create_project(tmp_path / "demo", name="演示项目", goal="记待办").project


def make_skill(project: Project, name: str = "my-skill") -> None:
    project.apply(
        save_skill(
            project,
            name=name,
            steps=["先把口述抄下来", "按顺序编号", "每条写清完成标准"],
            **FIELDS,
        )
    )


# ---- T052 / T053 内置能力单元 -------------------------------------------


def test_builtin_skills_cover_the_documented_ones() -> None:
    """内置能力单元至少要包含文档里承诺的那几个。

    这里断言的是**包含**而不是相等：加一个新范例不该逼着改测试
    （踩过同样的坑：把条数写死，加一条就得改一次）。
    """
    names = {meta.name for meta in builtin_skills()}
    expected = {
        "requirement-review",
        "risk-retro",
        "weekly-report",
        "verification-before-completion",
    }
    assert expected <= names, f"缺了：{sorted(expected - names)}"


def test_every_builtin_skill_explains_why() -> None:
    """FR-050：每个能力单元都要说清为什么这样做，不能只给步骤。"""
    for meta in builtin_skills():
        assert len(meta.why.strip()) >= 20, f"{meta.name} 的 why 太短，等于没说"


def test_every_builtin_skill_has_the_six_elements() -> None:
    for meta in builtin_skills():
        for field in fmt.SKILL_REQUIRED_FIELDS:
            assert getattr(meta, field).strip(), f"{meta.name} 缺 {field}"


def test_verification_skill_keeps_the_upstream_body(project: Project) -> None:
    """`verification-before-completion` 是逐字复刻上游的范例：正文核心不许被改写掉。

    上游：obra/superpowers（MIT）。本项目只补了 frontmatter 的五个字段与末尾的来源说明。
    """
    from pm_agent.workspace.skills import load_skill

    text = load_skill(project, "verification-before-completion")

    for marker in (
        "NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE",
        "The Gate Function",
        "| Claim | Requires | Not Sufficient |",
        "## Red Flags - STOP",
        "## Rationalization Prevention",
    ):
        assert marker in text, f"上游正文被改动了：缺 {marker}"
    assert "MIT" in text and "obra/superpowers" in text, "要标清来源与许可证"
# ---- T046 格式与要素 ----------------------------------------------------


@pytest.mark.parametrize("field", ["name", "description", "why", "when_to_use"])
def test_saving_without_required_element_is_refused(project: Project, field: str) -> None:
    payload = dict(FIELDS)
    payload["name"] = "x"
    payload[field] = "   "
    with pytest.raises(WorkspaceError):
        save_skill(project, steps=["一条要点"], **payload)


def test_saving_without_steps_is_refused(project: Project) -> None:
    with pytest.raises(WorkspaceError):
        save_skill(project, name="x", steps=[], **FIELDS)


def test_skill_file_without_frontmatter_is_rejected() -> None:
    with pytest.raises(FormatError):
        fmt.parse_skill_meta(
            "# 只有正文\n\n- 一条要点\n", source="项目", path=Path("x")
        )


# ---- T048 沉淀 ----------------------------------------------------------


def test_save_creates_the_skill_file(project: Project) -> None:
    make_skill(project)

    assert project.path(fmt.SKILLS_DIR, "my-skill", fmt.SKILL_FILE).is_file()
    meta = get_skill(project, "my-skill")
    assert meta.source == "项目" and meta.version == "1"


def test_saving_a_duplicate_name_is_refused(project: Project) -> None:
    make_skill(project)
    with pytest.raises(WorkspaceError):
        make_skill(project)


def test_project_skill_overrides_builtin_with_same_name(project: Project) -> None:
    project.apply(
        save_skill(
            project, name="weekly-report", steps=["按我们团队的口径写"], **FIELDS
        )
    )
    assert get_skill(project, "weekly-report").source == "项目"


# ---- T047 三级渐进式加载 ------------------------------------------------


def test_metadata_level_does_not_contain_the_body(project: Project) -> None:
    """会话开始时放进上下文的是元数据——正文不该跟着进去。"""
    make_skill(project)
    line = get_skill(project, "my-skill").one_line()

    assert "my-skill" in line and "口述" in line
    assert "先把口述抄下来" not in line, "步骤要点不该出现在元数据里"
    assert all(
        "先把口述抄下来" not in meta.one_line() for meta in list_skills(project)
    )


def test_body_is_read_only_when_asked(project: Project) -> None:
    make_skill(project)
    body = load_skill(project, "my-skill")

    assert "先把口述抄下来" in body
    assert "description:" not in body, "正文里不该再带上元数据"


def test_reference_files_are_the_third_level(project: Project) -> None:
    make_skill(project)
    reference = project.path(fmt.SKILLS_DIR, "my-skill", fmt.SKILL_REFERENCE_DIR)
    reference.mkdir(parents=True, exist_ok=True)
    (reference / "example.md").write_text("这是一份样例。\n", encoding="utf-8")

    assert "样例" in load_reference(project, "my-skill", "example.md")
    with pytest.raises(WorkspaceError):
        load_reference(project, "my-skill", "没有这个文件.md")


# ---- T049 匹配与建议 ----------------------------------------------------


def test_suggestion_matches_by_meaning_not_exact_words(project: Project) -> None:
    suggestions = suggest_skills(
        project, "帮我把这段需求过一遍，看有没有没法验收的", now=NOW
    )

    assert suggestions and suggestions[0].meta.name == "requirement-review"
    assert suggestions[0].score >= 2 and suggestions[0].reason


def test_unrelated_text_gets_no_suggestion(project: Project) -> None:
    assert suggest_skills(project, "今天天气不错", now=NOW) == []


def test_declined_skill_stops_being_suggested_for_a_while(project: Project) -> None:
    text = "评审一下这份需求规范"
    assert suggest_skills(project, text, now=NOW), "先确认它本来会被建议"

    project.apply(record_usage(project, "requirement-review", "declined", moment=NOW))
    assert suggest_skills(project, text, now=NOW) == [], "拒绝之后不该马上又来"

    later = NOW + dt.timedelta(days=DECLINE_COOLDOWN_DAYS + 1)
    assert suggest_skills(project, text, now=later), "过了冷却期可以再提"


def test_accepting_does_not_stop_suggestions(project: Project) -> None:
    text = "评审一下这份需求规范"
    project.apply(record_usage(project, "requirement-review", "accepted", moment=NOW))

    assert suggest_skills(project, text, now=NOW)


# ---- T050 采纳记录 ------------------------------------------------------


def test_usage_is_counted_per_skill(project: Project) -> None:
    project.apply(record_usage(project, "weekly-report", "accepted", moment=NOW))
    project.apply(record_usage(project, "weekly-report", "declined", moment=NOW))
    project.apply(record_usage(project, "risk-retro", "accepted", moment=NOW))

    summary = usage_summary(project)
    assert summary["weekly-report"] == {"accepted": 1, "declined": 1}
    assert summary["risk-retro"]["declined"] == 0


def test_unknown_skill_cannot_be_recorded(project: Project) -> None:
    with pytest.raises(WorkspaceError):
        record_usage(project, "没有这个能力单元", "accepted")


def test_bad_outcome_is_refused(project: Project) -> None:
    with pytest.raises(WorkspaceError):
        record_usage(project, "risk-retro", "随便写的")


# ---- T051 修订 ----------------------------------------------------------


def test_revise_bumps_version_and_keeps_usage_history(project: Project) -> None:
    make_skill(project)
    project.apply(record_usage(project, "my-skill", "accepted", moment=NOW))

    project.apply(
        revise_skill(project, "my-skill", version="2", steps=["换成新的三步法"])
    )

    assert get_skill(project, "my-skill").version == "2"
    assert "换成新的三步法" in load_skill(project, "my-skill")
    assert usage_summary(project)["my-skill"]["accepted"] == 1, "修订不该动使用历史"


def test_builtin_skill_cannot_be_edited_in_place(project: Project) -> None:
    with pytest.raises(WorkspaceError) as excinfo:
        revise_skill(project, "risk-retro", version="9")
    assert "内置" in str(excinfo.value)
