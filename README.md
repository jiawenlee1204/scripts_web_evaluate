# 剧本内容质量评估工具

## 核心价值

这个工具用于评估 8-12 集悬疑精短剧剧本。它不是让模型直接凭感觉打分，而是先把剧本拆成集、场、人物行动、信息释放、伏笔线索和问题候选，再进入七维评分和最终报告。

核心产物是 `final_report.md`。其他 JSON 文件主要用于监督模型每一步有没有跑偏。

评分口径：七个维度内部采用 0-5 分制，低于 3.0 触发低分诊断；总分仍按权重换算为 100 分制，便于判断等级和开发优先级。

## 输出结构

每篇剧本会生成一个独立文件夹，默认按输入文件名命名：

```text
output/
  wuxian_episode_script/
    final_report.md
    final_score.json
    low_score_diagnoses.json
    progress/
      run_manifest.json
      checkpoints/
      episode_map/
      ...
```

## 使用方法

默认剧本是 `input/wuxian_episode_script.md`。下面这段可以一次性复制运行：

```bash
# 进入项目目录
cd /Users/bytedance/Documents/剧本评测

# 设置 DeepSeek API key
export DEEPSEEK_API_KEY="你的 DeepSeek API key"

# 设置便宜模型：用于输入校验、剧本切分、事实抽取、问题候选
export SCRIPT_EVAL_MODEL="deepseek-v4-flash"

# 设置 DeepSeek API 地址
export SCRIPT_EVAL_BASE_URL="https://api.deepseek.com"

# 设置评审模型：用于七维评分、分数校准、低分诊断、最终报告
export SCRIPT_EVAL_JUDGE_MODEL="deepseek-v4-pro"

# 运行默认剧本，结果写入 output/wuxian_episode_script/
PYTHONPATH=src python3 -m script_quality_evaluator
```

中断后继续跑：

```bash
# 复用 output/wuxian_episode_script/progress/checkpoints/ 下已完成的节点
PYTHONPATH=src python3 -m script_quality_evaluator --resume
```

如果继续跑另一篇剧本，必须带同一个 `--input`：

```bash
# 复用 output/lixian_zhengren_episode_script/progress/checkpoints/ 下已完成的节点
PYTHONPATH=src python3 -m script_quality_evaluator --input input/lixian_zhengren_episode_script.md --resume
```

复用抽取结果，但用更强模型重新评分：

```bash
# 不重跑切分和事实抽取，只重跑评分、校准、诊断和最终报告
PYTHONPATH=src python3 -m script_quality_evaluator --resume --rerun-judging --judge-model deepseek-v4-pro
```

## 特殊情况

评估另一篇剧本：

```bash
# 输入另一篇剧本，结果写入 output/lixian_zhengren_episode_script/
PYTHONPATH=src python3 -m script_quality_evaluator --input input/lixian_zhengren_episode_script.md
```

同一篇剧本想单独保存一个版本：

```bash
# 手动指定本次评估文件夹名，结果写入 output/wuxian_v2_strict/
PYTHONPATH=src python3 -m script_quality_evaluator --input input/wuxian_episode_script.md --run-name wuxian_v2_strict
```

离线规则模式：

```bash
# 不调用模型，只跑本地规则链路，用于检查程序是否能跑通
PYTHONPATH=src python3 -m script_quality_evaluator --mode rules
```
