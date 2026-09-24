"""Harness：会话循环、上下文装配、冲突校验（plan §4.1 的独立一层）。

M3 是它的第一块——**跨会话交接**。M4 的"会话循环"会挂在它上面。
这一层只产出数据，打印与确认归 CLI。
"""

from .session import SessionBrief, session_brief

__all__ = ["SessionBrief", "session_brief"]
