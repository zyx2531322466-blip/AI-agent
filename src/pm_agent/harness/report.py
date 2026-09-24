"""进度汇报：把项目状态说给人听（T038 ~ T041）。

三条约束：

1. **每条都有来源**（FR-031）：条目都从某条记录来，来源写在条目上；校验时发现
   无来源条目就**打回**——宁可重生成，也不发出无法核查的汇报。
2. **按读者调详略**（FR-032）：自己看要细节，给上级看要结论与风险；
   但**风险与结论一条都不能少**。
3. **没进展就说没进展**（FR-033）：空周期不编填充内容。

生成是**规则式**的：不调模型，所以每条信息的来源天然存在、也永远复算得出。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from ..workspace import format as fmt
from ..workspace.store import Project
from .risks import Risk, detect_risks

# FR-030 要求的四类分组，顺序也是渲染顺序
SECTIONS = ("已完成", "进行中", "阻塞", "风险")

# 给上级看的视图里每类最多列几条；风险不设上限
BOSS_LIMIT = 5


@dataclass(frozen=True)
class ReportItem:
    """汇报里的一条。``source`` 是它的出处，不能空（FR-031）。"""

    section: str
    text: str
    source: str
    # "事实" 或 "推测"——和风险视图共用同一套标记（FR-024）
    inference: str = "事实"
    # 额外细节，只有"给自己看"的视图会展开
    detail: str = ""


@dataclass(frozen=True)
class Report:
    project: str
    audience: str
    since: str
    items: tuple[ReportItem, ...]

    def section(self, name: str) -> tuple[ReportItem, ...]:
        return tuple(item for item in self.items if item.section == name)

    @property
    def summary(self) -> str:
        """一句话结论。没有实质进展就直说（FR-033）。"""
        done = len(self.section("已完成"))
        doing = len(self.section("进行中"))
        blocked = len(self.section("阻塞"))
        risks = len(self.section("风险"))
        head = f"本周期完成 {done} 条、进行中 {doing} 条、阻塞 {blocked} 条、风险 {risks} 条。"
        if done == 0:
            head += "没有已完成的任务——这一周期没有实质进展。"
        return head

    def render(self, *, audience: str | None = None) -> str:
        who = audience or self.audience
        verbose = who == "自己"
        limited = who == "上级"

        lines: list[str] = [f"# {self.project} —— 进度汇报", ""]
        lines += [
            f"- 读者：{who}",
            f"- 周期：{self.since} 起（没写更新时间的任务不做时间筛选）",
            f"- 结论：{self.summary}",
            "",
        ]

        for name in SECTIONS:
            items = self.section(name)
            lines.append(f"## {name}")
            lines.append("")
            if not items:
                lines.append("（本周期没有已完成的任务）" if name == "已完成" else "（无）")
                lines.append("")
                continue

            shown = items[:BOSS_LIMIT] if (limited and name != "风险") else items
            for item in shown:
                tag = f"[{item.inference}] " if item.inference != "事实" else ""
                lines.append(f"- {tag}{item.text}　（来源：{item.source}）")
                if verbose and item.detail:
                    lines.append(f"  - {item.detail}")
            if len(shown) < len(items):
                lines.append(f"- …… 还有 {len(items) - len(shown)} 条（细节见 pm-agent tasks）")
            lines.append("")
        return "\n".join(lines).rstrip()


def check_report(report: Report) -> list[fmt.Problem]:
    """汇报的准入检查：**没有来源的条目一律打回**（FR-031）。

    这不是给人看的提醒，而是"发不出去"：无法核查的成果描述等于自说自话。
    """
    problems: list[fmt.Problem] = []
    for item in report.items:
        if not item.source.strip():
            problems.append(
                fmt.Problem(
                    "reports/",
                    f"「{item.section}」里有一条没有来源：{item.text[:40]}",
                    "补上它出自哪条记录；补不上就别写进去（FR-031）",
                )
            )
    return problems


def build_report(
    project: Project,
    *,
    audience: str = "自己",
    since: str | None = None,
    now: dt.datetime | None = None,
) -> Report:
    """按当前项目状态生成汇报。**只读。**"""
    items: list[ReportItem] = []

    for task in project.tasks():
        if not _within_period(task, since):
            continue
        if task.done:
            items.append(
                ReportItem(
                    section="已完成",
                    text=f"{task.id} {task.title}",
                    source=f"tasks.md 第 {task.line} 行（状态：完成）",
                    detail=f"证据：{task.evidence or '（没写）'}",
                )
            )
        elif task.status == "进行中":
            items.append(
                ReportItem(
                    section="进行中",
                    text=f"{task.id} {task.title}",
                    source=f"tasks.md 第 {task.line} 行（更新：{task.updated or '未记'}）",
                    detail=f"上次留下的结论：{task.conclusion}" if task.conclusion else "",
                )
            )
        elif task.status == "阻塞":
            items.append(
                ReportItem(
                    section="阻塞",
                    text=f"{task.id} {task.title}",
                    source=f"tasks.md 第 {task.line} 行（更新：{task.updated or '未记'}）",
                    detail=f"上次留下的结论：{task.conclusion}" if task.conclusion else "",
                )
            )

    for risk in detect_risks(project, now=now):
        items.append(_risk_item(risk))

    return Report(
        project=project.meta.name,
        audience=audience,
        since=since or "上次交接记录",
        items=tuple(items),
    )


def _risk_item(risk: Risk) -> ReportItem:
    """风险转成汇报条目——**沿用同一套事实/推测标记**（FR-024）。"""
    return ReportItem(
        section="风险",
        text=risk.text,
        source=risk.basis,
        inference=risk.inference,
    )


def _within_period(task: fmt.Task, since: str | None) -> bool:
    """任务算不算在本周期里。

    写了 ``**更新**`` 就按它比；**没写更新时间的算在内**——无法判断时宁多勿漏，
    总比悄悄漏掉一条强。这也是为什么这个筛选要在报告里写明口径。
    """
    if not since or not task.updated:
        return True
    return task.updated.strip() >= since.strip()
