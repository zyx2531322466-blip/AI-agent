"""本项目所有"可预期失败"的错误类型。

约定（对应 FR-037：不静默降级，先说明再给替代路径）：

- 凡是能向使用者解释清楚的失败，都抛 :class:`PMAgentError` 的子类；
- 每个错误都尽可能带一句 ``hint``，也就是"接下来该怎么办"；
- CLI 统一捕获它们，打印消息 + 提示，并以退出码 1 结束。

这样做的价值：错误信息本身就是产品的一部分，而不是让使用者去看堆栈。
"""

from __future__ import annotations


class PMAgentError(Exception):
    """所有可预期失败的基类。"""

    def __init__(self, message: str, *, hint: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.hint = hint


class WorkspaceError(PMAgentError):
    """项目工作区相关的问题：找不到、打不开、结构不对。"""


class FormatError(WorkspaceError):
    """文件内容不符合工作区格式定义（见 workspace/format.py）。"""


class ModelConfigError(PMAgentError):
    """模型接入的配置不完整，例如缺少密钥或地址。"""


class ModelError(PMAgentError):
    """模型调用失败：网络、鉴权、返回结构异常等。"""
