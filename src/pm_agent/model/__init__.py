"""模型接入层：把「用哪个模型」收在一个接口后面（plan.md §3）。

本项目的其余部分只认 ModelProvider，不认任何具体厂商。
换模型 = 换一个实现类，其余代码不动。
"""

from __future__ import annotations

import os

from ..errors import ModelConfigError
from .base import Message, ModelProvider
from .echo import EchoProvider
from .openai_compat import PRESETS, PROVIDER_ENV, OpenAICompatProvider

#: 本项目选定的服务商（见 plan.md §3 与 §11）
DEFAULT_PROVIDER = "deepseek"

_ECHO_NAMES = frozenset({"echo", "stub"})
_COMPAT_ALIASES = {"openai": "openai-compat", "compat": "openai-compat"}


def get_provider(name: str | None = None) -> ModelProvider:
    """按名字取一个模型实现；名字缺省时读环境变量。

    默认是 deepseek。没有配密钥会直接报错，而不会悄悄退回 echo——
    静默降级会让使用者把回声当成真实结果（FR-037）。
    """
    resolved = (name or os.environ.get(PROVIDER_ENV) or DEFAULT_PROVIDER).strip().lower()
    resolved = _COMPAT_ALIASES.get(resolved, resolved)

    if resolved in _ECHO_NAMES:
        return EchoProvider()
    if resolved in PRESETS:
        return OpenAICompatProvider.from_env(resolved)

    options = "、".join([DEFAULT_PROVIDER, *(name for name in PRESETS if name != DEFAULT_PROVIDER), "echo"])
    raise ModelConfigError(
        f"未知的模型实现：{resolved}",
        hint=(
            f"可选：{options}（默认 {DEFAULT_PROVIDER}）。"
            f"也可以用环境变量 {PROVIDER_ENV} 指定，例如 {PROVIDER_ENV}=echo"
        ),
    )


__all__ = [
    "Message",
    "ModelProvider",
    "EchoProvider",
    "OpenAICompatProvider",
    "get_provider",
    "PROVIDER_ENV",
]
