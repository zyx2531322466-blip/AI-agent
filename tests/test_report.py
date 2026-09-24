"""汇报与风险的测试（T038 ~ T044）。

三条最要紧的性质：

- **五类风险都能算出来**，而且**事实与推测分开标**（FR-021 / FR-024）；
- **没有来源的条目一律打回**（FR-031）——这不是提醒，是发不出去；
- **没进展就说没进展**，不编填充内容（FR-033）。
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pm_agent.cli import app
from pm_agent.errors import WorkspaceError
from pm_agent.harness.report import Report, ReportItem, build_report, check_report
from pm_agent.harness.risks import acknowledge_risk, detect_risks
from pm_agent.workspace import format as fmt
from pm_agent.workspace.store import Project, create_project

NOW = dt.datetime(2026, 9, 23, 17, 0, 0)

SPEC = """---
status: draft
version: 1
---

# 演示项目 —— 功能需求规范

## 4. 功能需求

- **FR-001** 能记一条待办。
- **FR-002** 能按天回看。
"""

#: 一个刻意触发多类风险的任务表
TASKS = """# 演示项目 —— 任务清单

## M1 · 记录

- [x] **T001**（— / FR-001）把待办存下来。**完成标准**：能读回。**优先级**：P1。**依赖**：无。**状态**：完成。**更新**：2026-09-20 10:00。**证据**：提交 a1b2c3d。
- [ ] **T002**（— / FR-001）加标题校验。**完成标准**：空标题被拒。**优先级**：P2。**依赖**：T001。**状态**：进行中。**更新**：2026-09-10 09:00。**结论**：校验放写入口。
- [ ] **T003**（— / FR-002）做回看页。**完成标准**：能按天列出。**优先级**：P1。**依赖**：T004。**状态**：未开始。

## M2 · 收尾

- [ ] **T004**（— / FR-002）导出结果。**完成标准**：能导出。**优先级**：P2。**依赖**：T002。**状态**：阻塞。**更新**：2026-09-15 14:00。**截止**：2026-09-18。
- [ ] **T005**（— / FR-002）加统计。**完成标准**：能按周统计。**优先级**：P3。**依赖**：T003。**状态**：未开始。
- [ ] **T006**（— / FR-001）做标题长度上限。**完成标准**：超长被拒。**优先级**：P3。**依赖**：T002。**状态**：进行中。**证据**：提交 def456。
"""

runner = CliRunner()


@pytest.fixture
def project(tmp_path: Path) -> Project:
    project = create_project(tmp_path / "demo", name="演示项目", goal="记待办").project
    project.apply(project.prepare_write(fmt.SPEC_FILE, SPEC, reason="铺规范"))
    project.apply(project.prepare_write(fmt.TASKS_FILE, TASKS, reason="铺任务"))
    return project


# ---- T042 风险五类 ------------------------------------------------------


def risk_kinds(project: Project) -> dict[str, list[str]]:
    grouped: dict[str, list[str]] = {}
    for risk in detect_risks(project, now=NOW):
        grouped.setdefault(risk.kind, []).append(risk.subject)
    return grouped


def test_overdue_is_detected(project: Project) -> None:
    assert "T004" in risk_kinds(project)["超期"]


def test_stale_is_detected(project: Project) -> None:
    assert "T002" in risk_kinds(project)["长期无进展"]


def test_blocked_dependency_is_detected(project: Project) -> None:
    """T003 直接依赖阻塞中的 T004。"""
    assert "T003" in risk_kinds(project)["依赖被阻塞"]


def test_rework_is_detected(project: Project) -> None:
    """T006 有证据却不是完成态——像是返工。"""
    assert "T006" in risk_kinds(project)["返工或验收未通过"]


def test_scope_creep_is_detected(project: Project) -> None:
    """范围蔓延靠对比最早的 spec 快照——所以在有历史之后才成立。"""
    text = project.read_text(fmt.SPEC_FILE)
    for index in range(3, 3 + 6):
        text += f"- **FR-{index:03d}** 第 {index} 条需求。\n"
    project.apply(project.prepare_write(fmt.SPEC_FILE, text, reason="扩规范"))

    assert "规范" in risk_kinds(project)["范围蔓延"]


def test_five_kinds_are_all_reachable(project: Project) -> None:
    """五类都要能识别——这是 FR-021 的字面要求。"""
    text = project.read_text(fmt.SPEC_FILE)
    for index in range(3, 3 + 6):
        text += f"- **FR-{index:03d}** 第 {index} 条需求。\n"
    project.apply(project.prepare_write(fmt.SPEC_FILE, text, reason="扩规范"))

    kinds = set(risk_kinds(project))
    assert kinds == {
        "超期",
        "长期无进展",
        "依赖被阻塞",
        "范围蔓延",
        "返工或验收未通过",
    }


# ---- T044 事实与推测 ----------------------------------------------------


def test_indirect_impact_is_labelled_as_a_guess(project: Project) -> None:
    """T005 间接依赖阻塞中的 T004——这是顺着依赖链推出来的，标推测。"""
    risks = [risk for risk in detect_risks(project, now=NOW) if risk.subject == "T005"]

    assert risks, "T005 应当有一条间接影响"
    assert all(risk.inference == "推测" for risk in risks)
    assert "间接依赖" in risks[0].text


def test_direct_risks_are_labelled_as_facts(project: Project) -> None:
    direct = [
        risk
        for risk in detect_risks(project, now=NOW)
        if risk.kind in ("超期", "长期无进展", "返工或验收未通过")
    ]
    assert direct and all(risk.inference == "事实" for risk in direct)


def test_every_risk_carries_a_basis(project: Project) -> None:
    for risk in detect_risks(project, now=NOW):
        assert risk.basis.strip(), f"{risk.key} 没有依据"


# ---- T043 预警处置 ------------------------------------------------------


def test_acknowledged_risk_stops_being_reported(project: Project) -> None:
    target = detect_risks(project, now=NOW)[0].key

    project.apply(acknowledge_risk(project, target))

    remaining = {risk.key for risk in detect_risks(project, now=NOW)}
    assert target not in remaining, "处置过的预警不该重复提醒"
    everything = {risk.key for risk in detect_risks(project, now=NOW, include_acknowledged=True)}
    assert target in everything, "--all 还能看到它"


def test_unknown_risk_cannot_be_acknowledged(project: Project) -> None:
    with pytest.raises(WorkspaceError) as excinfo:
        acknowledge_risk(project, "超期:T999")
    assert "没有这条预警" in str(excinfo.value)


# ---- T038 四类分组 ------------------------------------------------------


def test_report_has_all_four_sections(project: Project) -> None:
    report = build_report(project, now=NOW)

    assert [item.section for item in report.items if item.section == "已完成"]
    assert report.section("进行中")
    assert report.section("阻塞")
    assert report.section("风险")


def test_report_summary_counts(project: Project) -> None:
    summary = build_report(project, now=NOW).summary
    assert "完成 1 条" in summary and "风险" in summary


# ---- T039 每条标来源 ----------------------------------------------------


def test_every_item_has_a_source(project: Project) -> None:
    report = build_report(project, now=NOW)

    assert check_report(report) == [], "生成出来的汇报不该有无来源条目"
    assert "（来源：" in report.render()


def test_report_without_source_is_sent_back() -> None:
    """无法核查的成果描述——打回，不发出去。"""
    bad = Report(
        project="演示项目",
        audience="自己",
        since="上次交接",
        items=(ReportItem(section="已完成", text="做完了核心功能", source=""),),
    )

    problems = check_report(bad)
    assert problems and "没有来源" in problems[0].message


# ---- T040 按读者调详略 --------------------------------------------------


@pytest.mark.parametrize("audience", ["自己", "团队", "上级"])
def test_conclusion_and_risks_survive_audience_switch(project: Project, audience: str) -> None:
    report = build_report(project, audience=audience, now=NOW)
    text = report.render()

    assert "结论：" in text, "换读者不能把结论弄丢"
    assert "## 风险" in text and "T004" in text, "风险不能因为读者不同就消失"
    assert "（来源：" in text, "来源也不能省（FR-031）"


def test_boss_view_is_shorter_than_self_view(project: Project) -> None:
    self_view = build_report(project, audience="自己", now=NOW).render()
    boss_view = build_report(project, audience="上级", now=NOW).render()

    assert "上次留下的结论：" in self_view, "给自己看要细节"
    assert "上次留下的结论：" not in boss_view, "给上级看不展开细节"


# ---- T041 无进展如实说 --------------------------------------------------


def test_empty_period_says_so(tmp_path: Path) -> None:
    bare = create_project(tmp_path / "bare", name="空项目", goal="g").project
    project = bare
    project.apply(project.prepare_write(fmt.SPEC_FILE, SPEC, reason="铺规范"))
    project.apply(
        project.prepare_write(
            fmt.TASKS_FILE,
            "# 任务\n\n## M1 · 记录\n\n"
            "- [ ] **T001**（— / FR-001）还没动。**完成标准**：能读回。"
            "**优先级**：P1。**依赖**：无。**状态**：未开始。\n",
            reason="铺一个没进展的任务",
        )
    )

    text = build_report(project, now=NOW).render()
    assert "本周期没有已完成的任务" in text
    assert "没有实质进展" in text


# ---- 命令行 ------------------------------------------------------------


def test_cli_risks_and_report(tmp_path: Path) -> None:
    target = tmp_path / "汇报项目"
    runner.invoke(app, ["init", str(target), "--name", "汇报项目", "--goal", "g", "--no-git"])
    project = Project.open(target)
    project.apply(project.prepare_write(fmt.SPEC_FILE, SPEC, reason="铺规范"))
    project.apply(project.prepare_write(fmt.TASKS_FILE, TASKS, reason="铺任务"))

    listed = runner.invoke(app, ["risks", str(target)])
    assert listed.exit_code == 0, listed.stdout
    assert "超期" in listed.stdout and "事实" in listed.stdout

    key = f"超期:T004"
    acked = runner.invoke(app, ["risks", str(target), "--ack", key])
    assert acked.exit_code == 0, acked.stdout
    assert "已处置" in acked.stdout

    after = runner.invoke(app, ["risks", str(target)])
    assert "的截止日是 2026-09-18" not in after.stdout, "处置过的那条不该再出现"
    assert "T004" in after.stdout, "但同一对象上的其它风险（长期无进展）还该在"

    reported = runner.invoke(app, ["report", str(target), "--audience", "上级"])
    assert reported.exit_code == 0, reported.stdout
    assert "结论：" in reported.stdout and "## 风险" in reported.stdout
