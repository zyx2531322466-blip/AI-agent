# 项目管理 Agent

把项目管理里「想法 → 规范 → 任务 → 执行 → 汇报」这条链路，交给一个**可解释、可复用、跨会话接得上**的本地 Agent 接管一部分。

> 一句话形态：**项目就是一个人类可读的文件夹**，Agent 通过会话循环读写它；每轮结束留下交接记录，下次据此接上；每项可复用的做法以"能力单元"形式插拔。

## 文档导航

| 文件 | 回答什么问题 |
| --- | --- |
| [spec.md](./spec.md) | **做什么、为什么**（51 条功能需求、13 条成功标准） |
| [plan.md](./plan.md) | **怎么做**（技术选型、目录结构、里程碑、风险） |
| [tasks.md](./tasks.md) | **按什么顺序做**（76 个任务） |
| README.md | 怎么跑起来 |

## 当前进度

对应 [tasks.md](./tasks.md) 的 M0：**T002 ~ T005 已完成**，T001 留给你。

| 任务 | 内容 | 状态 |
| --- | --- | --- |
| T002 | 工具仓库骨架 + 依赖管理 + 可运行 CLI | ✅ |
| T003 | 项目工作区格式定义 + 模板 | ✅ |
| T004 | 工作区读写层 + 格式校验 | ✅ |
| T005 | 模型接入接口 + 默认实现 | ✅ |
| T001 | 写下你对 spec / plan 的 3 个疑问 | ⬜ 见文末 |

`M0` 剩下的 T006 ~ T010（阶段框架、交接记录、预览撤回、失败显式化、测试骨架）还未开始。

## 环境

这台机器上的 Python 是 **MSYS2 版**（`C:\msys64\ucrt64\bin\python.exe`，3.12.11），不是 Windows 官方安装版。这带来两个必须知道的差异：

1. **虚拟环境的目录是 `bin/` 而不是 `Scripts/`**（POSIX 布局）。所以命令是 `.\.venv\bin\python.exe`，不是 `.\.venv\Scripts\python.exe`。
2. **pip 需要手动指定 CA 证书**，否则报 `CERTIFICATE_VERIFY_FAILED`。本机的证书包在：

   ```
   C:\msys64\etc\pki\ca-trust\extracted\pem\tls-ca-bundle.pem
   ```

   装包时这样用（正规的 TLS 校验，不是绕过）：

   ```powershell
   $env:PIP_CERT = "C:\msys64\etc\pki\ca-trust\extracted\pem\tls-ca-bundle.pem"
   .\.venv\bin\python.exe -m pip install <包名>
   ```

虚拟环境已经建好（`.venv/`），依赖也装好了。要重建：

```powershell
& "C:\msys64\ucrt64\bin\python.exe" -m venv .venv
.\.venv\bin\python.exe -m pip install --editable ".[dev]"
```

## 快速开始

所有命令都用 `.\.venv\bin\pm-agent.exe`（或 `.\.venv\bin\python.exe -m pm_agent`）。

```powershell
# 创建一个新项目
.\pm-agent init ..\我的项目 --name "我的项目" --goal "一句话说清目标" --learning-goal "我想学到什么"
# 不想建版本库就加 --no-git

# 看现状
.\pm-agent show ..\我的项目

# 检查格式（--fix 会自动补建缺失的数据目录）
.\pm-agent check ..\我的项目 --fix

# 验证模型接入（echo 是离线回声实现，用来跑通流程）
.\pm-agent ask --provider echo "在吗"
```

`init` 的行为有一条硬规则：**已存在的文件一律跳过，绝不覆盖**。所以你可以在一个已经写过 `spec.md` 的目录里安全地执行它——本仓库就是这么初始化的。

它还会**默认初始化 git 版本库**（`--no-git` 可关闭）。理由见 plan.md §11：有了版本库，交接记录与提交历史就构成"跨会话证据"，也是后续冲突校验的依据。如果这台机器没有 git，它会如实说明并跳过，不影响其他功能。

## 从哪开始：上手路径

这一节是给"知道要做什么、但不知道从哪下手"的时候看的。

### 第 1 步：先跑一遍，看清数据怎么流（约 20 分钟）

```powershell
# 建一个练习项目
.\pm-agent init ..\练习项目 --name "练习项目" --goal "看懂数据怎么流" --learning-goal "读懂骨架"
```

然后**用编辑器打开** `..\练习项目\project.yaml`，把 `status: active` 改成 `status: paused`，保存，再回来跑：

```powershell
.\pm-agent show ..\练习项目
```

如果 `show` 里显示"状态 paused"，你就已经摸到这个项目的核心主张了：**数据不在程序里，在你随时能打开的文件里**。这个直觉后面每一步都要用。

### 第 2 步：按数据流读代码，别按目录读（约 30 分钟）

| 顺序 | 文件 | 读它回答什么问题 |
| --- | --- | --- |
| 1 | `src/pm_agent/cli.py` | 用户能做什么？命令从哪进来？错误怎么变成"怎么办"？ |
| 2 | `src/pm_agent/workspace/store.py` | 一个项目怎么被打开？读写为什么必须先收敛到这里？ |
| 3 | `src/pm_agent/workspace/format.py` | 什么算合法？`error` 与 `warn` 的区别是什么？ |
| 4 | `src/pm_agent/model/base.py` | 模型在哪一层被调用（以及为什么不该更靠上） |

`errors.py`、`templates/__init__.py`、`workspace/files.py` 扫一眼就行，用到再细看。

### 第 3 步：做第一个动手任务 T006

先把落点看清楚再动手：

| 要加/要改 | 位置 | 为什么在这里 |
| --- | --- | --- |
| 阶段描述 | 建议新增 `src/pm_agent/stages/stages.yaml` | 这些文字是**内容**不是逻辑，改文案不该碰代码 |
| 阶段框架 | 新增 `src/pm_agent/stages/__init__.py` | 提供 `announce(阶段名)`：输出目的 / 输入 / 预期产出 |
| 命令入口 | 改 `src/pm_agent/cli.py` | 加 `pm-agent stage <名字>`，用来演示与测试 |
| 测试 | 新增 `tests/test_stages.py` | 断言四个内置阶段（specify / plan / tasks / track）都输出三行、且内容非空 |

**先写这三行文字，再写代码**。`目的 / 输入 / 预期产出` 该写成什么样，是 T006 真正的难点——请把它当成"给一个人看的说明书"，而不是给程序解析的字段。这一层的手感定了，后面 `specify`、`tasks`、`report` 每个阶段都会沿用。

**怎么算做完**：`pm-agent stage specify` 能打印出该阶段的三行说明，并且 `pytest` 里有一条测试守着它。

### 每完成一个任务，固定做三件事

1. 跑测试：`.\.venv\bin\python.exe -m pytest -q`
2. 在 [tasks.md](./tasks.md) 里把那条勾上
3. 提交：`git add -A`，然后 `git commit -m "T006 阶段框架"`

> 这个仓库还没做过首次提交，而且这台机器上还没有配 git 身份。第一次提交前先在**仓库内**设置（不加 `--global`，只影响这个仓库）：
>
> ```powershell
> git config user.name "你的名字"
> git config user.email "你的邮箱"
> ```

如果中途发现 spec 或 plan 需要改：**先改文档并升版本**，再回 [plan.md](./plan.md) §12 的偏差记录表登记一行。

## 配置模型

默认接 **DeepSeek**（`deepseek-chat`）。它提供 OpenAI 兼容接口，所以接入方式就是本层默认实现。全部走环境变量：

| 环境变量 | 作用 | 默认值 |
| --- | --- | --- |
| `PM_AGENT_MODEL_PROVIDER` | 服务商：`deepseek`、`openai-compat`、`echo` | `deepseek` |
| `PM_AGENT_MODEL_API_KEY` | 密钥（必填） | 无 |
| `PM_AGENT_MODEL_BASE_URL` | 接口地址（覆盖预设） | 预设：`https://api.deepseek.com/v1` |
| `PM_AGENT_MODEL_NAME` | 模型名（覆盖预设） | 预设：`deepseek-chat` |
| `PM_AGENT_MODEL_TIMEOUT` | 超时秒数 | `60` |
| `PM_AGENT_CA_BUNDLE` | 自定义 CA 证书文件 | 系统默认 |

```powershell
$env:PM_AGENT_MODEL_API_KEY = "sk-..."     # 在 DeepSeek 控制台申请
# MSYS2 上如果报证书错误，加上这一行：
$env:PM_AGENT_CA_BUNDLE     = "C:\msys64\etc\pki\ca-trust\extracted\pem\tls-ca-bundle.pem"
.\pm-agent ask "你好"
```

**没有密钥时程序会直接报错，不会悄悄退回 echo**——静默降级会让人把回声当成真实结果（FR-037）。

换别的服务商：在 `src/pm_agent/model/openai_compat.py` 的 `PRESETS` 里加一行即可，其余代码不用动。

**密钥怎么处理**：程序只从环境变量读取密钥，不会把它写进任何项目文件；`.gitignore` 也已排除 `.env` 与 `.env.local`。所以密钥不会进入交接记录、决策记录，也不会被提交进版本库。

**验证状态**：2026-09-13 已用真实 DeepSeek 调用跑通（`ask "你好"` 正常返回），以及两条失败路径——无效密钥（HTTP 401 + 可操作提示）、缺少密钥（明确报错并给出两条出路）。

## 两个"目录"要分清

### 工具仓库（你正在读的这个）

```
src/pm_agent/
  cli.py            # 命令入口：init / show / check / ask
  errors.py         # 可预期失败的类型，每个错误都带"怎么办"
  workspace/        # 格式定义、读写层、校验（T003 / T004）
  model/            # 模型接入层（T005）
  templates/        # 生成新项目用的模板
tests/              # 36 个测试
```

### 项目工作区（工具管理的对象）

```
<project>/
  .git/             # 版本库（默认初始化）
  project.yaml      # 元信息 + 学习目标
  spec.md           # 规范
  plan.md           # 实现计划
  tasks.md          # 任务清单
  evidence/         # 完成证据
  decisions/        # 决策记录
  sessions/         # 交接记录（一次会话一个文件）
  reports/          # 进度汇报
  skills/           # 本项目沉淀的能力单元
  history/          # 版本历史
```

本仓库同时是这两个角色：根目录有工具代码，也被初始化成了一个项目工作区（`project.yaml` + 上面六个目录）。

## 开发

```powershell
.\.venv\bin\python.exe -m pytest -q          # 跑全部测试
.\.venv\bin\python.exe -m pytest tests/test_store.py -q   # 只跑读写层
```

改模板（`src/pm_agent/templates/`）时请同步检查 `src/pm_agent/workspace/format.py` 的校验规则：`create_project` 生成完会自检，不一致会直接报错，不会把坏格式留给使用者。

## 已知限制

- 只有 5 个命令；`specify` / `tasks` / `report` / `skill` / `export` 还没实现（见 tasks.md）。
- 写入还没有"预览 + 撤回"（T008），目前的写入入口已经收敛到 `Project.write_text`，就是为了那条需求好做。
- 需求条目与任务清单只是**编号统计**，还没有解析成结构化对象（T012 / T018）。
- 没有图形界面，演示走命令行。

## 待你完成：T001

读一遍 [spec.md](./spec.md) 和 [plan.md](./plan.md)，写下三个疑问与你的结论。要求：至少有一条带来文档修改，或明确记录一个取舍。

1. 疑问：大致做什么我已经了解了，现在我的疑问是落实到具体该如何做（比如我该从哪里开始编写代码）
   **答**：见上文《从哪开始：上手路径》。这一问带来了一处文档补充——原来的 spec / plan 说清了做什么与怎么设计，却没有给"人从哪里下手"的入口，README 现在补上了这一节。
2. 疑问：
4. 疑问：
