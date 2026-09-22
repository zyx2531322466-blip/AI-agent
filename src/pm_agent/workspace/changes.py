"""写入前预览与撤回（对应 tasks.md 的 T008）。

对应 spec.md 的 FR-034（写入前给预览）与 FR-035（能撤回最近一次变更），
以及 plan.md §6.2。四条设计约束：

1. **预览是数据，不是交互**。这一层只产出 :class:`Change`，不打印、不询问；
   显示与确认归 CLI——和 T006 的 ``announce`` 同一个道理，副作用留在最外层。
2. **想写入就必须先有 Change**。``prepare_write`` 是产出变更的唯一方式，
   ``apply_change`` 只接受 :class:`Change`。所以"先出预览"不是纪律，是类型。
3. **撤回靠快照，不靠补丁**。写入前把原内容整份存进 ``history/<时间戳>/before/``，
   撤回就是把快照复制回去。文件都是小文本，整份存最省事也最可靠：
   不会出现"补丁打不上"。
4. **一切按字节**。备份存原始字节，恢复写回原始字节。Windows 上文本模式
   会把 ``\\n`` 翻译成 ``\\r\\n``，那样"撤回"之后内容看着一样、字节却变了，
   "与写入前完全一致"就成了一句空话。

一个必须记住的边界：**文件在写入前可能根本不存在**（新建）。这时"撤回"是
**删掉它**，而不是往里面写空内容——留个 0 字节文件比删掉更糟。

初始化项目（``create_project``）有意不走这条路径：它是"新建"而不是"改动"，
没有"写入前"可以撤回，而且已存在文件一律跳过。
"""

from __future__ import annotations

import datetime as dt
import difflib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from ..errors import FormatError, WorkspaceError
from . import format as fmt

if TYPE_CHECKING:  # 只为类型标注；运行时避免与 store 形成循环导入
    from .store import Project

#: 一条变更记录占一个目录，目录名是可排序的时间戳
STAMP_FMT = "%Y-%m-%d-%H-%M-%S"
STAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}$")

#: 变更记录目录里的布局
META_FILE = "meta.yaml"
BEFORE_DIR = "before"

#: 预览里最多显示多少行差异，避免刷屏
PREVIEW_MAX_LINES = 12


@dataclass(frozen=True)
class ChangeEntry:
    """变更里的一个文件。

    ``before_bytes`` 是**原始字节**，不是解码后的文本——恢复要靠它逐字节还原。
    为 None 表示这个文件原本不存在。
    """

    path: str
    before_bytes: bytes | None
    after: str

    @property
    def existed(self) -> bool:
        return self.before_bytes is not None

    @property
    def after_bytes(self) -> bytes:
        return self.after.encode("utf-8")

    @property
    def before_text(self) -> str | None:
        """用于预览与差异；解码失败时用替代字符，不影响字节级的恢复。"""
        if self.before_bytes is None:
            return None
        return self.before_bytes.decode("utf-8", errors="replace")

    @property
    def changed(self) -> bool:
        """按**字节**比较：只有字节相同才算没变。"""
        return self.before_bytes != self.after_bytes

    @property
    def kind(self) -> str:
        if self.before_bytes is None:
            return "新建"
        return "修改" if self.changed else "未变"

    @property
    def diff_stat(self) -> tuple[int, int]:
        """(新增行数, 删除行数)，按真实差异算而不是按总行数差。"""
        before = (self.before_text or "").splitlines()
        after = self.after.splitlines()
        added = removed = 0
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(a=before, b=after).get_opcodes():
            if tag in ("replace", "delete"):
                removed += i2 - i1
            if tag in ("replace", "insert"):
                added += j2 - j1
        return added, removed

    def snippet(self, limit: int = PREVIEW_MAX_LINES) -> list[str]:
        """差异片段（超过 limit 行就截断，并说明还剩多少行）。"""
        if self.before_bytes is None:
            body = [f"+ {line}" for line in self.after.splitlines()]
        else:
            body = list(
                difflib.unified_diff(
                    (self.before_text or "").splitlines(),
                    self.after.splitlines(),
                    fromfile=self.path,
                    tofile=self.path,
                    lineterm="",
                )
            )
        if len(body) > limit:
            body = [*body[:limit], f"...（其余 {len(body) - limit} 行略）"]
        return body


@dataclass(frozen=True)
class Change:
    """一份**尚未落盘**的变更。想写入就得先有它。"""

    entries: tuple[ChangeEntry, ...]
    #: 人类可读的说明，会写进变更记录，便于日后回看"这次改的是为了什么"
    reason: str = ""

    @property
    def changed_entries(self) -> tuple[ChangeEntry, ...]:
        return tuple(entry for entry in self.entries if entry.changed)

    @property
    def is_noop(self) -> bool:
        return not self.changed_entries

    def render(self) -> str:
        """把变更渲染成给人看的预览文本。**只返回文本，不打印。**"""
        lines = [f"将要写入 {len(self.entries)} 个文件：", ""]
        for entry in self.entries:
            if not entry.changed:
                lines.append(f"  {entry.kind}  {entry.path}（内容相同，不会写入）")
                continue
            added, removed = entry.diff_stat
            stat = f"+{added} 行" if not entry.existed else f"+{added} -{removed} 行"
            lines.append(f"  {entry.kind}  {entry.path}（{stat}）")
            lines.extend(f"    {line}" for line in entry.snippet())
            lines.append("")
        if not self.is_noop:
            lines.append("写入前会把原内容存进 history/，之后可以撤回。")
        return "\n".join(lines).rstrip()


@dataclass(frozen=True)
class ApplyResult:
    """``apply_change`` 的结果。``entry_dir`` 为 None 表示没有实际写入。"""

    entry_dir: Path | None
    written: tuple[str, ...]
    skipped: tuple[str, ...]


@dataclass(frozen=True)
class UndoResult:
    """``undo_last`` 的结果。"""

    entry_dir: Path
    restored: tuple[str, ...]
    removed: tuple[str, ...]


# ---- 准备变更 ----------------------------------------------------------


def prepare_write(
    project: Project, relative: str, text: str, *, reason: str = ""
) -> Change:
    """准备一次写入：**读现状、产出预览，但不碰磁盘**。"""
    normalized = _normalize(relative)
    target = project.path(*normalized.split("/"))
    before = target.read_bytes() if target.is_file() else None
    return Change(
        entries=(ChangeEntry(path=normalized, before_bytes=before, after=text),),
        reason=reason,
    )


# ---- 落盘与撤回 --------------------------------------------------------


def apply_change(
    project: Project, change: Change, *, moment: dt.datetime | None = None
) -> ApplyResult:
    """把变更写进项目；写入前先把原内容存进 ``history/``。

    没有实际变化的变更**不写盘、也不留历史**——否则历史会被无意义的记录淹没。
    """
    pending = change.changed_entries
    if not pending:
        return ApplyResult(
            entry_dir=None,
            written=(),
            skipped=tuple(entry.path for entry in change.entries),
        )

    entry_dir = _new_entry_dir(project, moment or dt.datetime.now())
    _write_backups(entry_dir, pending)
    _write_meta(entry_dir, pending, reason=change.reason, created=moment)

    for entry in pending:
        target = project.path(*entry.path.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(entry.after_bytes)

    return ApplyResult(
        entry_dir=entry_dir,
        written=tuple(entry.path for entry in pending),
        skipped=tuple(
            entry.path for entry in change.entries if not entry.changed
        ),
    )


def undo_last(project: Project, *, moment: dt.datetime | None = None) -> UndoResult:
    """撤回**最近一次**尚未撤回的变更。

    撤回后会在那条记录里标记 ``undone``，所以再撤一次会继续往前退，
    而不是把同一条变更反复恢复。
    """
    entries = history_entries(project)
    target_dir = next((path for path in entries if not _is_undone(path)), None)
    if target_dir is None:
        raise WorkspaceError(
            "没有可撤回的变更",
            hint="history/ 里没有未撤回的记录；用 pm-agent history 看看都有哪些",
        )

    meta = read_change_meta(target_dir)
    restored: list[str] = []
    removed: list[str] = []

    for record in meta.get("files") or []:
        relative = str(record.get("path") or "")
        if not relative:
            continue
        target = project.path(*relative.split("/"))
        if record.get("existed"):
            backup = target_dir / str(record.get("backup") or "")
            if not backup.is_file():
                raise FormatError(
                    f"变更记录缺少备份文件，无法撤回：{backup.relative_to(project.root)}",
                    hint="这份 history/ 记录不完整，可能被手工删过",
                )
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(backup.read_bytes())
            restored.append(relative)
        else:
            # 原本不存在 → 撤回就是删掉它，而不是留个空文件
            if target.is_file():
                target.unlink()
            removed.append(relative)

    meta["undone"] = (moment or dt.datetime.now()).isoformat(timespec="seconds")
    _write_meta_file(target_dir, meta)

    return UndoResult(
        entry_dir=target_dir, restored=tuple(restored), removed=tuple(removed)
    )


def history_entries(project: Project) -> list[Path]:
    """全部变更记录目录，**最近在前**（目录名是可排序的时间戳）。"""
    folder = project.path(fmt.HISTORY_DIR)
    if not folder.is_dir():
        return []
    return sorted(
        (path for path in folder.iterdir() if path.is_dir() and STAMP_RE.match(path.name)),
        key=lambda path: path.name,
        reverse=True,
    )


def read_change_meta(entry_dir: Path) -> dict[str, Any]:
    """读一条变更记录的 meta.yaml。"""
    meta_path = entry_dir / META_FILE
    if not meta_path.is_file():
        raise FormatError(
            f"变更记录缺少 {META_FILE}：{entry_dir.name}",
            hint="history/ 里的一条记录应当同时有 meta.yaml 和 before/ 目录",
        )
    data = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise FormatError(
            f"{META_FILE} 的内容不是键值对：{entry_dir.name}",
            hint="对照其它变更记录改一下",
        )
    return data


# ---- 内部 --------------------------------------------------------------


def _normalize(relative: str) -> str:
    text = str(relative).replace("\\", "/").strip("/")
    if not text:
        raise WorkspaceError("要写入的路径是空的", hint="给出项目内的相对路径，例如 spec.md")
    return text


def _new_entry_dir(project: Project, moment: dt.datetime) -> Path:
    """建一个唯一的时间戳目录；同一秒已占用就往后挪一秒。"""
    folder = project.path(fmt.HISTORY_DIR)
    folder.mkdir(parents=True, exist_ok=True)
    while True:
        stamp = moment.strftime(STAMP_FMT)
        entry = folder / stamp
        if not entry.exists():
            entry.mkdir()
            return entry
        moment += dt.timedelta(seconds=1)


def _write_backups(entry_dir: Path, entries: tuple[ChangeEntry, ...]) -> None:
    for entry in entries:
        if entry.before_bytes is None:
            continue
        backup = entry_dir / BEFORE_DIR / entry.path
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(entry.before_bytes)


def _write_meta(
    entry_dir: Path,
    entries: tuple[ChangeEntry, ...],
    *,
    reason: str,
    created: dt.datetime | None,
) -> None:
    meta: dict[str, Any] = {
        "created": (created or dt.datetime.now()).isoformat(timespec="seconds"),
        "reason": reason or "",
        "files": [
            {
                "path": entry.path,
                "existed": entry.existed,
                "backup": f"{BEFORE_DIR}/{entry.path}" if entry.existed else None,
                "added": entry.diff_stat[0],
                "removed": entry.diff_stat[1],
            }
            for entry in entries
        ],
    }
    _write_meta_file(entry_dir, meta)


def _write_meta_file(entry_dir: Path, meta: dict[str, Any]) -> None:
    # 人可读：allow_unicode + 不排序，字段顺序按写入顺序保持
    text = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False)
    # 同样按字节写，理由见 store._write_if_absent
    (entry_dir / META_FILE).write_bytes(text.encode("utf-8"))


def _is_undone(entry_dir: Path) -> bool:
    return bool(read_change_meta(entry_dir).get("undone"))
