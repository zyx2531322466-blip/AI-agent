"""项目工作区：格式定义、读写层、模板渲染。

对应 plan.md §2「项目即目录」——不引入数据库，项目就是一个装满
Markdown + YAML 的文件夹，使用者可以直接打开、手工修改。
"""

from .store import Project, create_project

__all__ = ["Project", "create_project"]
