"""OpenAI 兼容接口的实现（本项目的默认模型接入方式）。

只用标准库 urllib，不额外引 HTTP 客户端：需求很单纯——POST 一段
JSON、取回一段文本，多一层封装就多一处要解释的东西。

**为什么 DeepSeek 可以直接用**：它提供的就是 OpenAI 兼容接口
（``POST /chat/completions``），所以换服务商只是换 ``base_url`` 与
``model`` 两个值，代码一行不动——这正是 plan.md §3 把模型接入
收在接口后面的目的。

配置全部走环境变量：

- PM_AGENT_MODEL_BASE_URL：接口地址，默认取服务商预设（DeepSeek）
- PM_AGENT_MODEL_API_KEY ：密钥（必填）
- PM_AGENT_MODEL_NAME    ：模型名，默认取服务商预设（deepseek-chat）
- PM_AGENT_MODEL_TIMEOUT ：超时秒数，默认 60
- PM_AGENT_CA_BUNDLE     ：自定义 CA 证书文件（见 README 的 MSYS2 说明）
"""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass

from ..errors import ModelConfigError, ModelError
from .base import Message, ModelProvider

BASE_URL_ENV = "PM_AGENT_MODEL_BASE_URL"
API_KEY_ENV = "PM_AGENT_MODEL_API_KEY"
MODEL_NAME_ENV = "PM_AGENT_MODEL_NAME"
TIMEOUT_ENV = "PM_AGENT_MODEL_TIMEOUT"
CA_BUNDLE_ENV = "PM_AGENT_CA_BUNDLE"
PROVIDER_ENV = "PM_AGENT_MODEL_PROVIDER"

#: 提示里反复要用到"改用离线回声"这句话，集中在一处，避免各处写不一致
PROVIDER_ENV_HINT = f"{PROVIDER_ENV}=echo"

DEFAULT_TIMEOUT = 60.0


@dataclass(frozen=True)
class Preset:
    """一个服务商的默认接入参数。"""

    label: str
    base_url: str
    model: str


#: 服务商预设。换服务商 = 在这里加一行，其余代码不动。
PRESETS: dict[str, Preset] = {
    "deepseek": Preset(
        label="DeepSeek",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
    ),
    "openai-compat": Preset(
        label="OpenAI 兼容",
        base_url="https://api.openai.com/v1",
        model="gpt-4o-mini",
    ),
}

#: 本项目选定的服务商（见 plan.md §3 与 §11）
DEFAULT_PRESET = "deepseek"


class OpenAICompatProvider(ModelProvider):
    """任何兼容 POST /chat/completions 的服务都能接。

    注意区分两件事：**协议**是 OpenAI 兼容（类名说的就是这个），
    **服务商**由 ``label`` 表示（例如 DeepSeek）。给使用者看的说明
    必须用服务商的名字——否则配了 DeepSeek 却显示 openai-compat，会误导。
    """

    name = "openai-compat"
    is_remote = True

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        label: str = "OpenAI 兼容",
        timeout: float = DEFAULT_TIMEOUT,
        ca_bundle: str | None = None,
    ) -> None:
        if not api_key.strip():
            raise ModelConfigError(
                f"{API_KEY_ENV} 是空的",
                hint=f"设置一个有效密钥，或改用离线回声实现：{PROVIDER_ENV_HINT}",
            )
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.label = label
        self.timeout = timeout
        self.ca_bundle = ca_bundle

    def describe(self) -> str:
        return f"{self.label}：{self.model}（走 OpenAI 兼容接口）"

    @classmethod
    def from_env(cls, preset_name: str = DEFAULT_PRESET) -> "OpenAICompatProvider":
        """按预设 + 环境变量构造。

        环境变量优先于预设：预设给一套能用的默认值，需要微调时再覆盖。
        """
        preset = PRESETS.get(preset_name) or PRESETS[DEFAULT_PRESET]

        api_key = os.environ.get(API_KEY_ENV, "")
        if not api_key.strip():
            raise ModelConfigError(
                f"没有配置 {API_KEY_ENV}（当前服务商：{preset.label}）",
                hint=(
                    "两种选择：① 设置密钥与模型名后再试；"
                    f"② 先用离线回声实现跑通流程：{PROVIDER_ENV_HINT}"
                ),
            )

        raw_timeout = os.environ.get(TIMEOUT_ENV, "")
        try:
            timeout = float(raw_timeout) if raw_timeout.strip() else DEFAULT_TIMEOUT
        except ValueError as exc:
            raise ModelConfigError(
                f"{TIMEOUT_ENV} 不是数字：{raw_timeout}",
                hint=f"例如 {TIMEOUT_ENV}=30",
            ) from exc

        return cls(
            api_key=api_key,
            base_url=os.environ.get(BASE_URL_ENV) or preset.base_url,
            model=os.environ.get(MODEL_NAME_ENV) or preset.model,
            label=preset.label,
            timeout=timeout,
            ca_bundle=os.environ.get(CA_BUNDLE_ENV) or None,
        )

    # ---- 调用 ----------------------------------------------------------

    def endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"

    def _ssl_context(self) -> ssl.SSLContext:
        if self.ca_bundle:
            return ssl.create_default_context(cafile=self.ca_bundle)
        return ssl.create_default_context()

    def complete(
        self,
        messages: list[Message],
        *,
        temperature: float = 0.2,
        max_tokens: int | None = None,
    ) -> str:
        payload: dict[str, object] = {
            "model": self.model,
            "messages": [message.to_dict() for message in messages],
            "temperature": temperature,
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        request = urllib.request.Request(
            self.endpoint(),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout, context=self._ssl_context()
            ) as response:
                body = response.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raise self._http_error(exc) from exc
        except urllib.error.URLError as exc:
            raise ModelError(
                f"连不上模型服务：{exc.reason}",
                hint=(
                    "检查网络与代理；若提示证书问题（MSYS2 上常见），"
                    f"把系统 CA 包路径设给 {CA_BUNDLE_ENV}，例如 "
                    r"C:\msys64\etc\pki\ca-trust\extracted\pem\tls-ca-bundle.pem"
                ),
            ) from exc
        except TimeoutError as exc:
            raise ModelError(
                f"模型服务超过 {self.timeout:g} 秒没有响应",
                hint=f"调大超时：{TIMEOUT_ENV}=120，或改用一个更快的模型",
            ) from exc

        return self._extract_text(body)

    def _http_error(self, exc: urllib.error.HTTPError) -> ModelError:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:300]
        except Exception:
            detail = ""

        hints = {
            401: f"密钥无效或缺失，检查 {API_KEY_ENV}",
            403: "密钥没有访问这个模型的权限",
            404: f"地址或模型名不对，检查 {BASE_URL_ENV} 与 {MODEL_NAME_ENV}",
            429: "触发限流，稍后重试或降低调用频率",
        }
        hint = hints.get(exc.code, "这是模型服务返回的错误，详情见上面的原文")
        suffix = f"；服务端说明：{detail}" if detail else ""
        return ModelError(f"模型服务返回 HTTP {exc.code}{suffix}", hint=hint)

    @staticmethod
    def _extract_text(body: str) -> str:
        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ModelError(
                f"模型服务返回的不是 JSON：{body[:200]}",
                hint=f"确认 {BASE_URL_ENV} 指向的是兼容 /chat/completions 的接口",
            ) from exc

        if isinstance(data, dict) and data.get("error"):
            raise ModelError(f"模型服务返回错误：{data['error']}")

        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            keys = ", ".join(sorted(data)) if isinstance(data, dict) else type(data).__name__
            raise ModelError(
                f"返回结构不是预期的 choices[0].message.content（顶层字段：{keys}）",
                hint="确认接口是 OpenAI 兼容格式",
            ) from exc

        if not isinstance(content, str):
            raise ModelError(f"回复内容不是文本，而是 {type(content).__name__}")
        return content
