"""让 AI 执行任务（T078 / T080，FR-053）。

这条命令最要紧的四件事，各由一条测试守着：

1. **上下文来自项目**：任务、来源需求、相关决策、相关能力单元都要真的进提示词；
2. **依赖没完成就别动手**：拒绝，并说清缺哪一条；
3. **产出不合格不许留存**：报错、交回原文、项目一个字节不变；
4. **落盘可撤回**：产出去 evidence/，`undo` 能逐字节退回。

另外守一条边界：它**不改任务状态**——"完成"仍由使用者拍板（FR-014）。
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest

from pm_agent.errors import FormatError
from pm_agent.errors import WorkspaceError
from pm_agent.model.base import Message, ModelProvider
from pm_agent.model.echo import ECHO_MARKER
from pm_agent.stages.work import (
    Artifact,
    PastDelivery,
    WorkDraft,
    check_artifacts,
    check_draft,
    draft_work,
    gather_context,
    past_deliveries,
    parse_deliverables,
    pick_task,
    prepare_work_change,
)
from pm_agent.workspace import format as fmt
from pm_agent.workspace.store import Project, create_project
from pm_agent.workspace.tasks import set_task_status

#: 固定时刻：用来断言产出文件名（时间戳固定才好比对）
NOW = dt.datetime(2026, 9, 24, 10, 30, 0)
#: 一个**远在将来**的时刻：撤回测试要用它，保证"这一条"确实最新。
#: 这里刻意不写"现在加一分钟"——写死时间会让测试过期（曾经踩过：跨到第二天，
#: 昨天的 23:59 反而不如夹具刚写下的那一条新，undo 就撤错了记录）。
LATER = dt.datetime(2030, 1, 1, 9, 0, 0)


def flat(text: str) -> str:
    """把 Rich 折行的输出压成一行再断言——不然长中文句子会被折开，断言假失败。"""
    return "".join(text.split())

SPEC = """---
status: draft
version: 1
---

# 待办清单 —— 功能需求规范

## 4. 功能需求

- **FR-001** 能新增一条待办。
- **FR-002** 能按天回看已完成待办。
"""

TASKS = """# 待办清单 —— 任务清单

## M1 · 记录

- [ ] **T001**（— / FR-001）把待办存下来。**完成标准**：新增一条后能读回。**优先级**：P1。**依赖**：无。**状态**：未开始。
- [ ] **T002**（— / FR-002）做按天回看。**完成标准**：能按天列出已完成待办。**优先级**：P1。**依赖**：T001。**状态**：未开始。
- [ ] **T003**（— / FR-002）给回看加导出。**完成标准**：能导出成文件。**优先级**：P2。**依赖**：T002。**状态**：未开始。
"""


class FakeProvider(ModelProvider):
    """把收到的消息原样记下来，并按需要返回固定文本。"""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.seen: list[Message] = []

    def complete(self, messages: list[Message]) -> str:
        self.seen = list(messages)
        return self.reply

    def describe(self) -> str:
        return "假模型（测试用）"


GOOD_REPLY = """# T001 交付物

## 1. 做法

新增 `todo.py`，用列表存待办，写入口做一次校验。

## 2. 交付物

### 文件：todo.py

```python
# todo.py
items = []


def add(title: str) -> None:
    if not title.strip():
        raise ValueError("标题不能为空")
    items.append({"title": title, "done": False})
```

## 3. 怎么验证

跑 `python -c "from todo import add, items; add('买菜'); print(items)"`，
看到一条 `done: False` 的记录就算通过；再空标题调用一次，应当报错。

## 4. 没做什么

没做持久化（重启就丢），也没做标题长度上限——需求里还是待澄清。
"""


@pytest.fixture
def project(tmp_path: Path) -> Project:
    made = create_project(tmp_path / "待办", name="待办清单", goal="管住每天的待办").project
    made.apply(made.prepare_write(fmt.SPEC_FILE, SPEC, reason="铺规范"))
    made.apply(made.prepare_write(fmt.TASKS_FILE, TASKS, reason="铺任务"))
    return Project.open(made.root)


# ---- 挑任务 ------------------------------------------------------------ #


def test_picks_the_first_ready_task(project: Project) -> None:
    """不指定编号时挑"现在能动手"的那条，并说明为什么是它。"""
    task, why = pick_task(project)

    assert task.id == "T001"
    assert "依赖已满足" in why and "P1" in why


def test_refuses_a_task_whose_dependency_is_unfinished(project: Project) -> None:
    """依赖没完成就别动手，并说清缺哪一条（FR-012）。"""
    with pytest.raises(WorkspaceError) as excinfo:
        pick_task(project, "T002")

    assert "T001" in excinfo.value.hint


def test_refuses_a_task_that_is_already_done(project: Project) -> None:
    project.apply(
        set_task_status(project, "T001", "完成", evidence="提交 abc123")
    )

    with pytest.raises(WorkspaceError) as excinfo:
        pick_task(project, "T001")
    assert "已经完成" in excinfo.value.message


def test_refuses_an_unknown_task_and_lists_the_known_ones(project: Project) -> None:
    with pytest.raises(WorkspaceError) as excinfo:
        pick_task(project, "T099")

    assert "T001" in excinfo.value.hint and "T003" in excinfo.value.hint


def test_says_so_when_nothing_can_be_started(project: Project) -> None:
    """全被依赖卡住时如实说明，而不是硬挑一条。"""
    blocked = project.apply(
        project.prepare_write(
            fmt.TASKS_FILE,
            "# 待办清单 —— 任务清单\n\n## M1 · 记录\n\n"
            "- [ ] **T001**（— / FR-001）先把地基打好。**完成标准**：能读回。**优先级**：P1。"
            "**依赖**：T009。**状态**：未开始。\n",
            reason="造一个悬空依赖",
        )
    )
    assert blocked  # 写入本身允许（悬空依赖只是 warn）

    with pytest.raises(WorkspaceError) as excinfo:
        pick_task(Project.open(project.root))
    assert "没有能动手的任务" in excinfo.value.message


# ---- 上下文装配 -------------------------------------------------------- #


def test_context_comes_from_the_project(project: Project) -> None:
    """任务、来源需求、完成标准都要进提示词——这是它比手工粘贴强的地方。"""
    task, _ = pick_task(project, "T001")
    provider = FakeProvider(GOOD_REPLY)

    draft_work(project, task, provider)

    sent = "\n".join(message.content for message in provider.seen)
    assert "T001" in sent and "把待办存下来" in sent
    assert "新增一条后能读回" in sent            # 完成标准
    assert "FR-001" in sent and "能新增一条待办" in sent  # 来源需求正文
    assert "管住每天的待办" in sent               # 项目目标


def test_context_brings_in_a_matching_skill(project: Project) -> None:
    """相关能力单元的**正文**（第二级）要被带进来，并记下用了哪一个。"""
    project.apply(
        project.prepare_write(
            fmt.TASKS_FILE,
            TASKS.replace("把待办存下来", "逐条评审这份需求规范是否站得住"),
            reason="换成与内置能力单元相关的活",
        )
    )
    task, _ = pick_task(Project.open(project.root), "T001")
    provider = FakeProvider(GOOD_REPLY)

    draft = draft_work(Project.open(project.root), task, provider)

    sent = "\n".join(message.content for message in provider.seen)
    assert "requirement-review" in sent, "命中时要把能力单元正文带进上下文"
    assert "requirement-review" in draft.skills


def test_context_records_which_requirements_were_used(project: Project) -> None:
    task, _ = pick_task(project, "T001")
    context = gather_context(project, task)

    assert context["_requirement_ids"] == "FR-001"
    assert "能新增一条待办" in context["requirements"]


# ---- 产出校验 ---------------------------------------------------------- #


@pytest.mark.parametrize("section", ["做法", "交付物", "验证", "没做什么"])
def test_draft_without_a_section_is_rejected(section: str) -> None:
    """四件事少一件就打回：做法、交付物、怎么验证、没做什么。"""
    text = GOOD_REPLY.replace(section, "随便")

    problems = check_draft(WorkDraft(task_id="T001", text=text))

    assert any(section in problem.message for problem in problems)


def test_echo_output_is_caught() -> None:
    """离线回声会把提示词吐回来，不能让它冒充交付物（FR-037）。"""
    text = GOOD_REPLY + f"\n{ECHO_MARKER}\n"

    problems = check_draft(WorkDraft(task_id="T001", text=text))

    assert any("回声" in problem.message for problem in problems)


def test_chatty_reply_is_rejected() -> None:
    problems = check_draft(WorkDraft(task_id="T001", text="好的，我这就开始做。"))

    assert any("不像是交付物" in problem.message for problem in problems)


# ---- 落盘与撤回 -------------------------------------------------------- #


def test_prepare_writes_the_files_and_a_record(project: Project) -> None:
    """交付物里的文件直接落进项目，同一条变更里再留一份记录。"""
    task, _ = pick_task(project, "T001")
    draft = WorkDraft(task_id="T001", text=GOOD_REPLY, source="假模型", requirements=("FR-001",))

    change = prepare_work_change(project, task, draft, moment=NOW)
    project.apply(change, moment=NOW)

    delivered = project.root / "todo.py"
    assert delivered.is_file(), "交付物里的文件要真的写进项目"
    assert "def add(title: str)" in delivered.read_text(encoding="utf-8")

    record = project.root / fmt.EVIDENCE_DIR / "T001-2026-09-24-10-30-00.md"
    assert record.is_file()
    text = record.read_text(encoding="utf-8")
    assert "task: T001" in text and "FR-001" in text
    assert "files:" in text and "todo.py" in text, "记录里要写清这次产出了哪些文件"
    assert "## 3. 怎么验证" in text


def test_bad_draft_writes_nothing(project: Project) -> None:
    """不合格时项目一个字节不变：没有证据文件、也没有历史记录。"""
    task, _ = pick_task(project, "T001")
    draft = WorkDraft(task_id="T001", text="好的，我来做这件事。")
    history_before = len(list((project.root / fmt.HISTORY_DIR).iterdir()))

    with pytest.raises(FormatError):
        prepare_work_change(project, task, draft, moment=NOW)

    assert list((project.root / fmt.EVIDENCE_DIR).iterdir()) == []
    assert len(list((project.root / fmt.HISTORY_DIR).iterdir())) == history_before


def test_evidence_can_be_undone(project: Project) -> None:
    """一次撤回要把这批文件**一起**退回——不会只退一半。"""
    task, _ = pick_task(project, "T001")
    draft = WorkDraft(task_id="T001", text=GOOD_REPLY)

    project.apply(prepare_work_change(project, task, draft, moment=LATER), moment=LATER)
    assert (project.root / "todo.py").is_file()

    result = project.undo_last()

    both = "".join(result.restored) + "".join(result.removed)
    assert "evidence" in both and "todo.py" in both
    assert not (project.root / "todo.py").exists(), "交付的文件也要一起退回"
    assert list((project.root / fmt.EVIDENCE_DIR).iterdir()) == []


def test_work_moves_the_task_to_in_progress_but_not_done(project: Project) -> None:
    """产出之后任务不再停在"未开始"；但**不是完成**——完成仍由使用者确认（FR-056 / FR-014）。

    这条曾经反过来：产出不碰状态，于是"有产出却仍是未开始"的任务把依赖它的任务全卡死了。
    """
    task, _ = pick_task(project, "T001")
    draft = WorkDraft(task_id="T001", text=GOOD_REPLY)

    project.apply(prepare_work_change(project, task, draft, moment=NOW), moment=NOW)

    after = {item.id: item for item in Project.open(project.root).tasks()}
    assert after["T001"].status == "进行中"
    assert after["T001"].done is False, "勾选框也不该被打勾"
    assert after["T001"].evidence == "", "证据仍要使用者自己给"


def test_undo_rolls_back_files_and_status_together(project: Project) -> None:
    """文件与状态同属一条变更：一次撤回，两样一起退回（不然会留下"文件退了、状态没退"）。"""
    before_tasks = project.read_text(fmt.TASKS_FILE)
    task, _ = pick_task(project, "T001")

    project.apply(
        prepare_work_change(
            project, task, WorkDraft(task_id="T001", text=GOOD_REPLY), moment=LATER
        ),
        moment=LATER,
    )
    assert (project.root / "todo.py").is_file()
    assert Project.open(project.root).tasks()[0].status == "进行中"

    project.undo_last()

    assert not (project.root / "todo.py").exists()
    assert project.read_text(fmt.TASKS_FILE) == before_tasks


def test_dependency_hint_points_at_the_existing_output(project: Project) -> None:
    """被依赖的那条其实已经产出过时，错误提示要把它说出来并给命令（FR-056）。"""
    task, _ = pick_task(project, "T001")
    project.apply(
        prepare_work_change(
            project, task, WorkDraft(task_id="T001", text=GOOD_REPLY), moment=LATER
        ),
        moment=LATER,
    )

    with pytest.raises(WorkspaceError) as excinfo:
        pick_task(Project.open(project.root), "T002")

    hint = flat(excinfo.value.hint)
    assert "其实已经有产出" in hint
    assert "pm-agenttrack" in hint and "T001" in hint


# ---- 命令端到端（T079）------------------------------------------------- #


# ---- 重复执行要拦（T087 / T088）----------------------------------------- #


def test_past_deliveries_reads_the_records(project: Project) -> None:
    """从历次记录里读回"这条任务以前产出过什么"。"""
    task, _ = pick_task(project, "T001")
    draft = WorkDraft(task_id="T001", text=GOOD_REPLY)
    project.apply(prepare_work_change(project, task, draft, moment=NOW), moment=NOW)

    past = past_deliveries(project, "T001")

    assert len(past) == 1
    assert past[0].files == ("todo.py",)
    assert past[0].at in ("2026-09-24 10:30", str(NOW)[:16])
    assert "todo.py" in past[0].render()


def test_past_deliveries_is_empty_for_a_fresh_task(project: Project) -> None:
    assert past_deliveries(project, "T001") == ()


def test_previous_files_go_into_the_prompt(project: Project) -> None:
    """重做时把上次的文件清单带进上下文，要求沿用同一套文件。"""
    task, _ = pick_task(project, "T001")
    project.apply(
        prepare_work_change(project, task, WorkDraft(task_id="T001", text=GOOD_REPLY), moment=NOW),
        moment=NOW,
    )
    provider = FakeProvider(GOOD_REPLY)

    draft_work(Project.open(project.root), task, provider)

    sent = "\n".join(message.content for message in provider.seen)
    assert "todo.py" in sent and "沿用同一套文件" in sent


def test_command_refuses_to_repeat_a_task(project: Project, monkeypatch) -> None:
    """第二次执行同一条任务：**默认拦住**，并列出上次产出了什么（FR-055）。"""
    from typer.testing import CliRunner

    from pm_agent import cli as cli_module

    monkeypatch.setattr(cli_module, "get_provider", lambda name: FakeProvider(GOOD_REPLY))
    first = CliRunner().invoke(
        cli_module.app, ["work", "T001", "--path", str(project.root), "--yes"]
    )
    assert first.exit_code == 0, first.stdout

    second = CliRunner().invoke(
        cli_module.app, ["work", "T001", "--path", str(project.root), "--yes"]
    )

    assert second.exit_code == 1
    shown = flat(second.stdout)
    assert "以前产出过1次" in shown
    assert "todo.py" in shown
    assert "没有重做" in shown
    assert "pm-agenttrack" in shown, '拒绝时要给出"把它标完成"的命令，别把人堵死'
    # 只有第一条记录，没有堆出第二次
    assert len(list((project.root / fmt.EVIDENCE_DIR).glob("T001-*.md"))) == 1


def test_command_redo_proceeds_and_says_so(project: Project, monkeypatch) -> None:
    """`--redo` 才继续；仍然提示沿用上次的文件。"""
    from typer.testing import CliRunner

    from pm_agent import cli as cli_module

    monkeypatch.setattr(cli_module, "get_provider", lambda name: FakeProvider(GOOD_REPLY))
    runner = CliRunner()
    runner.invoke(cli_module.app, ["work", "T001", "--path", str(project.root), "--yes"])

    again = runner.invoke(
        cli_module.app, ["work", "T001", "--path", str(project.root), "--yes", "--redo"]
    )

    assert again.exit_code == 0, again.stdout
    assert "沿用上次的文件名" in flat(again.stdout)


def test_command_echo_shows_which_project(project: Project, monkeypatch) -> None:
    """回显带项目名与路径——`work` / `track` 的项目目录是 `--path`，抄漏就会打到别的项目。"""
    from typer.testing import CliRunner

    from pm_agent import cli as cli_module

    monkeypatch.setattr(cli_module, "get_provider", lambda name: FakeProvider(GOOD_REPLY))

    result = CliRunner().invoke(
        cli_module.app, ["work", "T001", "--path", str(project.root), "--yes"]
    )

    assert result.exit_code == 0
    shown = flat(result.stdout)
    assert "项目" in shown and "待办清单" in shown
    assert "--path" in shown, "下一步提示里要能直接抄到 --path"


# ---- 写入后当场确认完成（T093 / FR-057）--------------------------------- #


def test_command_asks_whether_the_task_is_done(project: Project, monkeypatch) -> None:
    """写完就问一次；回答"是"→ 记为完成，并把本次产出自动关联成证据。"""
    from typer.testing import CliRunner

    from pm_agent import cli as cli_module

    monkeypatch.setattr(cli_module, "get_provider", lambda name: FakeProvider(GOOD_REPLY))

    result = CliRunner().invoke(
        cli_module.app,
        ["work", "T001", "--path", str(project.root)],
        input="y\ny\n",  # 第一个 y：写入；第二个 y：算完成了
    )

    assert result.exit_code == 0, result.stdout
    shown = flat(result.stdout)
    assert "这条任务算完成了吗" in shown
    assert "已记为完成" in shown

    after = {item.id: item for item in Project.open(project.root).tasks()}
    assert after["T001"].status == "完成"
    assert after["T001"].done is True
    assert "todo.py" in after["T001"].evidence, "证据要指向本次产出"
    assert "evidence/" in after["T001"].evidence


def test_answering_no_leaves_it_in_progress(project: Project, monkeypatch) -> None:
    """回答"否"就不标记完成——任务停在"进行中"，并给出后续命令。"""
    from typer.testing import CliRunner

    from pm_agent import cli as cli_module

    monkeypatch.setattr(cli_module, "get_provider", lambda name: FakeProvider(GOOD_REPLY))

    result = CliRunner().invoke(
        cli_module.app, ["work", "T001", "--path", str(project.root)], input="y\nn\n"
    )

    assert result.exit_code == 0, result.stdout
    shown = flat(result.stdout)
    assert "没标完成" in shown and "进行中" in shown
    assert "pm-agenttrack" in shown, "没标完成时要给出以后怎么标"

    after = {item.id: item for item in Project.open(project.root).tasks()}
    assert after["T001"].status == "进行中"
    assert after["T001"].done is False


def test_yes_flag_does_not_silently_mark_done(project: Project, monkeypatch) -> None:
    """`--yes` 跳过的是确认，不该顺带替人判定完成（默认判"没完成"）。"""
    from typer.testing import CliRunner

    from pm_agent import cli as cli_module

    monkeypatch.setattr(cli_module, "get_provider", lambda name: FakeProvider(GOOD_REPLY))

    result = CliRunner().invoke(
        cli_module.app, ["work", "T001", "--path", str(project.root), "--yes"]
    )

    assert result.exit_code == 0
    assert Project.open(project.root).tasks()[0].status == "进行中"


def test_done_flag_marks_it_without_asking(project: Project, monkeypatch) -> None:
    """`--done` 是给自动化用的：不问，直接记完成并关联证据。"""
    from typer.testing import CliRunner

    from pm_agent import cli as cli_module

    monkeypatch.setattr(cli_module, "get_provider", lambda name: FakeProvider(GOOD_REPLY))

    result = CliRunner().invoke(
        cli_module.app, ["work", "T001", "--path", str(project.root), "--yes", "--done"]
    )

    assert result.exit_code == 0
    shown = flat(result.stdout)
    assert "这条任务算完成了吗" not in shown, "--done 不该再问"
    assert "已记为完成" in shown
    after = Project.open(project.root).tasks()[0]
    assert after.status == "完成" and "todo.py" in after.evidence


# ---- 产出直接落盘（T081 / T082）----------------------------------------- #


def test_parse_deliverables_reads_every_file_block() -> None:
    """文件块：标题 + 紧跟的围栏；子目录路径也算。"""
    text = (
        "## 2. 交付物\n\n"
        "### 文件：todo.py\n\n```python\nprint('hi')\n```\n\n"
        "### 文件：`docs/调研笔记.md`\n\n```markdown\n# 结论\n```\n"
    )

    artifacts = parse_deliverables(text)

    assert [item.path for item in artifacts] == ["todo.py", "docs/调研笔记.md"]
    assert artifacts[0].content == "print('hi')\n"


def test_file_block_without_a_fence_is_refused() -> None:
    """标题后面没有围栏就报错——猜错路径的代价是内容写错地方。"""
    with pytest.raises(FormatError):
        parse_deliverables("### 文件：todo.py\n这里忘了围栏\n")


def test_deliverable_without_any_file_is_refused(project: Project) -> None:
    """只写了一堆说明、没给文件块的交付物不合格（FR-053 要求落成文件）。"""
    task, _ = pick_task(project, "T001")
    draft = WorkDraft(task_id="T001", text=GOOD_REPLY.replace("### 文件：todo.py", "### 大概这样写"))

    with pytest.raises(FormatError) as excinfo:
        prepare_work_change(project, task, draft, moment=NOW)

    assert "没有任何文件块" in str(excinfo.value)
    assert not (project.root / "todo.py").exists()


@pytest.mark.parametrize(
    "path",
    ["C:/windows/hosts", "/etc/passwd", "../外面.py", "sub/../../外面.py"],
)
def test_paths_outside_the_project_are_refused(project: Project, path: str) -> None:
    problems = check_artifacts(project, (Artifact(path=path, content="x\n"),))

    assert problems, f"{path} 不该被接受"


@pytest.mark.parametrize("path", ["spec.md", "tasks.md", "plan.md", "project.yaml", "history/x.md", ".git/config"])
def test_program_owned_files_are_refused(project: Project, path: str) -> None:
    """程序自己维护的文件与状态目录不许被 work 顺手改掉。"""
    problems = check_artifacts(project, (Artifact(path=path, content="x\n"),))

    assert problems, f"{path} 不该被接受"


def test_duplicate_file_is_refused(project: Project) -> None:
    problems = check_artifacts(
        project,
        (Artifact(path="todo.py", content="a\n"), Artifact(path="todo.py", content="b\n")),
    )

    assert any("两次" in problem.message for problem in problems)


def test_empty_file_is_refused(project: Project) -> None:
    problems = check_artifacts(project, (Artifact(path="todo.py", content="   \n"),))

    assert any("空的" in problem.message for problem in problems)


def test_multiple_files_land_together(project: Project) -> None:
    """一次交付多个文件：都写进去，一次 undo 全退回。"""
    task, _ = pick_task(project, "T001")
    reply = GOOD_REPLY + "\n### 文件：docs/用法.md\n\n```markdown\n# 用法\n\n`add('买菜')`\n```\n"
    draft = WorkDraft(task_id="T001", text=reply)

    project.apply(prepare_work_change(project, task, draft, moment=LATER), moment=LATER)

    assert (project.root / "todo.py").is_file()
    assert (project.root / "docs" / "用法.md").is_file()

    project.undo_last()
    assert not (project.root / "todo.py").exists()
    assert not (project.root / "docs" / "用法.md").exists()
    assert not (project.root / "docs").exists(), "空目录也该跟着清掉"


def test_command_writes_evidence(project: Project, monkeypatch) -> None:
    """端到端：挑任务 → 装配 → 预览 →（--yes）留存。"""
    from typer.testing import CliRunner

    from pm_agent import cli as cli_module

    monkeypatch.setattr(
        cli_module, "get_provider", lambda name: FakeProvider(GOOD_REPLY)
    )

    result = CliRunner().invoke(
        cli_module.app, ["work", "T001", "--path", str(project.root), "--yes"]
    )

    assert result.exit_code == 0, result.stdout
    assert "这次做的是" in result.stdout and "T001" in result.stdout
    assert "为什么是它" in result.stdout
    assert (project.root / "todo.py").is_file(), "命令跑完，交付的文件要真的在项目里"
    assert list((project.root / fmt.EVIDENCE_DIR).glob("T001-*.md"))


def test_command_refuses_echo(project: Project) -> None:
    """误用回声实现时拒绝留存——不然会把回显当成交付物（FR-037）。"""
    from typer.testing import CliRunner

    from pm_agent.cli import app as cli_app

    result = CliRunner().invoke(
        cli_app,
        ["work", "T001", "--path", str(project.root), "--provider", "echo", "--yes"],
    )

    assert result.exit_code == 1
    assert "回声" in result.stdout
    assert list((project.root / fmt.EVIDENCE_DIR).iterdir()) == []


def test_command_refuses_a_blocked_task(project: Project) -> None:
    from typer.testing import CliRunner

    from pm_agent.cli import app as cli_app

    result = CliRunner().invoke(
        cli_app, ["work", "T002", "--path", str(project.root), "--provider", "echo"]
    )

    assert result.exit_code == 1
    assert "依赖还没完成" in result.stdout
