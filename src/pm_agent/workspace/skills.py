"""能力单元：加载、匹配、沉淀、修订（T046 ~ T054）。

**三级渐进式加载**（T047）：

1. :func:`list_skills` 只读**元数据**——会话开始时放进上下文的就是这一级；
2. :func:`load_skill` 读正文（步骤要点）——判定相关之后才读；
3. :func:`load_reference` 读 ``reference/`` 下的文件——正文里点到才读。

**内置与项目分开**：内置的随程序走（只读），项目自己沉淀的在 ``<项目>/skills/``
（可写，走 Change 机制）。匹配时两者都算，但来源标得出来。

**采纳记录放在 ``project.yaml``**（``skill_usage``）而不是能力单元目录里：
这样修订能力单元不会动到使用历史（FR-029），反过来也一样。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from importlib.resources import files as package_files
from pathlib import Path

from ..errors import FormatError, WorkspaceError
from . import format as fmt
from .changes import Change
from .files import split_frontmatter
from .store import Project

#: 拒绝之后多少天内不再建议（FR-027 说的"不再纠缠"）
DECLINE_COOLDOWN_DAYS = 14
#: 匹配到几处重合才值得建议
MIN_OVERLAP = 2


@dataclass(frozen=True)
class SkillSuggestion:
    """一条建议：哪个能力单元、凭什么建议、重合了几处。"""

    meta: fmt.SkillMeta
    score: int
    reason: str


# ---- 加载（三级）-------------------------------------------------------


def builtin_skills() -> list[fmt.SkillMeta]:
    """内置能力单元的**元数据**（T053）。不读正文。"""
    root = package_files("pm_agent.skills")
    metas: list[fmt.SkillMeta] = []
    for entry in sorted(root.iterdir(), key=lambda item: item.name):
        skill_file = entry.joinpath(fmt.SKILL_FILE)
        if not skill_file.is_file():
            continue
        metas.append(
            fmt.parse_skill_meta(
                skill_file.read_text(encoding="utf-8"),
                source="内置",
                path=Path(entry.name),
            )
        )
    return metas


def project_skills(project: Project) -> list[fmt.SkillMeta]:
    """项目自己沉淀的能力单元（元数据）。"""
    folder = project.path(fmt.SKILLS_DIR)
    if not folder.is_dir():
        return []
    metas: list[fmt.SkillMeta] = []
    for entry in sorted(folder.iterdir(), key=lambda item: item.name):
        skill_file = entry / fmt.SKILL_FILE
        if not entry.is_dir() or not skill_file.is_file():
            continue
        metas.append(
            fmt.parse_skill_meta(
                skill_file.read_text(encoding="utf-8"),
                source="项目",
                path=entry,
            )
        )
    return metas


def list_skills(project: Project) -> list[fmt.SkillMeta]:
    """内置 + 项目的元数据；同名的以项目版为准。"""
    merged = {meta.name: meta for meta in builtin_skills()}
    merged.update({meta.name: meta for meta in project_skills(project)})
    return sorted(merged.values(), key=lambda meta: meta.name)


def get_skill(project: Project, name: str) -> fmt.SkillMeta:
    for meta in list_skills(project):
        if meta.name == name:
            return meta
    available = "、".join(meta.name for meta in list_skills(project)) or "（一个也没有）"
    raise WorkspaceError(f"没有这个能力单元：{name}", hint=f"现有：{available}")


def load_skill(project: Project, name: str) -> str:
    """第二级：读正文（步骤要点）。"""
    meta = get_skill(project, name)
    _, body, _ = split_frontmatter(_skill_text(project, meta))
    return body.strip()


def load_reference(project: Project, name: str, filename: str) -> str:
    """第三级：读 ``reference/`` 下的文件——正文里点到才读。"""
    meta = get_skill(project, name)
    if meta.source == "项目":
        target = meta.path / fmt.SKILL_REFERENCE_DIR / filename
        if not target.is_file():
            raise WorkspaceError(
                f"{name} 里没有这个引用文件：{filename}",
                hint=f"看看 {fmt.SKILL_REFERENCE_DIR}/ 下有什么",
            )
        return target.read_text(encoding="utf-8")

    root = package_files("pm_agent.skills").joinpath(
        meta.path.name, fmt.SKILL_REFERENCE_DIR
    )
    target = root.joinpath(filename)
    if not target.is_file():
        raise WorkspaceError(f"{name} 里没有这个引用文件：{filename}", hint="内置能力单元的引用文件在包内")
    return target.read_text(encoding="utf-8")


def _skill_text(project: Project, meta: fmt.SkillMeta) -> str:
    if meta.source == "项目":
        return (meta.path / fmt.SKILL_FILE).read_text(encoding="utf-8")
    root = package_files("pm_agent.skills").joinpath(meta.path.name, fmt.SKILL_FILE)
    return root.read_text(encoding="utf-8")


# ---- 匹配与建议（T049）-------------------------------------------------


def suggest_skills(
    project: Project,
    text: str,
    *,
    limit: int = 3,
    now: dt.datetime | None = None,
) -> list[SkillSuggestion]:
    """给一段任务描述挑相关的能力单元。

    匹配用字符 bigram 重叠（和 `track` 的归属判断同一套办法），
    并且**跳过冷却期内刚被拒绝过的**——FR-027 要求"可拒绝且不再纠缠"。
    """
    moment = now or dt.datetime.now()
    declined = _recently_declined(project, moment)

    scored: list[SkillSuggestion] = []
    for meta in list_skills(project):
        if meta.name in declined:
            continue
        by_when = fmt.bigram_overlap(text, meta.when_to_use)
        by_desc = fmt.bigram_overlap(text, meta.description)
        score = max(by_when, by_desc)
        if score < MIN_OVERLAP:
            continue
        where = "适用场景" if by_when >= by_desc else "说明"
        scored.append(
            SkillSuggestion(meta=meta, score=score, reason=f"与{where}重合 {score} 处")
        )
    scored.sort(key=lambda item: (-item.score, item.meta.name))
    return scored[:limit]


# ---- 沉淀与修订（T048 / T051）------------------------------------------


def save_skill(
    project: Project,
    *,
    name: str,
    description: str,
    when_to_use: str,
    when_not_to_use: str,
    inputs: str,
    outputs: str,
    why: str,
    steps: list[str] | tuple[str, ...],
    version: str = "1",
    reason: str = "沉淀能力单元",
) -> Change:
    """把一次成功做法沉淀成能力单元（T048）——**不用手写文件**。

    六要素 + why 缺一项就写不进去（FR-026 / FR-050）；步骤要点至少要有一条。
    """
    missing = [
        label
        for label, value in (
            ("name", name),
            ("description", description),
            ("when_to_use", when_to_use),
            ("when_not_to_use", when_not_to_use),
            ("inputs", inputs),
            ("outputs", outputs),
            ("why", why),
        )
        if not str(value).strip()
    ]
    if missing:
        raise WorkspaceError(
            f"能力单元缺要素：{'、'.join(missing)}",
            hint="FR-026 要求六要素齐全，FR-050 还要求写清 why（为什么这样做）",
        )
    clean_steps = [step.strip() for step in steps if step.strip()]
    if not clean_steps:
        raise WorkspaceError(
            "能力单元没有步骤要点", hint="正文至少要写成一条条要点（FR-026）"
        )

    relative = f"{fmt.SKILLS_DIR}/{name}/{fmt.SKILL_FILE}"
    if project.path(relative).exists():
        raise WorkspaceError(
            f"{name} 已经存在了", hint="要改它用 pm-agent skill-save 的修订路径，或换个名字"
        )

    meta = {
        "name": name.strip(),
        "description": description.strip(),
        "when_to_use": when_to_use.strip(),
        "when_not_to_use": when_not_to_use.strip(),
        "inputs": inputs.strip(),
        "outputs": outputs.strip(),
        "why": why.strip(),
        "version": str(version),
    }
    body = "\n".join(f"- {step}" for step in clean_steps)
    return project.prepare_write(
        relative, _render(meta, body), reason=reason
    )


def revise_skill(
    project: Project,
    name: str,
    *,
    version: str | None = None,
    steps: list[str] | tuple[str, ...] | None = None,
    reason: str = "修订能力单元",
    **fields: str,
) -> Change:
    """修订一个能力单元（T051）：改字段或正文，version 记一版。

    **使用历史不受影响**：采纳记录在 ``project.yaml`` 里，不跟着能力单元走（FR-029）。
    """
    meta = get_skill(project, name)
    if meta.source != "项目":
        raise WorkspaceError(
            f"{name} 是内置能力单元，不能直接改",
            hint="先把它沉淀成项目版（同名会覆盖内置的），或者换个名字",
        )

    raw = (meta.path / fmt.SKILL_FILE).read_text(encoding="utf-8")
    old_meta, old_body, _ = split_frontmatter(raw)
    for field_name, value in fields.items():
        if field_name not in fmt.SKILL_REQUIRED_FIELDS:
            raise WorkspaceError(
                f"能力单元没有 {field_name} 这个字段",
                hint=f"可改的字段：{'、'.join(fmt.SKILL_REQUIRED_FIELDS)}",
            )
        old_meta[field_name] = value
    if version is not None:
        old_meta["version"] = str(version)

    body = old_body.strip()
    if steps is not None:
        clean = [step.strip() for step in steps if step.strip()]
        if not clean:
            raise WorkspaceError("步骤要点不能清空", hint="至少留一条")
        body = "\n".join(f"- {step}" for step in clean)

    updated = _render({str(k): str(v) for k, v in old_meta.items()}, body)
    return project.prepare_write(
        f"{fmt.SKILLS_DIR}/{name}/{fmt.SKILL_FILE}", updated, reason=reason
    )


# ---- 采纳记录（T050）---------------------------------------------------


def record_usage(
    project: Project,
    name: str,
    outcome: str,
    *,
    moment: dt.datetime | None = None,
    reason: str = "",
) -> Change:
    """记一次采纳或拒绝（T050）。``outcome`` 取 ``accepted`` 或 ``declined``。"""
    if outcome not in ("accepted", "declined"):
        raise WorkspaceError(
            f"没有这种结果：{outcome}", hint="可选：accepted、declined"
        )
    get_skill(project, name)  # 不存在就报错
    stamp = (moment or dt.datetime.now()).isoformat(timespec="seconds")
    usage = [*project.meta.skill_usage, {"name": name, "outcome": outcome, "at": stamp}]
    return project.prepare_meta_change(
        skill_usage=usage, reason=reason or f"{name} 被 {outcome}"
    )


def usage_summary(project: Project) -> dict[str, dict[str, int]]:
    """每个能力单元被采纳 / 拒绝了几次（T050）。"""
    summary: dict[str, dict[str, int]] = {}
    for record in project.meta.skill_usage:
        name = str(record.get("name") or "")
        outcome = str(record.get("outcome") or "")
        if not name or not outcome:
            continue
        bucket = summary.setdefault(name, {"accepted": 0, "declined": 0})
        if outcome in bucket:
            bucket[outcome] += 1
    return summary


def share_skill(
    source: Project,
    target: Project,
    name: str,
    *,
    new_name: str | None = None,
    reason: str = "",
) -> Change:
    """把一个项目的能力单元复制到另一个项目（T058 / FR-041）。

    **复制，而不是让两个项目共用一份**：副本归目标项目所有，来源项目的归属与
    使用历史一动不动。共享复用要的是"做法可以搬过去"，不是"两份可变状态绑在一起"——
    后者一改就互相牵连，而 FR-041 要的恰恰是"引用不改变归属与历史"。
    """
    meta = get_skill(source, name)
    target_name = (new_name or meta.name).strip()
    relative = f"{fmt.SKILLS_DIR}/{target_name}/{fmt.SKILL_FILE}"
    if target.path(relative).exists():
        raise WorkspaceError(
            f"{target_name} 在目标项目里已经存在",
            hint="换个名字，或者先用 pm-agent skill-save --update 修订它",
        )

    body = load_skill(source, name)
    fields = {
        "name": target_name,
        "description": meta.description,
        "when_to_use": meta.when_to_use,
        "when_not_to_use": meta.when_not_to_use,
        "inputs": meta.inputs,
        "outputs": meta.outputs,
        "why": meta.why,
        "version": meta.version,
        # 留个来源，便于日后追溯；解析时会忽略不认识的字段
        "copied_from": f"{source.meta.name}/{meta.name}",
    }
    return target.prepare_write(
        relative,
        _render(fields, body),
        reason=reason or f"从 {source.meta.name} 复制能力单元 {meta.name}",
    )


def _recently_declined(project: Project, moment: dt.datetime) -> set[str]:
    """冷却期内拒绝过的能力单元（FR-027）。"""
    fresh: set[str] = set()
    for record in project.meta.skill_usage:
        if str(record.get("outcome")) != "declined":
            continue
        at = _parse_moment(str(record.get("at") or ""))
        if at is not None and (moment - at).days < DECLINE_COOLDOWN_DAYS:
            fresh.add(str(record.get("name") or ""))
    return fresh


def _parse_moment(text: str) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(text)
    except ValueError:
        return None


def _render(meta: dict[str, str], body: str) -> str:
    import yaml

    head = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False).strip()
    text = body.strip()
    # 正文可能自带一级标题（从别处复制过来时），有就别再加一个
    if not text.startswith("# "):
        text = f"# {meta.get('name', '')}\n\n{text}"
    return f"---\n{head}\n---\n\n{text}\n"
