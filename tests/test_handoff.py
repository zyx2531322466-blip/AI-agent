"""交接记录的测试（T007）。

完成标准点名的是"**一次空会话也能产出一份合法交接记录**"，
所以"空会话"和"第一份记录（没有前驱）"这两个边界各有一条测试守着。
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from pm_agent.errors import FormatError, WorkspaceError
from pm_agent.workspace import create_project
from pm_agent.workspace import format as fmt
from pm_agent.workspace.handoff import (
    SESSIONS_DIR,
    Handoff,
    list_handoffs,
    new_handoff,
    parse_handoff,
    read_handoff,
    read_latest_handoff,
    render_handoff,
    write_handoff,
)
from pm_agent.workspace.store import Project

MOMENT = dt.datetime(2026, 9, 22, 21, 17, 4)


@pytest.fixture
def project(tmp_path: Path) -> Project:
    return create_project(tmp_path / "demo", name="演示项目", goal="验证交接记录").project


def make(project: Project, **overrides: object) -> Handoff:
    fields: dict[str, object] = {
        "state": "进行中：T007",
        "next_steps": "补测试",
        "open_questions": "无",
        "did": "写完了 handoff.py",
        "moment": MOMENT,
    }
    fields.update(overrides)
    return new_handoff(project, **fields)  # type: ignore[arg-type]


def write_raw(project: Project, session_key: str, text: str) -> Path:
    """绕开校验直接写文件，用来模拟"使用者手工编辑"。"""
    path = project.path(SESSIONS_DIR, f"{session_key}.md")
    path.write_text(text, encoding="utf-8")
    return path


# ---- 写入与读回 --------------------------------------------------------


def test_first_record_lands_in_sessions_and_has_no_prev(project: Project) -> None:
    handoff = make(project)
    path = write_handoff(project, handoff)

    assert path.parent.name == SESSIONS_DIR
    assert path.name == f"{handoff.session}.md"
    assert handoff.prev is None, "第一份记录没有前驱"
    assert handoff.created == "2026-09-22"


def test_rendered_record_has_the_three_required_sections(project: Project) -> None:
    text = render_handoff(make(project))
    for title in ("当前状态", "下一步建议", "未决问题"):
        assert f"## {title}" in text, f"缺少 FR-016 要求的「{title}」段落"


def test_round_trip_keeps_every_field(project: Project) -> None:
    handoff = make(project)
    write_handoff(project, handoff)
    again = read_handoff(project, handoff.session)

    assert again == handoff


def test_empty_session_is_still_valid(project: Project) -> None:
    """T007 的完成标准：什么都没做的一轮，也要能产出一份合法记录。"""
    handoff = make(
        project,
        state="无进展：与上次相同",
        next_steps="与上次相同",
        open_questions="无新增",
        did="无。本次会话只重建了状态，没有产生改动。",
    )
    write_handoff(project, handoff)

    again = read_handoff(project, handoff.session)
    assert again.state.startswith("无进展")
    assert again.did.startswith("无。")


def test_read_latest_returns_none_before_any_record(project: Project) -> None:
    assert read_latest_handoff(project) is None


def test_prev_points_to_the_previous_record(project: Project) -> None:
    first = make(project)
    write_handoff(project, first)

    second = new_handoff(
        project,
        state="进行中：T008",
        next_steps="写预览",
        open_questions="无",
        moment=MOMENT + dt.timedelta(minutes=5),
    )
    assert second.prev == first.session
    write_handoff(project, second)

    assert read_latest_handoff(project) == second


def test_same_second_does_not_overwrite(project: Project) -> None:
    """同一秒连写两份时，会话键往后挪一秒，而不是加 -1 后缀。"""
    first = make(project)
    write_handoff(project, first)
    second = make(project)  # 同一个 moment

    assert second.session != first.session
    write_handoff(project, second)
    assert len(list_handoffs(project)) == 2


def test_refuses_to_overwrite_existing_record(project: Project) -> None:
    handoff = make(project)
    write_handoff(project, handoff)
    with pytest.raises(FormatError) as excinfo:
        write_handoff(project, handoff)
    assert "拒绝覆盖" in str(excinfo.value)


def test_new_handoff_survives_a_corrupt_previous_record(project: Project) -> None:
    """上一份坏了，不该拦住你写新的——读校验与写门禁是两件事。"""
    first = make(project)
    write_handoff(project, first)
    write_raw(project, first.session, "这不是一份合法记录\n")

    # 读它必须报错（这是读取路径的职责，不能假装没事）
    with pytest.raises(FormatError):
        read_handoff(project, first.session)

    # 但写新记录不该被旧记录绑架，而且 prev 照样指得对
    second = new_handoff(
        project,
        state="s",
        next_steps="n",
        open_questions="o",
        moment=MOMENT + dt.timedelta(minutes=1),
    )
    assert second.prev == first.session
    write_handoff(project, second)


# ---- 校验 --------------------------------------------------------------


@pytest.mark.parametrize("field", ["state", "next_steps", "open_questions"])
def test_missing_required_section_is_rejected(project: Project, field: str) -> None:
    with pytest.raises(FormatError) as excinfo:
        make(project, **{field: "   "})
    assert "FR-016" in str(excinfo.value)


def test_invalid_status_is_rejected_and_lists_options(project: Project) -> None:
    with pytest.raises(FormatError) as excinfo:
        make(project, status="随便乱写的状态")
    message = str(excinfo.value)
    for value in fmt.SESSION_STATUSES:
        assert value in message, "报错时要列出合法取值"


def test_session_must_match_filename(project: Project) -> None:
    """手工把 frontmatter 里的 session 改掉，读的时候必须报出来。"""
    handoff = make(project)
    write_handoff(project, handoff)
    text = project.read_text(SESSIONS_DIR, f"{handoff.session}.md")
    write_raw(project, handoff.session, text.replace(handoff.session, "2020-01-01-00-00-00", 1))

    with pytest.raises(FormatError) as excinfo:
        read_handoff(project, handoff.session)
    assert "不一致" in str(excinfo.value)


def test_missing_frontmatter_is_rejected(project: Project) -> None:
    write_raw(project, "2026-09-22-21-17-04", "# 只有正文\n\n没有 frontmatter\n")
    with pytest.raises(FormatError) as excinfo:
        read_handoff(project, "2026-09-22-21-17-04")
    assert "frontmatter" in str(excinfo.value)


def test_hand_written_empty_prev_becomes_none(project: Project) -> None:
    """回归：手写 `prev:`（不写值）时 YAML 给 None，不能变成字符串 "None"。"""
    session = "2026-09-22-21-17-04"
    write_raw(
        project,
        session,
        "---\n"
        f"session: {session}\n"
        "created: 2026-09-22\n"
        "project: 演示项目\n"
        "status: ok\n"
        "prev:\n"
        "---\n\n"
        "# 交接记录\n\n"
        "## 当前状态\n\n无进展\n\n"
        "## 下一步建议\n\n继续\n\n"
        "## 未决问题\n\n无\n",
    )
    parsed = parse_handoff(project.read_text(SESSIONS_DIR, f"{session}.md"), session_key=session)
    assert parsed.prev is None


def test_unknown_section_title_is_reported(project: Project) -> None:
    """标题打错时报"认不出的标题"，而不是只说"缺内容"——否则把人引到错误的地方。"""
    session = "2026-09-22-21-17-04"
    write_raw(
        project,
        session,
        "---\n"
        f"session: {session}\n"
        "created: 2026-09-22\n"
        "project: 演示项目\n"
        "status: ok\n"
        "---\n\n"
        "# 交接记录\n\n"
        "## 目前状态\n\n进行中\n\n"  # 标题写错了，应当是「当前状态」
        "## 下一步建议\n\n继续\n\n"
        "## 未决问题\n\n无\n",
    )

    with pytest.raises(FormatError) as excinfo:
        read_handoff(project, session)

    message = str(excinfo.value)
    assert "认不出的段落标题" in message
    assert "目前状态" in message
    assert "当前状态" in message, "报错时要顺便列出可用标题"


def test_hand_edited_status_is_read_back(project: Project) -> None:
    """数据属于使用者：手工改一个字段后，程序仍能正确读回。"""
    handoff = make(project)
    write_handoff(project, handoff)
    path = project.path(SESSIONS_DIR, f"{handoff.session}.md")
    path.write_text(
        path.read_text(encoding="utf-8").replace("status: ok", "status: conflict"),
        encoding="utf-8",
    )

    assert read_handoff(project, handoff.session).status == "conflict"


# ---- 列表 --------------------------------------------------------------


def test_list_returns_newest_first_and_ignores_other_files(project: Project) -> None:
    first = make(project)
    write_handoff(project, first)
    second = new_handoff(
        project,
        state="s",
        next_steps="n",
        open_questions="o",
        moment=MOMENT + dt.timedelta(hours=1),
    )
    write_handoff(project, second)

    (project.path(SESSIONS_DIR) / "README.md").write_text("不是交接记录", encoding="utf-8")

    names = [path.stem for path in list_handoffs(project)]
    assert names == [second.session, first.session]


def test_read_handoff_reports_missing_record(project: Project) -> None:
    with pytest.raises(WorkspaceError) as excinfo:
        read_handoff(project, "2026-09-22-21-17-04")
    assert "找不到" in str(excinfo.value)
