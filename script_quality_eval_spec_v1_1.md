# 8–12 集悬疑精短剧剧本内容质量评估系统 Spec v1.1

## 0. 文档目的

本文档用于指导 Codex / 工程实现一个电视剧剧本内容质量评估系统。

系统目标是对 **8–12 集、单集 45–60 分钟左右的悬疑类精短剧剧本** 进行结构化内容评估，输出可解释的多维评分、低分问题诊断和修改建议。

本系统不定位为“绝对裁判”，而是定位为：

> 剧本内容质量辅助评估系统：用大模型完成结构化读稿、证据化评分、低分问题定位和修改优先级建议，供编剧、制片、平台内容评审或项目负责人复核。

---

## 1. 适用范围

### 1.1 适用对象

第一版只支持：

- 集数：8–12 集
- 单集时长：约 45–60 分钟
- 类型：悬疑 / 犯罪 / 社会派悬疑 / 家庭秘密 / 年代谜团等悬疑相关精短剧
- 输入材料优先级：
  1. 完整剧本
  2. 完整分集大纲 + 人物小传
  3. 故事梗概 + 分集梗概
  4. 仅故事梗概，低置信度评估

### 1.2 暂不支持

- 微短剧 / 竖屏短剧
- 30–40 集长剧
- 纯喜剧、纯偶像剧、纯生活流剧的专门评估
- 成片质量评估
- 演员、导演、摄影、美术、宣发判断
- 市场爆款预测

### 1.3 评估输出目标

系统最终输出：

1. 总分与等级
2. 七个维度分项分
3. 每个分项的证据依据
4. 低分项专项诊断
5. 主要问题 Top N
6. 分集 / 人物 / 线索 / 场景级问题定位
7. 可执行修改建议
8. 置信度与评估限制

---

## 2. 核心原则

### 2.1 不直接让模型凭感觉打分

禁止流程：

```text
原始剧本 → 大模型直接评分 → 报告
```

推荐流程：

```text
原始剧本
→ 剧本切分
→ 分集/场景/人物/信息/伏笔结构化抽取
→ 问题候选生成
→ 证据充分性检查
→ 规则判定
→ 分数映射
→ 低分诊断
→ 一致性校准
→ 最终报告
```

### 2.2 先抽事实，再做评价

所有评分节点只能读取前置抽取结果和证据索引，不允许脱离证据自由发挥。

### 2.3 低分必须具体诊断

凡是任一维度低于 6.0，必须输出低分诊断。低分诊断必须具体到：

- 集数
- 场景
- 人物
- 线索
- 结构节点
- 关系节点
- 伏笔/回收节点

禁止只输出：

- 人物不够立体
- 节奏偏慢
- 悬疑感不足
- 逻辑有问题
- 结尾仓促

除非继续说明具体问题位置、文本证据、影响和修改建议。

### 2.4 分数稳定性目标

目标：同一剧本、同一维度，两次评分偏差尽量不超过 1.0 分。

10 分制下，1.0 分相当于 10% 偏差。

实现方式：

- 低 temperature
- 结构化 JSON 输出
- 评分前事实抽取
- 统一评分锚点
- 硬性降分规则
- 双评审
- 差异超过 1.0 分时触发仲裁

---

## 3. 总体架构

采用 **DAG 工作流**，不是单条长链。

### 3.1 总流程

```text
Stage 0 输入与切分
  ↓
Stage 1 分集级事实抽取 Map
  ↓
Stage 2 全局事实汇总 Reduce
  ↓
Stage 3 问题候选生成
  ↓
Stage 4 七个维度并行评分
  ↓
Stage 5 低分诊断条件触发
  ↓
Stage 6 一致性校准 / 仲裁
  ↓
Stage 7 总分计算与最终报告
```

### 3.2 串联与并行规则

| 阶段 | 执行方式 | 原因 |
|---|---|---|
| 输入校验 → 剧本切分 | 串联 | 后续依赖统一 ID |
| 分集事实抽取 | 按集并行 | 每集可独立处理，降低 token 压力 |
| 单集抽取 → 全局汇总 | 串联 | 人物线、伏笔线、信息线需要跨集汇总 |
| 问题候选生成 | 串联 | 依赖全局事实底座 |
| 七维评分 | 并行 | 各维度读取同一事实底座 |
| 低分诊断 | 条件触发 | 依赖评分结果 |
| 一致性校准 | 串联 | 比较两轮评分差异 |
| 最终报告 | 串联 | 依赖全部结果 |

---

## 4. 推荐项目结构

```text
/script-quality-evaluator
  /input
    raw_script.md
    metadata.json

  /artifacts
    input_profile.json
    script_units.json

    /episode_map
      E01_structure.json
      E01_scene_functions.json
      E01_character_actions.json
      E01_information_release.json
      E01_setup_candidates.json
      ...

    episode_structure.json
    scene_functions.json
    character_chains.json
    information_release.json
    setup_payoff_map.json
    issue_candidates.json

    scores_round_a.json
    scores_round_b.json
    calibrated_scores.json
    low_score_diagnoses.json
    final_score.json
    final_report.md

  /prompts
    00_input_validation.md
    01_script_split.md
    02_episode_structure_extract.md
    03_scene_function_extract.md
    04_character_action_extract.md
    05_information_release_extract.md
    06_setup_candidate_extract.md
    07_global_reduce.md
    08_issue_candidates.md

    score_D1_suspense_information.md
    score_D2_character_chain.md
    score_D3_episode_structure.md
    score_D4_logic.md
    score_D5_scene_density.md
    score_D6_theme.md
    score_D7_ending.md

    low_score_diagnosis.md
    score_calibration.md
    final_report.md

  /src
    pipeline.py
    llm_client.py
    schemas.py
    scoring.py
    report.py
```

---

## 5. Artifact 数据流

```text
raw_script.md
→ input_profile.json
→ script_units.json
→ episode_map/*.json
→ episode_structure.json
→ scene_functions.json
→ character_chains.json
→ information_release.json
→ setup_payoff_map.json
→ issue_candidates.json
→ scores_round_a.json
→ scores_round_b.json
→ calibrated_scores.json
→ low_score_diagnoses.json
→ final_score.json
→ final_report.md
```

---

## 6. Stage 0：输入校验与剧本切分

### Node 0：输入校验

#### 目标

确认输入材料是否足够进行评估，明确可评范围和不可评范围。

#### 输入

- raw_script.md
- metadata.json，可选

#### 输出：input_profile.json

```json
{
  "project_name": "",
  "episode_count": 10,
  "episode_duration": "45-60min",
  "material_type": "完整剧本 / 分集大纲 / 梗概 / 混合材料",
  "genre_claimed": "悬疑",
  "is_complete": true,
  "can_evaluate": [],
  "cannot_evaluate": [],
  "risk_notes": [],
  "confidence_level": "高 / 中 / 低"
}
```

#### Prompt 要点

```text
你是电视剧剧本评估系统的输入校验节点。
请只判断输入材料的类型、完整度、可评估范围和不可评估范围。
不要评价剧本质量，不要打分，不要提出修改建议。

请输出 JSON。
如果材料不足，请明确说明哪些评价不能进行。
```

---

### Node 1：剧本切分

#### 目标

把剧本拆成统一结构单位：集、场、事件。

#### 输出：script_units.json

```json
{
  "episodes": [
    {
      "episode_id": "E01",
      "scenes": [
        {
          "scene_id": "E01-S01",
          "location": "",
          "time": "",
          "characters": [],
          "surface_event": "",
          "state_change": "",
          "source_excerpt": ""
        }
      ]
    }
  ]
}
```

#### 规则

- scene_id 必须使用 `E01-S01` 格式
- 如果原文已有场号，保留原场号并映射到系统 scene_id
- source_excerpt 保留短证据片段，不要存整段长文本
- 不做质量评价

---

## 7. Stage 1：分集级事实抽取 Map

对每一集并行执行以下抽取节点。

### Node 2A：本集结构抽取

#### 输出

```json
{
  "episode_id": "E01",
  "opening_state": "",
  "ending_state": "",
  "core_event": "",
  "mainline_progress": "",
  "new_information": [],
  "new_question_or_hook": "",
  "episode_function": "启动 / 推进 / 反转 / 沉淀 / 回收 / 过渡 / 功能不明"
}
```

---

### Node 2B：本集场景功能抽取

#### 功能标签

| 标签 | 含义 |
|---|---|
| PLOT | 推进情节 |
| CHARACTER | 揭示人物 |
| CONFLICT | 制造、升级、转移或解决冲突 |
| CLUE | 埋设线索 |
| PAYOFF | 回收伏笔 |
| EMOTION | 情绪累积或释放 |
| WORLD | 建立环境、时代、行业、地域背景 |
| THEME | 承载主题表达 |
| TRANSITION | 过渡连接 |
| UNKNOWN | 功能不明 |

#### 输出

```json
{
  "episode_id": "E01",
  "scene_functions": [
    {
      "scene_id": "E01-S01",
      "function_tags": ["PLOT", "CLUE"],
      "information_change": "",
      "relationship_change": "",
      "conflict_change": "",
      "emotion_or_theme_function": "",
      "suspected_functionless": false,
      "evidence": ""
    }
  ]
}
```

---

### Node 2C：本集人物行动抽取

#### 输出

```json
{
  "episode_id": "E01",
  "character_actions": [
    {
      "character_name": "",
      "scene_id": "E01-S03",
      "action": "",
      "motivation_evidence": "",
      "consequence": "",
      "cost_or_risk": "",
      "change_after_action": "",
      "relationship_impact": ""
    }
  ]
}
```

---

### Node 2D：本集信息释放抽取

#### 输出

```json
{
  "episode_id": "E01",
  "information_release": [
    {
      "info_id": "I-E01-001",
      "scene_id": "E01-S05",
      "information": "",
      "info_type": "线索 / 真相 / 误导 / 背景 / 动机 / 关系 / 证据",
      "audience_knows": true,
      "protagonist_knows": true,
      "other_characters_who_know": [],
      "characters_who_do_not_know": [],
      "changes_understanding": "",
      "leads_to_action": "",
      "later_used_at": []
    }
  ]
}
```

---

### Node 2E：本集伏笔/线索候选抽取

#### 输出

```json
{
  "episode_id": "E01",
  "setup_candidates": [
    {
      "candidate_id": "F-E01-001",
      "scene_id": "E01-S04",
      "setup_content": "",
      "surface_meaning_at_first": "",
      "possible_future_function": "案件 / 人物 / 关系 / 主题 / 反转 / 未知",
      "evidence": ""
    }
  ]
}
```

---

## 8. Stage 2：全局事实汇总 Reduce

### Node 3A：全剧分集结构汇总

#### 输出：episode_structure.json

```json
{
  "main_story_goal": "",
  "episodes": [
    {
      "episode_id": "E01",
      "opening_state": "",
      "ending_state": "",
      "core_event": "",
      "mainline_progress": "",
      "new_information": [],
      "new_question_or_hook": "",
      "episode_function": ""
    }
  ],
  "unclosed_mainline_questions": []
}
```

---

### Node 3B：全剧场景功能汇总

#### 输出：scene_functions.json

```json
{
  "scene_functions": [
    {
      "scene_id": "E01-S01",
      "episode_id": "E01",
      "function_tags": [],
      "information_change": "",
      "relationship_change": "",
      "conflict_change": "",
      "emotion_or_theme_function": "",
      "suspected_functionless": false,
      "evidence": ""
    }
  ],
  "statistics": {
    "total_scene_count": 0,
    "functionless_scene_count": 0,
    "functionless_ratio": 0,
    "per_episode_functionless_ratio": {}
  }
}
```

---

### Node 3C：全剧人物行动链汇总

#### 输出：character_chains.json

```json
{
  "characters": [
    {
      "character_name": "",
      "role_type": "主角 / 重要配角 / 对抗人物 / 受害者 / 证人 / 其他",
      "initial_state": "",
      "explicit_goal": "",
      "implicit_need_with_evidence": "",
      "action_chain": [
        {
          "episode_id": "E01",
          "scene_id": "E01-S03",
          "action": "",
          "motivation_evidence": "",
          "consequence": "",
          "cost_or_risk": "",
          "change_after_action": ""
        }
      ],
      "relationship_changes": [],
      "final_state": "",
      "suspected_motivation_gaps": []
    }
  ]
}
```

---

### Node 3D：全剧信息释放表汇总

#### 输出：information_release.json

```json
{
  "information_release": [
    {
      "info_id": "I001",
      "episode_id": "E01",
      "scene_id": "E01-S05",
      "information": "",
      "info_type": "",
      "audience_knows": true,
      "protagonist_knows": true,
      "other_characters_who_know": [],
      "characters_who_do_not_know": [],
      "changes_understanding": "",
      "leads_to_action": "",
      "later_used_at": []
    }
  ],
  "knowledge_state_summary": {
    "audience_knows_by_episode": {},
    "protagonist_knows_by_episode": {},
    "key_information_gaps": []
  }
}
```

---

### Node 3E：全剧伏笔回收表汇总

#### 输出：setup_payoff_map.json

```json
{
  "setup_payoff_map": [
    {
      "item_id": "F001",
      "setup_content": "",
      "first_appearance": "E01-S04",
      "surface_meaning_at_first": "",
      "reappearances": [],
      "payoff_position": "",
      "payoff_meaning": "",
      "payoff_type": "情节回收 / 人物回收 / 情感回收 / 主题回收 / 反转回收",
      "status": "已回收 / 未发现回收 / 疑似后置硬解释",
      "evidence": ""
    }
  ]
}
```

---

## 9. Stage 3：问题候选生成

### Node 4：问题候选生成

#### 输出：issue_candidates.json

```json
{
  "issue_candidates": [
    {
      "issue_id": "Q001",
      "issue_type": "",
      "related_positions": [],
      "related_characters": [],
      "related_clues": [],
      "trigger_evidence": "",
      "needs_review": ""
    }
  ]
}
```

### 候选问题类型

| 类型 | 触发条件 |
|---|---|
| 主线推进不明显 | 某集未发现明显主线状态变化 |
| 场景功能不明 | 场景没有明确叙事功能 |
| 场景功能重复 | 多场戏释放同一信息，且无新变化 |
| 人物动机断裂 | 关键行动缺少前置目标、压力、利益或情感依据 |
| 人物行动无后果 | 行动没有改变局面、关系或风险 |
| 冲突悬置 | 冲突启动后没有升级、转移、解决或悬置说明 |
| 信息释放突兀 | 关键真相后段首次出现，缺少前置线索 |
| 伏笔未回收 | 重要信息或物件前文出现，后文未使用 |
| 后置硬解释 | 结尾用新信息解决核心问题 |
| 单集钩子不足 | 本集结尾无新风险、新问题、新选择 |
| 支线悬空 | 支线不影响主线、人物或主题 |
| 主题直给 | 主题主要通过台词说明，缺少戏剧行动支撑 |
| 结尾仓促 | 后段集中解释、人物/关系/主题回收不足 |

---

## 10. Stage 4：七维并行评分

### 10.1 评分维度与整数权重

| 维度 | 权重 |
|---|---:|
| D1 悬疑信息控制 | 20 |
| D2 人物行动链 | 20 |
| D3 分集结构与节奏推进 | 20 |
| D4 情节因果与逻辑可信度 | 15 |
| D5 场景戏剧张力与有效密度 | 10 |
| D6 主题表达与现实质感 | 10 |
| D7 结尾回收与整体完成度 | 5 |
| **合计** | **100** |

### 10.2 总分公式

```text
total_score =
D1 * 0.20 +
D2 * 0.20 +
D3 * 0.20 +
D4 * 0.15 +
D5 * 0.10 +
D6 * 0.10 +
D7 * 0.05
```

### 10.3 权重解释

- D1/D2/D3 各 20：悬疑精短剧的基本盘，决定观众是否追、角色是否成立、故事是否持续推进。
- D4 15：逻辑可信是类型成立的硬约束，略低于前三项，避免与 D1/D3 重复扣分。
- D5/D6 各 10：分别衡量场景执行密度和内容厚度。
- D7 5：结尾回收很重要，但 D1/D3/D4 已经覆盖大量结尾相关问题，因此用低权重 + 硬门槛规则处理，避免重复扣分。

---

## 11. 通用评分节点协议

每个维度评分节点必须执行四步：

```text
1. 证据充分性检查
2. 规则判定 Checklist
3. 硬性降分规则
4. 分数映射
5. 如 score < 6.0，输出低分诊断
```

### 11.1 通用输出 Schema

```json
{
  "dimension": "",
  "weight": 0,
  "evidence_sufficiency": {
    "status": "充分 / 部分充分 / 不充分",
    "reason": "",
    "missing_evidence": [],
    "max_score_allowed": 10
  },
  "checks": [
    {
      "check_id": "",
      "check_name": "",
      "result": "成立 / 部分成立 / 不成立 / 证据不足",
      "evidence": [],
      "issue": ""
    }
  ],
  "triggered_score_caps": [
    {
      "rule": "",
      "cap": 0,
      "reason": ""
    }
  ],
  "score": 0,
  "score_band": "",
  "score_reason": "",
  "positive_evidence": [],
  "negative_evidence": [],
  "low_score_diagnosis": null
}
```

### 11.2 通用分数区间

| 分数 | 含义 |
|---|---|
| 9.0–10.0 | 高度成熟，问题轻微，不影响整体成立 |
| 8.0–8.9 | 整体成熟，存在局部可优化问题 |
| 7.0–7.9 | 整体成立，但有明确修改空间 |
| 6.0–6.9 | 基本可读，但存在明显短板 |
| 5.0–5.9 | 机制不稳，需要重点修改 |
| 4.0–4.9 | 关键机制失效，需要大修 |
| 3.0–3.9 | 大面积失效，需要重构 |
| 0–2.9 | 当前维度基本不成立 |

---

## 12. 七个维度的评分协议摘要

完整 prompt 应分别放入 `/prompts/score_D*.md`。此处给出工程实现所需核心规则。

---

### D1 悬疑信息控制，权重 20

#### 评审目标

判断剧本是否以公平、递进、可回溯的方式控制悬疑信息。

#### Checklist

| ID | 检查项 |
|---|---|
| S1 | 核心谜题是否清晰启动 |
| S2 | 信息释放是否具有递进性 |
| S3 | 关键真相是否有前置线索 |
| S4 | 误导是否公平 |
| S5 | 观众与主角的信息差是否被有效利用 |
| S6 | 反转是否改变理解，而不只是改变结果 |
| S7 | 真相揭示是否由人物行动推动 |
| S8 | 悬疑线是否完成回收 |

#### 硬性降分规则

| 触发条件 | 最高分 |
|---|---:|
| 核心谜题不清晰启动 | 6.5 |
| 关键真相无前置线索 | 5.5 |
| 结尾主要靠新人物/新证据解释 | 5.0 |
| 反转只改变结果，不重组前文理解 | 7.0 |
| 连续两集无有效信息增量 | 7.0 |
| 观众/主角信息状态混乱，导致理解困难 | 6.5 |
| 核心谜题未完成回收 | 5.0 |
| 材料证据不充分 | 按 evidence_sufficiency.max_score_allowed |

---

### D2 人物行动链，权重 20

#### 评审目标

判断主要人物是否具备可追踪的“初始处境—外部目标—行动选择—后果代价—关系变化—认知变化—结尾状态”链条。

#### Checklist

| ID | 检查项 |
|---|---|
| C1 | 主要人物是否有清晰初始处境 |
| C2 | 主要人物是否有可追踪的外部目标 |
| C3 | 关键行动是否由人物主动选择触发 |
| C4 | 关键行动是否有前置动机依据 |
| C5 | 人物行动是否造成后果和代价 |
| C6 | 人物关系是否随行动发生变化 |
| C7 | 人物是否有认知或价值变化 |
| C8 | 人物功能是否服务主题和类型，而不只是服务情节 |

#### 硬性降分规则

| 触发条件 | 最高分 |
|---|---:|
| 主角没有可追踪外部目标 | 5.0 |
| 主角关键行动主要由外部事件推着走 | 6.0 |
| 2 个以上关键行动无前置动机依据 | 5.5 |
| 多数关键行动没有后果或代价 | 6.0 |
| 主要人物结尾状态与初始状态无明显差异 | 6.0 |
| 关键人物普遍工具化 | 7.0 |
| 主角工具化 | 5.0 |
| 没有完整结尾 | 6.5 |
| 材料证据不充分 | 按 evidence_sufficiency.max_score_allowed |

---

### D3 分集结构与节奏推进，权重 20

#### 评审目标

判断剧本是否在 8–12 集有限体量中合理分配启动、展开、升级、反转、回收等叙事任务，并保证每一集都对主线、人物关系、信息释放或主题表达产生有效推进。

#### Checklist

| ID | 检查项 |
|---|---|
| E1 | 前 1–2 集是否有效启动主线 |
| E2 | 每集是否有明确结构任务 |
| E3 | 每集结尾是否形成追看动力 |
| E4 | 中段是否有升级、转向或反转 |
| E5 | 主线推进是否连续，避免空转 |
| E6 | 节奏分配是否符合 8–12 集有限体量 |
| E7 | 场景密度是否支撑单集节奏 |
| E8 | 结尾是否完成结构回收，且不仓促 |

#### 硬性降分规则

| 触发条件 | 最高分 |
|---|---:|
| 前 2 集未清晰启动主线 | 6.5 |
| 超过 2 集结构功能不明 | 6.0 |
| 连续两集没有有效结尾钩子 | 7.0 |
| E04–E07 连续缺少结构升级 | 6.0 |
| 连续两集开头/结尾状态基本一致 | 6.5 |
| 某一集超过 30% 场景功能不明 | 6.0 |
| 结尾主要靠集中口述解释完成 | 6.0 |
| 核心主线未回收 | 5.0 |
| 材料证据不充分 | 按 evidence_sufficiency.max_score_allowed |

---

### D4 情节因果与逻辑可信度，权重 15

#### 评审目标

判断关键事件、人物行为、线索发现、危机升级、反转揭示是否由清晰因果推动，而不是依赖巧合、降智、后置补丁或编剧强行安排。

#### Checklist

| ID | 检查项 |
|---|---|
| L1 | 主线事件是否有清晰因果链 |
| L2 | 关键转折是否有前置条件 |
| L3 | 人物行为是否符合其信息状态 |
| L4 | 人物是否存在明显降智 |
| L5 | 巧合是否被控制在合理范围内 |
| L6 | 设定规则是否前后一致 |
| L7 | 反转是否改变因果理解 |
| L8 | 逻辑漏洞是否影响核心主线 |

#### 硬性降分规则

| 触发条件 | 最高分 |
|---|---:|
| 核心真相依赖后置补丁解释 | 5.0 |
| 主线关键节点主要靠巧合推动 | 5.5 |
| 主角多次明显降智 | 5.5 |
| 人物行为与其已知信息明显矛盾 | 6.0 |
| 关键反转缺少前置条件 | 5.5 |
| 时间线/空间线存在核心矛盾 | 5.0 |
| 职业流程或技术设定严重失真，且影响主线 | 6.0 |
| 材料证据不充分 | 按 evidence_sufficiency.max_score_allowed |

---

### D5 场景戏剧张力与有效密度，权重 10

#### 评审目标

判断场景是否具备明确叙事功能、内部变化、冲突张力、信息增量、人物关系推进或情绪/主题承载。

#### Checklist

| ID | 检查项 |
|---|---|
| SCE1 | 场景是否有明确叙事功能 |
| SCE2 | 场景内部是否发生变化 |
| SCE3 | 冲突是否具体 |
| SCE4 | 说明性场景是否被戏剧化 |
| SCE5 | 重复场景是否被控制 |
| SCE6 | 关键场景是否承担足够重量 |
| SCE7 | 情绪场景是否有推进功能 |
| SCE8 | 单集场景组合是否有节奏变化 |

#### 硬性降分规则

| 触发条件 | 最高分 |
|---|---:|
| 多个关键场景只有信息交代，没有行动或冲突承载 | 6.0 |
| 某一集超过 30% 场景功能不明 | 6.0 |
| 多场戏重复释放同一信息，且无新变化 | 6.5 |
| 关键转折场景缺少铺垫和后果 | 6.0 |
| 主要人物大量场景没有目标 | 5.5 |
| 场景普遍只有对白解释，没有局面变化 | 5.5 |
| 材料证据不充分 | 按 evidence_sufficiency.max_score_allowed |

---

### D6 主题表达与现实质感，权重 10

#### 评审目标

判断剧本是否在悬疑类型叙事之外，形成可信的主题表达、人物处境、情绪厚度和现实质感。

#### Checklist

| ID | 检查项 |
|---|---|
| T1 | 主题命题是否清晰 |
| T2 | 主题是否由情节承载 |
| T3 | 主题是否由人物承载 |
| T4 | 现实细节是否可信 |
| T5 | 议题表达是否克制 |
| T6 | 类型与主题是否融合 |
| T7 | 情绪表达是否有积累 |
| T8 | 价值表达是否复杂 |

#### 硬性降分规则

| 触发条件 | 最高分 |
|---|---:|
| 主题主要靠台词口号表达 | 6.0 |
| 案件/悬疑线与主题线明显脱节 | 6.5 |
| 人物命运无法承载主题 | 6.0 |
| 现实背景只是装饰，不影响人物行动 | 6.5 |
| 职业/地域/年代细节严重空泛 | 6.0 |
| 议题表达明显标签化或单薄化 | 6.0 |
| 材料证据不充分 | 按 evidence_sufficiency.max_score_allowed |

---

### D7 结尾回收与整体完成度，权重 5

#### 评审目标

判断剧本作为 8–12 集有限剧，是否完成它承诺的核心故事；结尾是否完成主线、悬疑、人物、关系、情绪和主题的综合回收；开放性是否可控。

#### Checklist

| ID | 检查项 |
|---|---|
| END1 | 核心主线是否闭合 |
| END2 | 关键悬疑问题是否回收 |
| END3 | 主要人物是否完成结尾状态 |
| END4 | 关系线是否有结果 |
| END5 | 情绪是否完成释放 |
| END6 | 主题是否形成落点 |
| END7 | 结尾是否避免仓促解释 |
| END8 | 开放性是否可控 |

#### 硬性降分规则

| 触发条件 | 最高分 |
|---|---:|
| 核心主线未闭合 | 5.0 |
| 关键真相未解释 | 5.0 |
| 结尾主要靠集中口述解释 | 6.0 |
| 主要人物没有结尾选择或状态变化 | 6.0 |
| 多条重要支线悬空 | 6.0 |
| 主题没有结尾落点 | 7.0 |
| 情绪回收明显缺失 | 7.0 |
| 开放结尾影响核心理解 | 5.5 |
| 缺少完整结尾材料 | 6.0 |

---

## 13. 总分门槛规则

整数权重用于总分计算，但必须配合门槛规则，避免核心问题被平均分掩盖。

### 13.1 核心维度门槛

```text
如果 D1/D2/D3/D4 任一项 < 5.0：
  - 总等级最高不得超过 C
  - 必须标记“核心机制风险”
  - 最终报告必须优先诊断该项
```

### 13.2 结尾门槛

```text
如果 D7 < 6.0：
  - 必须标记“结尾完成度风险”

如果 D7 < 5.0：
  - 总等级最高不得超过 C
```

### 13.3 结构性硬伤门槛

```text
如果任一维度 < 4.0：
  - 必须进入结构性硬伤诊断
  - 最终报告必须给出“大修优先级”
```

### 13.4 总分低分门槛

```text
如果 total_score < 70：
  - 最终报告必须输出 Top 5 问题

如果 total_score < 60：
  - 最终报告必须输出：
    1. 是否建议继续开发
    2. 是否建议大修
    3. 最优先修改的三处
```

---

## 14. Stage 5：低分诊断

### 14.1 触发条件

```text
if dimension.score < 6.0:
    run low_score_diagnosis
```

### 14.2 输出 Schema

```json
{
  "low_score_diagnoses": [
    {
      "dimension": "",
      "score": 0,
      "severity": "中等问题 / 严重问题 / 结构性硬伤",
      "core_problem": "",
      "specific_positions": [],
      "evidence": [],
      "impact": "",
      "revision_suggestions": []
    }
  ]
}
```

### 14.3 严重程度规则

| 分数 | 严重程度 |
|---|---|
| 5.0–5.9 | 中等问题 |
| 4.0–4.9 | 严重问题 |
| 0–3.9 | 结构性硬伤 |

### 14.4 合格标准

低分诊断必须同时满足：

1. 指出低分项名称和分数
2. 说明核心问题
3. 定位到具体集数、场景、人物、线索、结构节点或关系节点
4. 引用前置抽取结果作为证据
5. 说明影响：追看动力、人物可信度、悬疑公平感、逻辑可信度、结构闭合、情绪完成、现实质感或开发确定性
6. 给出可执行修改建议

---

## 15. Stage 6：双评审一致性校准

### 15.1 推荐机制

```text
Score Round A
Score Round B
↓
Compare
↓
if abs(score_a - score_b) > 1.0:
    run arbitration
else:
    use average or score_a
```

### 15.2 仲裁规则

仲裁不得简单取平均。必须：

1. 回到前置抽取证据
2. 比较两轮评分引用的证据是否充分
3. 检查是否触发硬性降分规则
4. 根据评分锚点给出仲裁分数

### 15.3 输出 Schema

```json
{
  "calibrated_scores": [
    {
      "dimension": "",
      "score_a": 0,
      "score_b": 0,
      "difference": 0,
      "status": "通过 / 需仲裁",
      "final_score": 0,
      "arbitration_reason": ""
    }
  ]
}
```

---

## 16. Stage 7：总分与最终报告

### 16.1 总分等级

| 总分 | 等级 | 解释 |
|---|---|---|
| 85–100 | A | 成熟度高，具备较强开发价值 |
| 75–84 | B | 整体成立，有明确修改空间 |
| 65–74 | C | 基本可读，但存在明显结构/人物/类型问题 |
| 55–64 | D | 需要大修，当前开发风险较高 |
| 0–54 | E | 核心机制不成立，暂不建议继续开发 |

最终等级还必须受门槛规则约束。

### 16.2 final_score.json

```json
{
  "total_score": 0,
  "raw_grade": "",
  "final_grade": "",
  "dimension_scores": [
    {
      "dimension": "",
      "weight": 0,
      "score": 0,
      "weighted_score": 0
    }
  ],
  "risk_flags": [],
  "top_issues": []
}
```

### 16.3 final_report.md 结构

```text
# 电视剧剧本内容质量评估报告

## 一、项目基础信息
## 二、评估材料说明
## 三、总分与等级
## 四、分项评分概览
## 五、核心优点
## 六、主要问题 Top 5
## 七、低分项专项诊断
## 八、分集问题定位
## 九、人物问题定位
## 十、悬疑机制问题定位
## 十一、逻辑与因果问题定位
## 十二、修改优先级
## 十三、开发建议
## 十四、置信度与评估限制
```

---

## 17. MVP 分期

### Phase 1：核心 MVP

实现：

```text
Node 0 输入校验
Node 1 剧本切分
Node 2A 分集结构抽取
Node 2C 人物行动抽取
Node 2D 信息释放抽取
Node 2E 伏笔候选抽取
Node 3 Reduce
Node 4 问题候选生成
D1/D2/D3/D4 四个核心维度评分
低分诊断
总分计算
最终报告
```

暂不实现：

- D5 场景密度
- D6 主题表达
- D7 结尾完成度
- 双评审仲裁
- benchmark 校准

### Phase 2：完整七维评分

补全：

- D5 场景戏剧张力与有效密度
- D6 主题表达与现实质感
- D7 结尾回收与整体完成度
- 总分门槛规则

### Phase 3：稳定性增强

补全：

- 双评审
- 仲裁节点
- benchmark 样本校准
- 评分差异统计
- prompt/rubric 迭代工具

---

## 18. 工程验收标准

### 18.1 功能验收

必须满足：

1. 能读取一份 8–12 集剧本或分集大纲
2. 能生成 `script_units.json`
3. 能生成全剧事实底座：
   - episode_structure.json
   - character_chains.json
   - information_release.json
   - setup_payoff_map.json
   - issue_candidates.json
4. 能输出至少 D1/D2/D3/D4 四个评分
5. 任一评分低于 6.0 时，必须输出低分诊断
6. 最终报告必须包含分数、证据、问题、修改建议

### 18.2 低分诊断验收

对于任一低分项，必须能回答：

- 哪个维度低
- 为什么低
- 哪几集/哪几场出问题
- 证据来自哪里
- 影响了什么
- 怎么改

如果低分诊断只出现“加强、优化、丰富、深化”等抽象词，无具体动作，判定失败。

### 18.3 稳定性验收

使用同一输入运行两次：

- 单维度评分差异应尽量 ≤ 1.0
- 若 > 1.0，必须触发仲裁
- 仲裁必须输出理由，不得简单取平均

### 18.4 JSON 验收

所有节点输出必须是可 parse 的 JSON。

失败时必须输出：

```json
{
  "error": true,
  "node": "",
  "reason": "",
  "retry_suggestion": ""
}
```

---

## 19. LLM 调用建议

### 19.1 参数

推荐：

```json
{
  "temperature": 0,
  "top_p": 0.1,
  "response_format": "json_object"
}
```

### 19.2 分块策略

- 完整剧本过长时，按集分块
- 单集过长时，按场景块分割
- 每个分块都保留 episode_id 和 scene_id
- Reduce 阶段只汇总结构化结果，避免重新吞完整剧本

### 19.3 重试策略

如果输出 JSON 解析失败：

1. 原 prompt 不变
2. 附加“请修复为合法 JSON，不要改变内容”
3. 最多重试 2 次
4. 仍失败则返回 error artifact

---

## 20. 最终交付物

工程完成后，系统应能输出：

```text
/artifacts
  input_profile.json
  script_units.json
  episode_structure.json
  scene_functions.json
  character_chains.json
  information_release.json
  setup_payoff_map.json
  issue_candidates.json
  scores_round_a.json
  calibrated_scores.json
  low_score_diagnoses.json
  final_score.json
  final_report.md
```

核心交付是：

1. `final_report.md`
2. `final_score.json`
3. `low_score_diagnoses.json`
4. 全部中间事实 artifact，用于人工复核

---

## 21. 当前版本说明

版本：v1.1

相比 v1.0 的关键变化：

1. 权重改为整数百分比：
   - D1/D2/D3：20/20/20
   - D4：15
   - D5/D6：10/10
   - D7：5
2. 增加结尾门槛规则，避免 D7 权重低导致结尾风险被低估
3. 明确核心维度 D1/D2/D3/D4 任一低于 5.0 时，总等级最高 C
4. 强化低分诊断合格标准
5. 明确 DAG workflow：前处理串联、分集抽取并行、七维评分并行、诊断和报告串联
