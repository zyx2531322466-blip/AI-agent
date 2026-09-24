"""可讲解：把"为什么这么做"变成能查到的东西（plan §4.1 的 explain 层）。

- 依据与取舍的**内容**在 ``stages/stages.yaml`` 里（每个阶段一条）；
- 这里负责把它们**汇总起来看**：学习目标对照（T035）、项目设计说明（T036）。

为什么要单独一层：可讲解性靠的不是事后写文档，而是**内容本来就在那儿**。
这一层只是把它端出来。
"""

from .design import build_design_document, export_design
from .goals import GoalReview, goal_review

__all__ = ["GoalReview", "goal_review", "build_design_document", "export_design"]
