# 电视剧剧本质量评测系统 Web 版

Web 版提供一个可分享的上传评测页面。用户上传 `.md` 或 `.txt` 剧本后，可以实时查看评测进度、过程产物和最终 `final_report.md`，并下载最终报告或完整结果包。

Web 版固定使用 LLM 评测链路，不在页面提供其他模式选择。原有 CLI 用法保留不变。

## 本地启动

```bash
cd /Users/bytedance/Documents/剧本评测
python3 -m pip install -r requirements.txt
streamlit run app.py
```

打开终端中显示的本地地址后，上传剧本并点击“开始评测”。

## API 配置

页面“高级配置”中的输入优先级最高。留空时会读取部署环境变量；环境变量也没有时使用代码默认模型和默认 Base URL。

常用环境变量：

```bash
export SCRIPT_EVAL_API_KEY="你的 API key"
export SCRIPT_EVAL_BASE_URL="https://api.deepseek.com"
export SCRIPT_EVAL_MODEL="deepseek-v4-flash"
export SCRIPT_EVAL_JUDGE_MODEL="deepseek-v4-pro"
```

兼容变量：

- `DEEPSEEK_API_KEY`
- `OPENAI_API_KEY`
- `API_KEY`
- `BASE_URL`
- `MAIN_MODEL`
- `JUDGE_MODEL`

如果页面和部署环境都没有 API Key，Web 页面会提示补充配置，不会切换到其他评测模式。

## Streamlit Cloud 部署

1. 将项目推送到 GitHub。
2. 在 Streamlit Cloud 新建 App，入口文件填写 `app.py`。
3. 在 App 的 Secrets 中填写：

```toml
API_KEY = ""
BASE_URL = "https://api.deepseek.com"
MAIN_MODEL = "deepseek-v4-flash"
JUDGE_MODEL = "deepseek-v4-pro"
```

4. 部署完成后，把 Streamlit Cloud 生成的链接分享给使用者。

安全提醒：如果在部署环境中配置了默认 API Key，所有访问该 Web App 的评测都会消耗部署者的 API 额度。也可以不配置默认 Key，让使用者在页面中自行填写。

## Hugging Face Spaces 部署

1. 新建 Space，类型选择 Streamlit。
2. 上传项目代码，确保包含 `app.py`、`requirements.txt` 和 `src/`。
3. 在 Space 的 Settings → Secrets 中配置：

```text
SCRIPT_EVAL_API_KEY=你的 API key
SCRIPT_EVAL_BASE_URL=https://api.deepseek.com
SCRIPT_EVAL_MODEL=deepseek-v4-flash
SCRIPT_EVAL_JUDGE_MODEL=deepseek-v4-pro
```

4. Space 构建完成后即可获得可分享链接。

## 输出与下载

每次 Web 评测都会创建独立目录：

```text
output/{run_name}/
```

如果同名目录已存在，系统会自动追加时间戳和短 ID，避免覆盖历史结果。临时上传文件会保存到 `tmp_uploads/`，不会放入下载结果包。

结果包包含 pipeline 正常生成的文件，例如：

- `final_report.md`
- `final_score.json`
- `low_score_diagnoses.json`
- `progress/checkpoints/*`
- 其他过程文件

API Key 不会写入报告、checkpoint 或下载结果包。

## 最小测试流程

1. 启动：`streamlit run app.py`
2. 上传 `input/wuxian_episode_script.md`
3. 在“高级配置”填写 API Key，或提前配置环境变量。
4. 点击“开始评测”。
5. 观察“当前进度”和“过程产物”区域。
6. 运行结束后查看“最终报告”，下载 `final_report.md` 或完整结果包。

## CLI 仍可使用

原有命令保持可用：

```bash
PYTHONPATH=src python3 -m script_quality_evaluator --input input/wuxian_episode_script.md
```

CLI 仍支持原来的参数和环境变量读取方式。
