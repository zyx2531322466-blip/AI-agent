"""金样本回放（T017）。

固定输入 + 一份**录制**的真实模型输出。回放它，就能在没有网络、不花钱的情况下
验证整条链路：清理 → 校验 → 组装 → 落盘，并守住 SC-001。

录制怎么来的、什么时候重做，见 evals/README.md。
"""

from __future__ import annotations

import datetime as dt
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
from pm_agent.stages.work import (
    WorkDraft,
    check_draft as check_work_draft,
    pick_task,
    prepare_work_change,
)
from pm_agent.harness.session import session_brief
from pm_agent.harness.report import build_report, check_report
from pm_agent.stages import announce, get_stage
from pm_agent.workspace import format as fmt
from pm_agent.workspace.store import Project, create_project
from pm_agent.workspace.tasks import coverage_gaps
from pm_agent.workspace.skills import record_usage, suggest_skills, usage_summary
from pm_agent.workspace.skills import get_skill, share_skill
from pm_agent.harness.projects import overview
from pm_agent.harness.risks import detect_risks
from pm_agent.workspace.handoff import read_latest_handoff
from pm_agent.workspace.transfer import build_demo
from pm_agent.harness.impact import analyze_change_impact

NOW_TS = dt.datetime(2026, 9, 23, 17, 0, 0)

CASE_DIR = Path(__file__).parents[1] / "evals" / "specify"
CASE_FILE = CASE_DIR / "case-001.yaml"
RECORDING = CASE_DIR / "case-001.recorded.md"

TASK_CASE_DIR = Path(__file__).parents[1] / "evals" / "tasks"
RESUME_CASE_DIR = Path(__file__).parents[1] / "evals" / "resume" / "case-001"
EXPLAIN_CASE = Path(__file__).parents[1] / "evals" / "explain" / "case-001.yaml"
REPO_SPEC = Path(__file__).parents[1] / "spec.md"
REPORT_CASE_DIR = Path(__file__).parents[1] / "evals" / "report" / "case-001"
SKILL_CASE = Path(__file__).parents[1] / "evals" / "skills" / "case-001.yaml"
PROJECT_CASE = Path(__file__).parents[1] / "evals" / "projects" / "case-001.yaml"
DEMO_CASE = Path(__file__).parents[1] / "evals" / "demo" / "case-001.yaml"
IMPACT_CASE = Path(__file__).parents[1] / "evals" / "impact" / "case-001.yaml"
WORK_CASE_DIR = Path(__file__).parents[1] / "evals" / "work"


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


def test_resume_case_satisfies_sc003(tmp_path: Path) -> None:
    """SC-003：中断 7 天后重新开始，不追问背景就能说清状态与下一步。

    夹具是一个"做到一半、停了 7 天"的项目：交接记录写于 2026-09-16，
    任务表停在 T002 进行中、留了结论。
    """
    project = create_project(tmp_path / "resume", name="待办清单", goal="记待办").project
    for relative in ("spec.md", "tasks.md"):
        project.apply(
            project.prepare_write(
                relative,
                (RESUME_CASE_DIR / relative).read_text(encoding="utf-8"),
                reason="铺测试状态",
            )
        )
    session_file = RESUME_CASE_DIR / "sessions" / "2026-09-16-09-00-00.md"
    project.path("sessions", session_file.name).write_bytes(
        session_file.read_bytes()
    )

    brief = session_brief(project)
    text = brief.render()

    assert brief.ok, "这份状态里不该有需要裁决的冲突：\n" + text
    assert brief.last_handoff is not None
    assert "第一次会话" not in text, "接上了就不该说自己是第一次"

    # 上次到哪：三要素都要能看到，否则就得追问背景
    assert "把待办表建起来" in text, "上轮做了什么"
    assert "先把 T002 收尾" in text, "下一步建议"
    assert "标题最长允许多少字" in text, "未决问题"

    # 现在到哪：进行中的任务与它留下的结论
    assert [task.id for task in brief.active] == ["T002"]
    assert "校验放在写入口更省事" in text, "中间结论要能看到，否则得重讲背景"

    # 现在能动手：T001 完成、T002 进行中，所以 T003 就绪（P1 排在 P2 前面）
    assert [task.id for task in brief.ready] == ["T003", "T002"]


def test_explain_case_satisfies_sc011() -> None:
    """SC-011：随便挑一个阶段问「为什么」，结论在系统内就能找到，不用查外部资料。"""
    case = yaml.safe_load(EXPLAIN_CASE.read_text(encoding="utf-8"))
    known = {item.id for item in fmt.parse_requirements(REPO_SPEC.read_text(encoding="utf-8"))}

    for key in case["stages"]:
        text = announce(key, explain=True)
        for line in case["required_lines"]:
            assert line in text, f"{key} 的讲解里缺「{line}」"

        # 依据里引用的需求必须真的存在——"能在系统内找到"就是这条
        for requirement_id in fmt.FR_ID_RE.findall(get_stage(key).basis):
            assert requirement_id in known, (
                f"{key} 的依据引用了 {requirement_id}，但本仓库 spec.md 里没有它"
            )


def test_report_case_satisfies_sc004(tmp_path: Path) -> None:
    """SC-004：进度汇报里「无来源的成果描述」数量为 0。

    夹具刻意触发多类风险（超期、长期无进展、依赖被阻塞、返工），
    所以这份汇报连风险条目也必须带来源。
    """
    project = create_project(tmp_path / "report-case", name="待办清单", goal="记待办").project
    for relative in ("spec.md", "tasks.md"):
        project.apply(
            project.prepare_write(
                relative,
                (REPORT_CASE_DIR / relative).read_text(encoding="utf-8"),
                reason="铺测试状态",
            )
        )

    report = build_report(
        project, audience="上级", now=dt.datetime(2026, 9, 23, 17, 0, 0)
    )
    text = report.render()

    for section in ("已完成", "进行中", "阻塞", "风险"):
        assert f"## {section}" in text, f"缺了「{section}」这一类"

    assert check_report(report) == [], "SC-004：不该有无来源条目"
    assert text.count("（来源：") == len(report.items), "每一条都要带着来源出现"
    assert any(item.inference == "推测" for item in report.items), "这份夹具里应当有推测类"


def test_skill_case_satisfies_sc005(tmp_path: Path) -> None:
    """SC-005：能力单元能在**多个不同任务**里被建议复用，且采纳与拒绝都有记录。"""
    case = yaml.safe_load(SKILL_CASE.read_text(encoding="utf-8"))
    project = create_project(tmp_path / "skill-case", name="待办清单", goal="记待办").project

    hit = 0
    for text in case["tasks"]:
        names = {item.meta.name for item in suggest_skills(project, text, now=NOW_TS)}
        if case["expected_skill"] in names:
            hit += 1
    assert hit >= case["min_tasks"], f"只在 {hit} 个任务里被建议，不够"

    # 采纳与拒绝都要留痕
    project.apply(record_usage(project, case["expected_skill"], "accepted", moment=NOW_TS))
    project.apply(record_usage(project, "risk-retro", "declined", moment=NOW_TS))
    summary = usage_summary(project)
    assert summary[case["expected_skill"]]["accepted"] == 1
    assert summary["risk-retro"]["declined"] == 1


def test_projects_case_satisfies_sc009(tmp_path: Path) -> None:
    """SC-009：两个项目并行运行时，任一项目的数据都不出现在另一个项目里。"""
    case = yaml.safe_load(PROJECT_CASE.read_text(encoding="utf-8"))
    shelf = tmp_path / "项目架"
    built = []
    for item in case["projects"]:
        project = create_project(
            shelf / item["name"], name=item["name"], goal=item["goal"]
        ).project
        project.apply(
            project.prepare_write(
                fmt.TASKS_FILE,
                f"# {item['name']} 的任务\n\n## M1 · 记录\n\n"
                f"- [ ] **T001**（— / FR-001）{item['task']}。**完成标准**：能跑。"
                "**优先级**：P1。**依赖**：无。\n",
                reason="铺任务",
            )
        )
        built.append(project)

    first, second = built
    first_task, second_task = (item["task"] for item in case["projects"])

    # 抽查：任一项目都看不到另一个项目的内容
    assert first_task in first.read_text(fmt.TASKS_FILE)
    assert first_task not in second.read_text(fmt.TASKS_FILE)
    assert second_task in second.read_text(fmt.TASKS_FILE)
    assert second_task not in first.read_text(fmt.TASKS_FILE)

    # 跨项目共享能力单元：来源不变，目标多了一份自己的
    second.apply(share_skill(first, second, case["shared_skill"]))
    assert get_skill(second, case["shared_skill"]).source == "项目"
    assert get_skill(first, case["shared_skill"]).source == "内置"

    # 总览能同时看到两个
    names = {item.name for item in overview(shelf, now=NOW_TS)}
    assert names == {item["name"] for item in case["projects"]}


def test_recorded_work_satisfies_sc014(tmp_path: Path) -> None:
    """SC-014：让 AI 执行一条任务，产出围绕完成标准与来源需求展开，并留成可追溯的证据。

    录制是 2026-09-24 用真实 DeepSeek 跑出来的一稿（`evals/work/case-001.recorded.md`）：
    回放它，就能在没有网络、不花钱的情况下守住"这条链路还能跑出合格交付物"。
    """
    case = yaml.safe_load((WORK_CASE_DIR / "case-001.yaml").read_text(encoding="utf-8"))
    recorded = (WORK_CASE_DIR / "case-001.recorded.md").read_text(encoding="utf-8")

    project = create_project(
        tmp_path / "work-case",
        name=case["name"],
        goal=case["goal"],
        learning_goals=list(case.get("learning_goals") or []),
    ).project
    project.apply(project.prepare_write(fmt.SPEC_FILE, case["spec"], reason="铺规范"))
    project.apply(project.prepare_write(fmt.TASKS_FILE, case["tasks"], reason="铺任务"))

    task, why = pick_task(project, case["task_id"])
    assert "依赖已满足" in why

    draft = WorkDraft(
        task_id=task.id,
        text=recorded,
        source="录制（evals/work/case-001.recorded.md）",
        requirements=tuple(task.requirements),
    )
    assert check_work_draft(draft) == [], "录制的产出必须是合格交付物"

    project.apply(prepare_work_change(project, task, draft, moment=NOW_TS), moment=NOW_TS)

    # 录制的交付物里有两个文件块（todo.py 与 test_todo.py），它们要真的落进项目
    assert (project.root / "todo.py").is_file()
    assert (project.root / "test_todo.py").is_file()
    assert "def add_todo" in (project.root / "todo.py").read_text(encoding="utf-8")

    written = list((project.root / fmt.EVIDENCE_DIR).glob("*.md"))
    assert len(written) == 1, "交付物要落成一份记录"
    text = written[0].read_text(encoding="utf-8")
    assert "task: T001" in text and "FR-001" in text, "记录要能追溯回任务与来源需求"
    assert "todo.py" in text and "test_todo.py" in text, "记录要写清这次产出了哪些文件"
    for section in ("做法", "交付物", "验证", "没做什么"):
        assert section in text, f"交付物缺了「{section}」"

    # 状态说实话：有产出就不再是"未开始"；但**不是完成**——那要使用者确认（FR-056 / FR-014）
    assert Project.open(project.root).tasks()[0].status == "进行中"
    assert Project.open(project.root).tasks()[0].done is False
    assert fmt.errors(fmt.check_workspace(project.root)) == [], "产出应当通过工作区校验"


def test_demo_case_satisfies_sc010(tmp_path: Path) -> None:
    """SC-010：未受训者能独立走完一次完整流程。

    这里验的是**能不能走通**：引导里写的每一步都得是真命令；
    示范项目得撑得起这几步（有任务、有交接记录、有能出风险或明确说没有的数据）。
    """
    from typer.testing import CliRunner

    from pm_agent.cli import app

    case = yaml.safe_load(DEMO_CASE.read_text(encoding="utf-8"))
    available = set()
    for command in app.registered_commands:
        available.add(command.name or command.callback.__name__.replace("_", "-"))

    for step in case["steps"]:
        assert step["command"] in available, f"引导里写了 {step['command']}，但它不是真命令"

    # 示范项目要撑得起这几步
    demo = build_demo(tmp_path / "试用")
    assert demo.tasks() and demo.requirements()
    assert read_latest_handoff(demo) is not None, "没有交接记录，resume 就没东西可讲"

    # 报告和风险这两步真的跑得出东西
    report = build_report(demo, audience="上级", now=NOW_TS)
    assert check_report(report) == [] and report.items
    assert detect_risks(demo, now=NOW_TS) is not None


def test_impact_case_satisfies_sc006(tmp_path: Path) -> None:
    """SC-006：改一条需求之前，影响面要能列全，无遗漏。"""
    case = yaml.safe_load(IMPACT_CASE.read_text(encoding="utf-8"))
    project = create_project(tmp_path / "impact-case", name="演示", goal="记待办").project
    spec = (
        "---\nstatus: draft\nversion: 1\n---\n\n# 演示 —— 规范\n\n## 4. 功能需求\n\n"
        "- **FR-001** 能记一条待办。\n- **FR-002** 能按天回看。\n"
    )
    tasks = (
        "# 演示 —— 任务清单\n\n## M1 · 记录\n\n"
        "- [x] **T001**（— / FR-001）存下来。**完成标准**：能读回。**优先级**：P1。"
        "**依赖**：无。**状态**：完成。**证据**：提交 abc。\n"
        "- [ ] **T002**（— / FR-001）加校验。**完成标准**：空标题被拒。**优先级**：P2。"
        "**依赖**：T001。**状态**：进行中。\n"
        "- [ ] **T003**（— / FR-001）加编辑。**完成标准**：能改。**优先级**：P2。"
        "**依赖**：T001。**状态**：未开始。\n\n## M2 · 回看\n\n"
        "- [ ] **T004**（— / FR-002）按天列出。**完成标准**：能列。**优先级**：P1。"
        "**依赖**：T002。**状态**：未开始。\n"
        "- [ ] **T005**（— / FR-002）导出回看。**完成标准**：能导。**优先级**：P3。"
        "**依赖**：T004。**状态**：未开始。\n"
    )
    project.apply(project.prepare_write(fmt.SPEC_FILE, spec, reason="铺规范"))
    project.apply(project.prepare_write(fmt.TASKS_FILE, tasks, reason="铺任务"))

    impact = analyze_change_impact(project, case["requirement"])
    assert {t.id for t in impact.tasks} == set(case["direct_tasks"])
    assert {t.id for t in impact.downstream} == set(case["downstream_tasks"]), "连带的也要列出来"
    assert {t.id for t in impact.done_tasks} == set(case["done_tasks"])
    assert impact.needs_review is case["expect_review"]
    assert "建议先重新评审" in impact.render()
