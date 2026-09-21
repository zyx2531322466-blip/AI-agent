"""格式校验的测试（T003 / T004）。

校验规则是这个项目的"看门人"：它决定使用者手工写坏的东西
是被清楚地指出来，还是被程序默默接受。
"""

from __future__ import annotations

import pytest

from pm_agent.workspace import format as fmt


def valid_meta() -> dict:
    return {
        "schema_version": "1",
        "name": "示例项目",
        "goal": "验证格式校验能不能正常工作",
        "created": "2026-09-13",
        "status": "active",
        "learning_goals": ["学会把需求拆成任务"],
    }


def messages(problems: list[fmt.Problem]) -> str:
    return " / ".join(item.message for item in problems)


def test_valid_meta_has_no_problems() -> None:
    assert fmt.validate_meta(valid_meta()) == []


def test_meta_from_dict_round_trip() -> None:
    meta = fmt.meta_from_dict(valid_meta())
    assert meta.name == "示例项目"
    assert meta.learning_goals == ["学会把需求拆成任务"]
    assert meta.to_dict() == valid_meta()


@pytest.mark.parametrize("field", ["schema_version", "name", "goal", "created", "status"])
def test_missing_required_field_is_reported(field: str) -> None:
    data = valid_meta()
    del data[field]
    problems = fmt.validate_meta(data)
    assert fmt.errors(problems), f"缺少 {field} 应该被报为错误"
    assert field in messages(problems)


def test_bad_date_is_reported_with_fix_hint() -> None:
    data = valid_meta()
    data["created"] = "2026/09/13"
    problems = fmt.errors(fmt.validate_meta(data))
    assert problems and "created" in messages(problems)
    assert "YYYY-MM-DD" in problems[0].fix


def test_unquoted_yaml_date_is_accepted() -> None:
    """回归：YAML 会把未加引号的 2026-09-13 解析成日期对象。

    如果只接受字符串，使用者手工写下的日期就会被判成非法——
    而"手工能改"是原则 2 的底线。
    """
    import datetime as dt

    data = valid_meta()
    data["created"] = dt.date(2026, 9, 13)
    assert fmt.validate_meta(data) == []
    assert fmt.meta_from_dict(data).created == "2026-09-13"


def test_bad_status_lists_allowed_values() -> None:
    data = valid_meta()
    data["status"] = "working"
    problems = fmt.errors(fmt.validate_meta(data))
    assert problems
    assert "active" in problems[0].fix and "paused" in problems[0].fix


def test_unknown_schema_version_is_rejected() -> None:
    data = valid_meta()
    data["schema_version"] = "99"
    assert fmt.errors(fmt.validate_meta(data))


def test_empty_learning_goals_is_only_a_warning() -> None:
    data = valid_meta()
    data["learning_goals"] = []
    problems = fmt.validate_meta(data)
    assert fmt.errors(problems) == []
    assert fmt.warnings(problems)


def test_learning_goals_must_be_list() -> None:
    data = valid_meta()
    data["learning_goals"] = "学会拆任务"
    assert fmt.errors(fmt.validate_meta(data))


def test_top_level_must_be_mapping() -> None:
    assert fmt.errors(fmt.validate_meta(["不是字典"]))


def test_check_workspace_on_missing_directory() -> None:
    problems = fmt.check_workspace(__import__("pathlib").Path("不存在的目录-xyz"))
    assert problems and "目录不存在" in problems[0].message
