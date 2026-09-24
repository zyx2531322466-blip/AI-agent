# 项目管理 Agent

把项目管理里「想法 → 规范 → 任务 → 执行 → 汇报」这条链路，交给一个**可解释、可复用、跨会话接得上**的本地 Agent 接管一部分。

> 一句话形态：**项目就是一个人类可读的文件夹**，Agent 通过会话循环读写它；每轮结束留下交接记录，下次据此接上；每项可复用的做法以"能力单元"形式插拔。

## 文档导航

| 文件 | 回答什么问题 |
| --- | --- |
| [spec.md](./spec.md) | **做什么、为什么**（55 条功能需求、16 条成功标准） |
| [plan.md](./plan.md) | **怎么做**（技术选型、目录结构、里程碑、风险） |
| [tasks.md](./tasks.md) | **按什么顺序做**（89 个任务，每条挂到具体需求） |
| [项目框架.md](./项目框架.md) | **代码长什么样**（每个文件的类与函数、依赖关系、完整数据流） |
| [简历材料.md](./简历材料.md) | **怎么讲**（3 分钟讲稿、难在哪与出处、面试追问的答法） |
| [使用指南.md](./使用指南.md) | **怎么用**（开头是**功能总览**：37 条命令按能力分组、各标读写性质；再是激活环境 → 全流程命令 → 速查表 → 报错怎么办） |
| [收尾核对表.md](./收尾核对表.md) | 走查与演示怎么验（T072 的走查记录在这里） |
| README.md | 怎么跑起来 |

## 当前进度

进度以 [tasks.md](./tasks.md) 为准，这里只说结论：

- **M0 骨架已完成**（T002 ~ T010）：CLI、工作区读写、格式校验、模型接入、阶段框架、跨会话交接、写入前预览与撤回。
- **M1 已完成**（T011 ~ T017）：一句话目标 → 规范 → 按编号引用与修改 → 查来龙去脉 → 逐条确认 → 导出评审稿。
- **M2 已完成**（T018 ~ T025）：规范 → 任务清单（带依赖与优先级）→ 覆盖缺口检查 → 就绪任务排序；改任务要素与标记完成都要过校验。
- **M3 已完成**（T026 ~ T032）：任务四态与变更时间 → 会话开始重建摘要（`resume`）→ 一句话更新状态（`track`）→ 结束写交接记录（`handoff`）→ 冲突校验。
- **M4 已完成**（T033 ~ T037）：每个阶段都有依据 → `--explain` 讲取舍与被放弃的备选 → 学习目标对照 → 导出设计说明。
- **M5 已完成**（T038 ~ T045）：五类风险识别（事实与推测分开）→ 预警处置后不再重复提醒 → 四类分组的进度汇报（每条带来源、按读者调详略、没进展就说没进展）。
- **M6 已完成**（T046 ~ T054）：能力单元的格式与三级渐进式加载 → 会话里沉淀 → 按意思匹配并建议（可拒绝、拒绝后有冷却）→ 采纳记录 → 修订与版本；内置需求评审 / 风险复盘 / 周报汇总 / 完成前验证四个单元。
- **M7 已完成**（T055 ~ T059）：跨项目总览（只读扫描）、项目数据隔离、能力单元跨项目共享（复制，来源不受影响）。
- **M8 已完成**（T060 ~ T066）：把真实项目导出一份副本当示范项目 → 试用留下的东西可以整体丢掉 → 引导式首次使用（`pm-agent guide`）。
- **M9 已完成**（T067 ~ T071）：变更影响分析（含连带影响与"可能要重做"）→ 决策记录 → 任务到需求再到决策的追溯链。
- **M10 已完成**（T078 ~ T093，v0.7 起五次修订）：**让 AI 接手一条任务**（`pm-agent work`）——自动装配这条任务的上下文（完成标准、来源需求、相关决策、相关做法），产出的文件**直接写进项目工作区**（代码落代码文件），同一条变更里附一份记录，因此可整体 `undo`。边界：不覆盖 `spec.md`/`tasks.md`/`project.yaml`/`plan.md` 与 `history/`、不越出项目目录、产出后**推进为"进行中"**、**写入后再当场问一句"算完成了吗"**（`--done` 可自动化；`--yes` 不代判）、**同一条任务默认只做一次**（有既往产出就拦住，`--redo` 才继续且沿用同一套文件）。US-13 / FR-053 / FR-055 / FR-056 / FR-057 / SC-014 / SC-016 / SC-017 / SC-018。
- **收尾**：独立走查 T072 已完成（不看文档走完全链路，四处在走查里暴露的缺陷都已修：引导缺建项目入口、注释里的示例被当成真条目、`demo --reset` 会去清仓库、证书设置被写成注释），材料见 [收尾核对表.md](./收尾核对表.md)。**只剩 T075**：照 [演示脚本.md](./演示脚本.md) 向一个真人完整演示一次——那一步要你本人出面，代码替不了。

> 顺带说一句这次走查最值钱的产出：`pm-agent demo --reset` 原本能作用于任意目录，实际执行时真的删掉了本仓库的 `.git/hooks` 与 `.git/logs`（被权限拦住才停）。现在它只认带 `.pm-agent-demo` 标记的自建示范项目。这条从事故到修复的记录在 [decisions/](./decisions/) 与 spec.md 的 FR-052 里。

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

第一次用，先跑这一条——它会把"建项目 → 走完主链路 → 出汇报"全套讲一遍，不用先读文档：

```powershell
.\.venv\bin\pm-agent.exe guide
```

要一份能回头查的手册（功能总览、激活环境、全流程命令、37 条速查表、报错对照），看 [使用指南.md](./使用指南.md)。

下面用 `pm-agent` 指代 `.\.venv\bin\pm-agent.exe`。注意程序装在 `bin/` 里，
**仓库根目录没有** `pm-agent` 这个文件，所以要写全路径（或者先激活虚拟环境，
那时 `pm-agent` 就能直接用）。任何命令后面加 `--help`，它会列出自己的参数。

```powershell
# 创建一个新项目
pm-agent init ..\我的项目 --name "我的项目" --goal "一句话说清目标" --learning-goal "我想学到什么"
# 不想建版本库就加 --no-git

# 看现状
pm-agent show ..\我的项目

# 列出规范里的需求条目
pm-agent requirements ..\我的项目 --limit 10

# 还有哪些问题没答案 / 给一处疑问定结论并回填 / 逐条确认 / 导出评审稿
pm-agent questions ..\我的项目
pm-agent clarify "标题最长 80 字，超出拒绝保存" --for FR-003 --path ..\我的项目
pm-agent confirm FR-002 --path ..\我的项目
pm-agent review ..\我的项目

# 把规范拆成任务（先给预览与覆盖检查，确认后才写）
pm-agent breakdown ..\我的项目

# 让 AI 接手一条任务：自己读齐上下文 → 产出文件并直接写进项目（附一份记录，可整体撤回）
pm-agent work --path ..\我的项目
pm-agent work T003 --path ..\我的项目

# 看任务：全部 / 现在能动手的 / 覆盖缺口
pm-agent tasks ..\我的项目
pm-agent tasks ..\我的项目 --ready
pm-agent tasks ..\我的项目 --coverage

# 会话三件事：开始先接上、随手更新状态、结束留下交接记录
pm-agent resume ..\我的项目
pm-agent track "T018 做完了，提交 abc123" --path ..\我的项目
pm-agent handoff ..\我的项目

# 讲清"为什么"：某一步的来龙去脉 / 学习目标对照 / 导出设计说明
pm-agent stage specify --explain
pm-agent goals ..\我的项目
pm-agent design ..\我的项目

# 风险与汇报
pm-agent risks ..\我的项目
pm-agent risks ..\我的项目 --ack 超期:T005
pm-agent report ..\我的项目 --audience 上级

# 能力单元：看、用、沉淀
pm-agent skills ..\我的项目
pm-agent skills ..\我的项目 --suggest "帮我评审一下这份需求规范"
pm-agent skill requirement-review --path ..\我的项目
pm-agent skill requirement-review --why --path ..\我的项目
pm-agent skill-use requirement-review --outcome accepted --path ..\我的项目

# 多项目：总览 / 把能力单元共享过去
pm-agent projects ..\项目架
pm-agent skill-share requirement-review --from ..\项目架\甲 --to ..\项目架\乙

# 检查格式（--fix 会自动补建缺失的数据目录）
pm-agent check ..\我的项目 --fix

# 验证模型接入（echo 是离线回声实现，用来跑通流程）
pm-agent ask --provider echo "在吗"

# 让模型把目标整理成规范：先看预览，确认后才写入 spec.md
pm-agent specify ..\我的项目

# 反悔了就撤回最近一次改动
pm-agent undo ..\我的项目
```

`init` 的行为有一条硬规则：**已存在的文件一律跳过，绝不覆盖**。所以你可以在一个已经写过 `spec.md` 的目录里安全地执行它——本仓库就是这么初始化的。

它还会**默认初始化 git 版本库**（`--no-git` 可关闭）。理由见 plan.md §11：有了版本库，交接记录与提交历史就构成"跨会话证据"，也是后续冲突校验的依据。如果这台机器没有 git，它会如实说明并跳过，不影响其他功能。

## 从哪开始：上手路径

这一节是给"知道要做什么、但不知道从哪下手"的时候看的。

### 第 1 步：先跑一遍，看清数据怎么流（约 20 分钟）

```powershell
# 建一个练习项目
pm-agent init ..\练习项目 --name "练习项目" --goal "看懂数据怎么流" --learning-goal "读懂骨架"
```

然后**用编辑器打开** `..\练习项目\project.yaml`，把 `status: active` 改成 `status: paused`，保存，再回来跑：

```powershell
pm-agent show ..\练习项目
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

### 每完成一个任务，固定做四件事

1. 跑测试：`.\.venv\bin\python.exe -m pytest -q`
2. 在 [tasks.md](./tasks.md) 里把那条勾上
3. 改了 `src/` 下的代码，就更新 [项目框架.md](./项目框架.md)（过一遍它 §6 的检查表）
4. 提交：`git add -A`，然后 `git commit -m "T006 阶段框架"`

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
pm-agent ask "你好"
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
.\.venv\bin\python.exe -m pytest -q          # 跑全部测试（默认离线，不花钱）
.\.venv\bin\python.exe -m pytest tests/test_store.py -q   # 只跑读写层
```

**联网测试**（真实调用模型）默认关闭，因为它要联网、要花钱、输出还不完全确定。要跑就显式打开：

```powershell
$env:PM_AGENT_RUN_NETWORK_TESTS = "1"
$env:PM_AGENT_CA_BUNDLE = "C:\msys64\etc\pki\ca-trust\extracted\pem\tls-ca-bundle.pem"
.\.venv\bin\python.exe -m pytest tests/test_specify_live.py -q -s
```

改模板（`src/pm_agent/templates/`）时请同步检查 `src/pm_agent/workspace/format.py` 的校验规则：`create_project` 生成完会自检，不一致会直接报错，不会把坏格式留给使用者。

## 已知限制

- 命令共 37 个，`pm-agent --help` 是权威清单；第一次用先跑 `pm-agent guide`。
- **`demo --reset` 只认本工具建的示范项目**（认 `.pm-agent-demo` 标记文件）。指到别的目录一律拒绝，一个字节都不动；真要清空请自己删。理由见 spec.md 的 FR-052 与 收尾核对表.md 里那次走查事故。
- 需求条目与任务清单都已**真正解析**（能按编号引用、按依赖排序、查覆盖缺口）。
- 新增/修改需求条目还没有命令行入口：它通过 `workspace.requirements` 的接口调用（`confirm` 只切换确认状态）。
- 待澄清的闭环已补上：`questions` 列出（带序号）→ `clarify "结论" --for 来源或序号` 回填进规范，**问题原样留着、后面记上结论**；若那条需求此前被确认过，确认随之作废并提示重新看（FR-054）。
- `track` 的归属判断是**规则式**的（编号优先，其次标题 bigram 重叠），不是模型；所以它先回显再让你确认，认不出就问、不猜。
- `goals` 的"目标 ↔ 任务"匹配同样是**规则式**的，结果一律标"推测"——目标和任务标题之间没有权威对应关系，硬说成结论就是编。
- 风险识别是**规则式**的，只看记录里写着的东西（截止日、更新时间、依赖状态、证据）。"这个任务可能延期"这类没有记录依据的判断，程序不做。
- 能力单元的建议也是**规则式**的（bigram 重叠），不是模型判断；所以它可能出现"看着相关其实不相关"的建议——拒绝一次就会安静两周。
- "多项目"是**一个目录下放多个项目**，不引入账号或全局注册表：当前项目就是你传给命令的那个路径。
- `specify` 的校验是**关键词级**的：能拦住漏项和聊天话术，但拦不住"提到了词却没写好内容"。
- 没有图形界面，演示走命令行。

## 待你完成：T001

读一遍 [spec.md](./spec.md) 和 [plan.md](./plan.md)，写下三个疑问与你的结论。要求：至少有一条带来文档修改，或明确记录一个取舍。

1. 疑问：大致做什么我已经了解了，现在我的疑问是落实到具体该如何做（比如我该从哪里开始编写代码）
   **答**：见上文《从哪开始：上手路径》。这一问带来了一处文档补充——原来的 spec / plan 说清了做什么与怎么设计，却没有给"人从哪里下手"的入口，README 现在补上了这一节。
2. 疑问：
4. 疑问：
