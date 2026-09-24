"""项目工作区：格式定义、读写层、模板渲染。

对应 plan.md §2「项目即目录」——不引入数据库，项目就是一个装满
Markdown + YAML 的文件夹，使用者可以直接打开、手工修改。
"""

from .handoff import (
    Handoff,
    list_handoffs,
    new_handoff,
    read_handoff,
    read_latest_handoff,
    write_handoff,
)
from .changes import (
    ApplyResult,
    Change,
    ChangeEntry,
    UndoResult,
    apply_change,
    history_entries,
    prepare_write,
    read_change_meta,
    undo_last,
)
from .store import Project, create_project
from .requirements import (
    RequirementRevision,
    add_requirement,
    next_requirement_id,
    requirement_history,
    update_requirement,
)
from .review import (
    build_review_document,
    confirm_requirement,
    export_review,
    parse_confirmed,
    unconfirmed_requirements,
)
from .skills import (
    SkillSuggestion,
    get_skill,
    list_skills,
    load_reference,
    load_skill,
    record_usage,
    revise_skill,
    save_skill,
    share_skill,
    suggest_skills,
    usage_summary,
)

__all__ = [
    "Project",
    "create_project",
    "Change",
    "ChangeEntry",
    "ApplyResult",
    "UndoResult",
    "prepare_write",
    "apply_change",
    "undo_last",
    "history_entries",
    "read_change_meta",
    "add_requirement",
    "update_requirement",
    "next_requirement_id",
    "requirement_history",
    "RequirementRevision",
    "confirm_requirement",
    "unconfirmed_requirements",
    "parse_confirmed",
    "build_review_document",
    "export_review",
    "SkillSuggestion",
    "list_skills",
    "get_skill",
    "load_skill",
    "load_reference",
    "suggest_skills",
    "save_skill",
    "revise_skill",
    "share_skill",
    "record_usage",
    "usage_summary",
    "Handoff",
    "list_handoffs",
    "new_handoff",
    "read_handoff",
    "read_latest_handoff",
    "write_handoff",
]
