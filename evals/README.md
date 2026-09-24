# 金样本（evals/）

固定输入 + **录制的真实模型输出**，用来在没有网络、不花钱的情况下回放整条链路。

## 为什么要有这一层

三种测试各管一段，谁也替代不了谁：

| 手段 | 能证明什么 | 证明不了什么 |
| --- | --- | --- |
| 假 provider（`tests/test_specify.py`） | 我们的管道通：提示词组装、清理、校验、落盘 | 提示词真能要到合格输出吗 |
| 联网测试（`tests/test_specify_live.py`） | 真模型**这一次**做对了 | 下次改代码还会不会做对 |
| **金样本（这里）** | 把"真模型那次做对了"固定下来，之后每次改代码都能重放 | 输入换了呢 |

## 目录约定

```
evals/specify/
  case-001.yaml            # 输入：项目名、目标、学习目标
  case-001.recorded.md     # 录制：真实模型返回的规范正文
evals/tasks/
  case-001.spec.md         # 输入：一份规范（三条需求）
  case-001.recorded.md     # 录制：真实模型返回的任务清单
evals/resume/
  case-001/                # 一个"做到一半、停了 7 天"的项目状态
    spec.md
    tasks.md
    sessions/2026-09-16-09-00-00.md
evals/explain/
  case-001.yaml            # 要检查的阶段 + 讲解里必须出现的几行
evals/report/
  case-001/                # 一个能触发多类风险的项目状态
    spec.md
    tasks.md
evals/skills/
  case-001.yaml            # 同一段意思的三种说法，都要认出同一个能力单元
evals/projects/
  case-001.yaml            # 两个项目 + 一条要跨项目共享的能力单元
evals/demo/
  case-001.yaml            # 未受训者要走的那几步，每步都得是真命令
evals/work/
  case-001.yaml            # 输入：一条任务（T001）与它的来源需求
  case-001.recorded.md     # 录制：真实模型产出的交付物正文
```

`evals/resume/` 不是模型录制，而是一份**固定的项目状态**：用来证明
"隔了一周回来还能接上"（SC-003）。它的价值在于每次都从同一个状态出发，
所以摘要退化了立刻能看出来。

回放它的是 `tests/test_evals.py`：把录制内容当成模型回复喂进去，断言产出的
规范满足 SC-001（一次会话内得到可评审规范，无需人工补结构）。
同一份文件里还有 `test_recorded_work_satisfies_sc014` 那条：把 `evals/work/` 的录制
喂给 work 阶段，断言产出落成证据、能追溯回任务与需求、不越权改状态（SC-014）。

## 怎么录一份新的

```powershell
$env:PM_AGENT_MODEL_API_KEY = "..."
$env:PM_AGENT_CA_BUNDLE = "C:\msys64\etc\pki\ca-trust\extracted\pem\tls-ca-bundle.pem"
# 用与 case-XXX.yaml 相同的输入跑一次，把 draft.text 写进 case-XXX.recorded.md
```

录制是**真实输出**，不是手写的理想答案——它的价值就在于"这是模型当时确实说出来的东西"。
如果换了模型或改了提示词，录制要重做；重做时顺便看一眼：新输出比旧的好了还是差了。

## 一条注意

录制文件用**字节写入**（LF），别用文本模式——Windows 上文本模式会把 `\n` 换成 `\r\n`，
而项目里所有文件的约定是 LF（见 `项目框架.md` 里 T008 那次教训）。
