---
name: verification-before-completion
description: Use when about to claim work is complete, fixed, or passing, before committing or creating PRs - requires running verification commands and confirming output before making any success claims; evidence before assertions always
when_to_use: 准备宣称"完成 / 修好了 / 通过了"之前，提交或建 PR 之前，把任务标完成之前，交给下一个人或别的 Agent 之前
when_not_to_use: 还在探索、东西没定型的时候——那时候该先说清"现在到哪、还没验什么"，不是拿这套规则把自己憋住不干活
inputs: 能证明这个说法的命令或动作；这一轮刚刚跑出来的完整输出（含退出码、失败数）；原本的需求或计划
outputs: 要么带证据的结论，要么如实说"现在的实际状态是什么、还没验的是什么"——两者都不许含糊
why: 最常见的失手不是做错，而是没验就说做完了：上次跑过算数、应该没问题算数、Agent 报成功也算数，最后都是别人替你还债。把"先说证据、再下结论"固定成铁律，就不依赖这次记不记得。
version: "1"
---

# Verification Before Completion

## Overview

**Core principle:** Evidence before claims, always.

**Violating the letter of this rule is violating the spirit of this rule.**

## The Iron Law

```
NO COMPLETION CLAIMS WITHOUT FRESH VERIFICATION EVIDENCE
```

If you haven't run the verification command in this message, you cannot claim it passes.

## The Gate Function

```
BEFORE claiming any status or expressing satisfaction:

1. IDENTIFY: What command proves this claim?
2. RUN: Execute the FULL command (fresh, complete)
3. READ: Full output, check exit code, count failures
4. VERIFY: Does output confirm the claim?
   - If NO: State actual status with evidence
   - If YES: State claim WITH evidence
5. ONLY THEN: Make the claim

Skip any step = lying, not verifying
```

## Common Failures

| Claim | Requires | Not Sufficient |
|-------|----------|----------------|
| Tests pass | Test command output: 0 failures | Previous run, "should pass" |
| Linter clean | Linter output: 0 errors | Partial check, extrapolation |
| Build succeeds | Build command: exit 0 | Linter passing, logs look good |
| Bug fixed | Test original symptom: passes | Code changed, assumed fixed |
| Regression test works | Red-green cycle verified | Test passes once |
| Agent completed | VCS diff shows changes | Agent reports "success" |
| Requirements met | Line-by-line checklist | Tests passing |

## Red Flags - STOP

- Using "should", "probably", "seems to"
- Expressing satisfaction before verification ("Great!", "Perfect!", "Done!", etc.)
- About to commit/push/PR without verification
- Trusting agent success reports
- Relying on partial verification
- Thinking "just this once"
- Tired and wanting work over
- **ANY wording implying success without having run verification**

## Rationalization Prevention

| Excuse | Reality |
|--------|---------|
| "Should work now" | RUN the verification |
| "I'm confident" | Confidence ≠ evidence |
| "Just this once" | No exceptions |
| "Linter passed" | Linter ≠ compiler |
| "Agent said success" | Verify independently |
| "I'm tired" | Exhaustion ≠ excuse |
| "Partial check is enough" | Partial proves nothing |
| "Different words so rule doesn't apply" | Spirit over letter |

## Key Patterns

**Tests:**
```
✅ [Run test command] [See: 34/34 pass] "All tests pass"
❌ "Should pass now" / "Looks correct"
```

**Regression tests (TDD Red-Green):**
```
✅ Write → Run (pass) → Revert fix → Run (MUST FAIL) → Restore → Run (pass)
❌ "I've written a regression test" (without red-green verification)
```

**Build:**
```
✅ [Run build] [See: exit 0] "Build passes"
❌ "Linter passed" (linter doesn't check compilation)
```

**Requirements:**
```
✅ Re-read plan → Create checklist → Verify each → Report gaps or completion
❌ "Tests pass, phase complete"
```

**Agent delegation:**
```
✅ Agent reports success → Check VCS diff → Verify changes → Report actual state
❌ Trust agent report
```

## When To Apply

**ALWAYS before:**
- ANY variation of success/completion claims
- ANY expression of satisfaction
- ANY positive statement about work state
- Committing, PR creation, task completion
- Moving to next task
- Delegating to agents

**Rule applies to:**
- Exact phrases
- Paraphrases and synonyms
- Implications of success
- ANY communication suggesting completion/correctness

---

## 来源与说明（本段是本项目加的，上游没有）

- **上游原文**：`obra/superpowers` 的 `skills/verification-before-completion/SKILL.md`
  （<https://github.com/obra/superpowers/blob/main/skills/verification-before-completion/SKILL.md>），
  许可证 **MIT，Copyright (c) 2025 Jesse Vincent**。
- **本项目的改动只有两处**：① 按本项目的能力单元格式补了 frontmatter 的五个字段
  （`when_to_use` / `when_not_to_use` / `inputs` / `outputs` / `why`，上游只有 `name` 与 `description`）；
  ② 在正文末尾加了这一段来源说明。**正文其余部分逐字保留上游原文**（2026-09-25 取自 `main` 分支）。
- **一句话中文导读**：没跑过的验证不算验证——先用一条命令证明它，再说它成了；说不出来就给"实际状态 + 还没验什么"。
  这张"声称 ↔ 需要什么证据 ↔ 什么不算数"的对照表是它最值钱的部分。
