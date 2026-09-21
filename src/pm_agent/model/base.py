"""模型接入的统一接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Message:
    """一条对话消息。role 取 system / user / assistant。"""

    role: str
    content: str

    def to_dict(self) -> dict[str, str]:
        return {"role": self.role, "content": self.content}


class ModelProvider(ABC):
    """所有模型实现的共同接口。

    故意只留一个方法：会话循环、上下文装配这些"真正属于产品"的部分
    （见 plan.md §5.3）不应该藏在模型实现里。
    """

    name: str = "unknown"
    #: 是否真的会调用外部服务。EchoProvider 为 False，
    #: 用于在无网络、无密钥时验证上层逻辑。
    is_remote: bool = True

    @abstractmethod
    def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        """给定对话，返回模型的文本回复。"""

    def describe(self) -> str:
        """给使用者看的一行说明，用于 show 之类的输出。"""
        return self.name
