"""不联网的回声实现。

用途只有两个，别拿它当模型用：

1. 没有密钥、没有网络时，验证 CLI 与上层逻辑能不能跑通；
2. 测试里作为确定性替身（同样的输入永远给同样的输出）。

它**不假装**自己是模型：输出里会明确标注这是回声结果，
避免使用者把占位内容当成真实产出（FR-037）。
"""

from __future__ import annotations

from .base import Message, ModelProvider

ECHO_MARKER = "[echo]"


class EchoProvider(ModelProvider):
    """把最后一条 user 消息原样回显，用于联调与测试。"""

    name = "echo"
    is_remote = False

    def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        last_user = next(
            (message.content for message in reversed(messages) if message.role == "user"),
            "",
        )
        return (
            f"{ECHO_MARKER} 这是回声实现，不是真实模型输出。\n"
            f"共收到 {len(messages)} 条消息，最后一条用户输入是：\n{last_user}"
        )
