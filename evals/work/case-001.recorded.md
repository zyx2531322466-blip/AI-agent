
# T001 交付物

## 1. 做法

**要动的文件**（全部新建，项目当前无既有代码）：

1. `todo.py` —— 核心模块。放两个东西：一个存储层（读写本地 JSON 文件），一个 `add_todo(title)` 函数（校验 + 落盘 + 返回新记录）。选 JSON 文件而不是数据库，因为项目目标是"只在本地跑"，JSON 零依赖、可读、够用。
2. `test_todo.py` —— 验证脚本。覆盖完成标准的两条：新增后能读回、空标题被拒绝。

**顺序**：先写存储层（`_load` / `_save`），再写 `add_todo`，最后写测试。先有读写地基，新增才有地方落。

**为什么这么切**：FR-001 只要求"能新增一条待办，字段含标题与是否完成"。所以这一版只做**新增**和**读回**，不做列表展示、不做标完成、不做按天回顾——那些是后续任务。`add_todo` 返回完整记录（含 `id`、`title`、`done`、`created_at`），是为了让后续任务能直接复用这条记录，不用回头改结构。

**字段设计**（对齐 FR-001，并为后续留位）：
- `id`：自增整数，本地唯一即可
- `title`：字符串，非空（去空白后）
- `done`：布尔，新增时固定 `False`
- `created_at`：ISO 时间戳，为"按天回顾"预留

## 2. 交付物

### 文件：`todo.py`

```python
"""本地待办清单 —— 存储与新增（T001 / FR-001）。"""

import json
import os
from datetime import datetime

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "todos.json")


def _load():
    """读取全部待办。文件不存在或为空时返回空列表。"""
    if not os.path.exists(DATA_FILE):
        return []
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        content = f.read().strip()
        if not content:
            return []
        return json.loads(content)


def _save(todos):
    """把全部待办写回文件。"""
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(todos, f, ensure_ascii=False, indent=2)


def add_todo(title):
    """新增一条待办。

    参数:
        title: 待办标题，字符串。去空白后不能为空。

    返回:
        新增的待办记录 dict，含 id / title / done / created_at。

    异常:
        ValueError: 标题为空或只有空白时抛出。
    """
    if not isinstance(title, str) or not title.strip():
        raise ValueError("标题不能为空")

    todos = _load()
    next_id = max((t["id"] for t in todos), default=0) + 1

    todo = {
        "id": next_id,
        "title": title.strip(),
        "done": False,
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    todos.append(todo)
    _save(todos)
    return todo


def get_todo(todo_id):
    """按 id 读回一条待办，找不到返回 None。"""
    for t in _load():
        if t["id"] == todo_id:
            return t
    return None
```

### 文件：`test_todo.py`

```python
"""T001 验证脚本：新增后能读回，空标题被拒绝。"""

import os
import tempfile

import todo


def _use_temp_file():
    """把数据文件指到临时路径，避免污染真实数据。"""
    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.remove(path)  # 让 _load 从"文件不存在"开始
    todo.DATA_FILE = path
    return path


def test_add_then_read_back():
    _use_temp_file()
    created = todo.add_todo("买牛奶")
    assert created["title"] == "买牛奶"
    assert created["done"] is False
    assert isinstance(created["id"], int)

    read_back = todo.get_todo(created["id"])
    assert read_back is not None
    assert read_back["title"] == "买牛奶"
    assert read_back["done"] is False
    print("PASS: 新增后能读回")


def test_empty_title_rejected():
    _use_temp_file()
    for bad in ["", "   ", "\t\n"]:
        try:
            todo.add_todo(bad)
        except ValueError:
            continue
        raise AssertionError(f"空标题未被拒绝: {bad!r}")
    print("PASS: 空标题被拒绝")


def test_multiple_adds_get_unique_ids():
    _use_temp_file()
    a = todo.add_todo("第一条")
    b = todo.add_todo("第二条")
    assert a["id"] != b["id"]
    assert todo.get_todo(a["id"])["title"] == "第一条"
    assert todo.get_todo(b["id"])["title"] == "第二条"
    print("PASS: 多条新增 id 唯一且各自可读回")


if __name__ == "__main__":
    test_add_then_read_back()
    test_empty_title_rejected()
    test_multiple_adds_get_unique_ids()
    print("\n全部通过")
```

## 3. 怎么验证

**跑什么**：

```bash
python test_todo.py
```

**看什么**：

- 三条 `PASS` 依次打印，最后一行是 `全部通过`。
- 任何 `AssertionError` 或 `ValueError` 冒出来 = 不通过。

**逐条对完成标准**：

| 完成标准 | 对应验证 | 通过条件 |
|---|---|---|
| 新增一条后能读回 | `test_add_then_read_back` | `add_todo` 返回的记录，用其 `id` 经 `get_todo` 读回，`title` 与 `done` 一致 |
| 空标题被拒绝 | `test_empty_title_rejected` | `""`、`"   "`、`"\t\n"` 三种输入都抛 `ValueError` |

**手动确认（可选）**：在项目目录跑 `python -c "import todo; print(todo.add_todo('测试'))"`，然后看目录下生成的 `todos.json` 里确实多了一条 `done: false` 的记录。

## 4. 没做什么

- **没做列表展示、标完成、按天回顾**：这些不在 FR-001 范围内，属于后续任务。`done` 字段已落盘但本任务不提供修改入口。
- **没做并发/多进程写入保护**：本地单人使用场景下未处理，若将来要同时开多个进程写同一文件，需要加锁——这是需要使用者拍板是否要做的事。
- **没定 `todos.json` 的存放位置策略**：当前放在 `todo.py` 同目录。如果使用者希望放到用户目录（如 `~/.todo/`）或可配置，需要拍板。
- **没做标题长度上限、去重**：FR-001 未要求，未加。
- **`created_at` 用的是本地时间**：为"按天回顾"预留，但时区/格式（本地 vs UTC）未与使用者确认，后续做回顾功能时可能需要统一。
