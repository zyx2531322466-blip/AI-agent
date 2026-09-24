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


# ---- 注释不是内容（T072 走查发现） ------------------------------------------
#
# 起因：新建出来的空项目，**它自己的模板注释里那句示例条目**会被当成真条目，
# 于是 `init` 完立刻 `show` 就看到"看起来是需求条目，但编号不合规"。
# 那句话是我们自己写进模板的示例——一份刚建的项目不该一上来就报自己的错。


def test_commented_out_requirement_is_not_an_entry() -> None:
    """注释掉的条目就是不存在，不能算条目，也不能报"编号不合规"。"""
    text = (
        "# 规范\n\n## 4. 功能需求\n\n"
        "<!-- 示例（随便写点什么）：\n\n"
        "   - **FR-001** 系统 MUST ……\n"
        "   - **FR-1** 位数不对\n\n"
        "把示例换成你自己的第一条需求。 -->\n\n"
        "- **FR-002** 真的条目。\n"
    )

    assert [item.id for item in fmt.parse_requirements(text)] == ["FR-002"]
    assert fmt.check_requirements(text) == []


def test_commented_out_requirement_does_not_shift_line_numbers() -> None:
    """抹掉注释不能让后面的行号偏移——行号要用来定点改文件。"""
    text = "<!-- 注释\n跨了两行 -->\n- **FR-001** 第一条。\n"

    item = fmt.parse_requirements(text)[0]
    assert (item.id, item.line) == ("FR-001", 3)
    assert text.split("\n")[item.line - 1] == "- **FR-001** 第一条。"


def test_comment_inside_a_line_keeps_the_entry() -> None:
    """行内注释只抹掉注释本身，条目正文照旧。"""
    text = "- **FR-001** 能记一条待办。<!-- 这里补充说明 -->\n"

    assert fmt.parse_requirements(text)[0].text == "能记一条待办。"


def test_comment_can_hide_a_clarification_and_a_task() -> None:
    """待澄清与任务走同一套规则：注释掉就不算。"""
    spec = "<!-- - 示例：[待澄清] 这条是示例不是问题 -->\n- **FR-001** 真条目。\n"
    tasks = "<!-- - [ ] **T999** 示例任务。 -->\n- [ ] **T001** 真任务。**完成标准**：能跑。**优先级**：P1。**依赖**：无。\n"

    assert fmt.parse_clarifications(spec) == []
    assert [task.id for task in fmt.parse_tasks(tasks)] == ["T001"]
    assert fmt.check_tasks(tasks) == []


def test_malformed_entries_outside_comments_are_still_reported() -> None:
    """注释规则不能顺手把该报的也吞掉。"""
    problems = fmt.check_requirements("<!-- 注释里的 - **FR-1** -->\n- **FR-1** 位数不对\n")

    assert any("编号不合规" in problem.message for problem in problems)
