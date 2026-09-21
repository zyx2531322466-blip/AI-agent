from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from importlib.resources import files
from types import MappingProxyType
from typing import Mapping

import yaml

from ..errors import PMAgentError

_FIELDS = ("title", "purpose", "inputs", "outputs")


@dataclass(frozen=True, slots=True)
class Stage:
    """一个阶段需要展示给使用者的说明。"""

    title: str
    purpose: str
    inputs: str
    outputs: str


def _stages() -> tuple[tuple[str, Stage], ...]:
    """读取并校验内置阶段；缓存避免每次调用都解析 YAML。"""
    text = files(__name__).joinpath("stages.yaml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)

    if not isinstance(data, dict):
        raise PMAgentError(
            "stages.yaml 的顶层必须是阶段字典。",
            hint="请检查 stages.yaml 的顶层结构和缩进。",
        )

    stages: list[tuple[str, Stage]] = []
    for key, raw in data.items():
        if not isinstance(key, str) or not isinstance(raw, dict):
            raise PMAgentError(
                "stages.yaml 里有格式不正确的阶段条目。",
                hint="每个阶段都应写成“阶段名:”加四个文本字段。",
            )

        values: dict[str, str] = {}
        for field in _FIELDS:
            value = raw.get(field)
            if not isinstance(value, str) or not value.strip():
                raise PMAgentError(
                    f"阶段 {key!r} 缺少有效的 {field}。",
                    hint=f"请在 stages.yaml 的 {key}.{field} 写入非空文本。",
                )
            values[field] = value.strip()

        stages.append((key, Stage(**values)))

    return tuple(stages)


def load_stages() -> Mapping[str, Stage]:
    """返回全部内置阶段。"""
    return MappingProxyType(dict(_stages()))


def get_stage(key: str) -> Stage:
    """按名字取得阶段；未知名字给出可选阶段提示。"""
    stages = load_stages()
    try:
        return stages[key]
    except KeyError as exc:
        choices = " / ".join(stages)
        raise PMAgentError(
            f"没有名为 {key!r} 的阶段。",
            hint=f"可用的阶段：{choices}。",
        ) from exc


def announce(key: str) -> str:
    """把阶段说明渲染为三行：目的、输入、预期产出。"""
    stage = get_stage(key)
    return "\n".join(
        (
            f"{stage.title}｜目的：{stage.purpose}",
            f"输入：{stage.inputs}",
            f"预期产出：{stage.outputs}",
        )
    )