"""模型接入层的测试（T005）。

完成标准有两条：**正常返回文本** + **缺配置时错误信息清晰**。
这里不联网，用 echo 实现与直接调用解析函数来验证。
"""

from __future__ import annotations

import pytest

from pm_agent.errors import ModelConfigError, ModelError
from pm_agent.model import EchoProvider, Message, get_provider
from pm_agent.model.openai_compat import (
    API_KEY_ENV,
    BASE_URL_ENV,
    DEFAULT_PRESET,
    MODEL_NAME_ENV,
    PRESETS,
    OpenAICompatProvider,
    PROVIDER_ENV,
)


def test_echo_provider_returns_text_and_marks_itself() -> None:
    reply = EchoProvider().complete([Message(role="user", content="你好")])
    assert "你好" in reply
    assert "[echo]" in reply, "回声实现必须标明自己不是真实模型（FR-037）"


def test_get_provider_returns_echo() -> None:
    provider = get_provider("echo")
    assert isinstance(provider, EchoProvider)
    assert provider.is_remote is False


def test_get_provider_rejects_unknown_name() -> None:
    with pytest.raises(ModelConfigError) as excinfo:
        get_provider("不存在的实现")
    assert "openai-compat" in (excinfo.value.hint or "")


def test_default_provider_needs_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """默认实现缺密钥时必须明确报错，而不是悄悄退回 echo（FR-037）。"""
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    monkeypatch.delenv(PROVIDER_ENV, raising=False)
    with pytest.raises(ModelConfigError) as excinfo:
        get_provider()
    assert API_KEY_ENV in str(excinfo.value)
    assert "echo" in (excinfo.value.hint or "")


def test_provider_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(API_KEY_ENV, "test-key")
    monkeypatch.setenv(PROVIDER_ENV, "openai-compat")
    provider = get_provider()
    assert isinstance(provider, OpenAICompatProvider)
    assert provider.model  # 有默认模型名


def test_empty_api_key_is_rejected() -> None:
    with pytest.raises(ModelConfigError):
        OpenAICompatProvider(api_key="   ", base_url="https://example.com/v1", model="m")


def test_endpoint_join() -> None:
    provider = OpenAICompatProvider(
        api_key="k", base_url="https://example.com/v1/", model="m"
    )
    assert provider.endpoint() == "https://example.com/v1/chat/completions"


def test_default_provider_is_deepseek(monkeypatch: pytest.MonkeyPatch) -> None:
    """本项目选定 DeepSeek（plan.md §11），默认实现应当指向它。"""
    assert DEFAULT_PRESET == "deepseek"
    monkeypatch.setenv(API_KEY_ENV, "test-key")
    monkeypatch.delenv(PROVIDER_ENV, raising=False)
    monkeypatch.delenv(BASE_URL_ENV, raising=False)
    monkeypatch.delenv(MODEL_NAME_ENV, raising=False)

    provider = get_provider()
    assert isinstance(provider, OpenAICompatProvider)
    assert "deepseek" in provider.base_url
    assert provider.model == PRESETS["deepseek"].model
    # 给使用者看的说明必须是服务商的名字，不能是协议名
    assert "DeepSeek" in provider.describe()
    assert "deepseek-chat" in provider.describe()


def test_env_overrides_preset(monkeypatch: pytest.MonkeyPatch) -> None:
    """预设给默认值，环境变量负责微调。"""
    monkeypatch.setenv(API_KEY_ENV, "test-key")
    monkeypatch.setenv(BASE_URL_ENV, "https://my-proxy.example/v1")
    monkeypatch.setenv(MODEL_NAME_ENV, "my-model")
    provider = get_provider("deepseek")
    assert provider.base_url == "https://my-proxy.example/v1"
    assert provider.model == "my-model"


def test_deepseek_uses_openai_compatible_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """DeepSeek 说的是 OpenAI 兼容协议，所以路径不变，只换地址与模型名。"""
    monkeypatch.setenv(API_KEY_ENV, "test-key")
    monkeypatch.delenv(BASE_URL_ENV, raising=False)
    monkeypatch.delenv(MODEL_NAME_ENV, raising=False)
    provider = get_provider("deepseek")
    assert provider.endpoint() == "https://api.deepseek.com/v1/chat/completions"


def test_extract_text_parses_standard_response() -> None:
    body = '{"choices": [{"message": {"content": "答案"}}]}'
    assert OpenAICompatProvider._extract_text(body) == "答案"


def test_extract_text_reports_error_payload() -> None:
    with pytest.raises(ModelError):
        OpenAICompatProvider._extract_text('{"error": {"message": "余额不足"}}')


def test_extract_text_reports_unexpected_shape() -> None:
    with pytest.raises(ModelError) as excinfo:
        OpenAICompatProvider._extract_text('{"result": "ok"}')
    assert "result" in str(excinfo.value), "报错时要带上实际收到的字段，便于排查"


def test_extract_text_reports_non_json() -> None:
    with pytest.raises(ModelError):
        OpenAICompatProvider._extract_text("<html>502 Bad Gateway</html>")
