from __future__ import annotations

import io
import json
import os
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

import streamlit as st


ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from script_quality_evaluator.config import RuntimeConfig
from script_quality_evaluator.pipeline import run_pipeline, safe_run_name
from script_quality_evaluator.web_utils import make_unique_run_name, mask_secret, sanitize_upload_filename


OUTPUT_BASE = ROOT / "output"
UPLOAD_BASE = ROOT / "tmp_uploads"
PREVIEW_LIMIT = 6000


st.set_page_config(page_title="电视剧剧本质量评测系统", layout="wide")


def main() -> None:
    st.title("电视剧剧本质量评测系统")
    st.write(
        "上传 8-12 集精短悬疑剧剧本，系统将从悬念信息、人物链条、单集结构、逻辑因果、"
        "场景密度、主题表达、结尾回收等维度进行 LLM 评测，并生成结构化报告。"
    )

    uploaded_file = st.file_uploader("上传剧本", type=["md", "txt"])
    default_run_name = safe_run_name(Path(uploaded_file.name).stem) if uploaded_file else "script"
    run_name_input = st.text_input("本次评测名称", value=default_run_name)

    with st.expander("高级配置", expanded=False):
        st.caption("留空时使用部署环境中的默认配置。API Key 不会在页面回显，也不会写入结果文件。")
        base_url = st.text_input("Base URL", placeholder="例如：https://api.deepseek.com")
        api_key = st.text_input("API Key", type="password")
        main_model = st.text_input("主评测模型", placeholder="例如：deepseek-v4-flash")
        judge_model = st.text_input("复核与报告模型", placeholder="例如：deepseek-v4-pro")

    progress_slot = st.empty()
    artifact_slot = st.empty()
    report_slot = st.container()

    if st.button("开始评测", type="primary"):
        if not uploaded_file:
            st.error("请先上传 .md 或 .txt 格式的剧本文件。")
            return

        config = _resolve_config(
            {
                "base_url": base_url,
                "api_key": api_key,
                "main_model": main_model,
                "judge_model": judge_model,
            }
        )
        if not config.has_api_credentials():
            st.error("缺少 API 配置，无法运行 LLM 评测。请填写 API Key / Base URL，或在部署环境中配置默认环境变量。")
            return

        try:
            upload_path, safe_run = _save_upload(uploaded_file, run_name_input)
        except ValueError as exc:
            st.error(str(exc))
            return

        output_dir = OUTPUT_BASE / safe_run
        progress_lines: list[str] = []

        def progress_callback(message: str) -> None:
            progress_lines.append(_friendly_progress(message))
            _render_progress(progress_slot, progress_lines)
            _render_checkpoint_names(artifact_slot, output_dir)

        try:
            progress_callback("正在读取剧本")
            result = run_pipeline(
                input_path=upload_path,
                output_dir=OUTPUT_BASE,
                run_name=safe_run,
                mode="llm",
                config=config,
                progress=progress_callback,
            )
            output_dir = Path(result["output_dir"])
            progress_callback("评测完成")
        except Exception as exc:  # noqa: BLE001 - Streamlit should keep partial artifacts visible.
            st.error(f"评测未完成：{mask_secret(exc, config.api_key)}")
            _render_progress(progress_slot, progress_lines)
            _render_artifacts(artifact_slot, output_dir)
            _render_downloads(report_slot, output_dir)
            return

        _render_artifacts(artifact_slot, output_dir)
        _render_final_report(report_slot, output_dir)
        _render_downloads(report_slot, output_dir)


def _resolve_config(form_values: dict[str, str]) -> RuntimeConfig:
    deployment_defaults = _streamlit_secret_defaults()
    overrides = {**deployment_defaults, **_non_empty(form_values)}
    return RuntimeConfig.from_env(overrides)


def _streamlit_secret_defaults() -> dict[str, str]:
    defaults: dict[str, str] = {}
    secret_map = {
        "api_key": ("API_KEY", ("SCRIPT_EVAL_API_KEY", "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "API_KEY")),
        "base_url": ("BASE_URL", ("SCRIPT_EVAL_BASE_URL", "BASE_URL")),
        "main_model": ("MAIN_MODEL", ("SCRIPT_EVAL_MODEL", "MAIN_MODEL")),
        "judge_model": ("JUDGE_MODEL", ("SCRIPT_EVAL_JUDGE_MODEL", "JUDGE_MODEL")),
    }
    for target, (secret_key, env_keys) in secret_map.items():
        if any(os.getenv(key) for key in env_keys):
            continue
        value = _secret(secret_key)
        if value:
            defaults[target] = value
    return defaults


def _secret(key: str) -> str | None:
    try:
        value = st.secrets.get(key)
    except Exception:  # noqa: BLE001 - Local runs may not have a secrets file.
        return None
    return str(value).strip() if value else None


def _non_empty(values: dict[str, str]) -> dict[str, str]:
    return {key: value.strip() for key, value in values.items() if value and value.strip()}


def _save_upload(uploaded_file: Any, run_name: str) -> tuple[Path, str]:
    filename = sanitize_upload_filename(uploaded_file.name)
    data = uploaded_file.getvalue()
    if not data or not data.decode("utf-8", errors="ignore").strip():
        raise ValueError("剧本内容为空，请上传包含正文的 .md 或 .txt 文件。")

    safe_run = make_unique_run_name(OUTPUT_BASE, run_name or Path(filename).stem)
    upload_dir = UPLOAD_BASE / safe_run
    upload_dir.mkdir(parents=True, exist_ok=True)
    upload_path = upload_dir / filename
    upload_path.write_bytes(data)
    return upload_path, safe_run


def _friendly_progress(message: str) -> str:
    mapping = {
        "读取输入": "正在读取剧本",
        "00 输入校验": "正在检查剧本格式",
        "01 剧本切分": "正在进行结构解析",
        "02 分集结构": "正在梳理单集结构",
        "03 场景功能": "正在分析场景功能",
        "04 人物行动": "正在提取人物行动链条",
        "05 信息释放": "正在分析悬念信息释放",
        "06 伏笔候选": "正在整理伏笔与回收线索",
        "07 汇总全局事实": "正在汇总剧本信息",
        "08 生成问题候选": "正在生成问题候选",
        "评分 Round A": "正在进行第一轮维度评分",
        "评分 Round B": "正在进行第二轮维度评分",
        "校准分数": "正在进行双轮评分校准",
        "生成低分诊断": "正在生成低分诊断",
        "生成最终报告": "正在生成 final report",
        "写入结果文件": "正在整理结果文件",
    }
    for prefix, friendly in mapping.items():
        if message.startswith(prefix):
            return f"{friendly}：{message}"
    if message.startswith("复用 checkpoint"):
        return f"正在复用已完成步骤：{message.replace('复用 checkpoint:', '').strip()}"
    return message


def _render_progress(slot: Any, progress_lines: list[str]) -> None:
    with slot.container():
        st.subheader("当前进度")
        for item in progress_lines[-12:]:
            st.write(f"- {item}")


def _render_checkpoint_names(slot: Any, output_dir: Path) -> None:
    files = _checkpoint_files(output_dir)
    if not files:
        return
    with slot.container():
        st.subheader("过程产物")
        for path in files[-8:]:
            st.write(f"- {path.name}")


def _render_artifacts(slot: Any, output_dir: Path) -> None:
    files = _checkpoint_files(output_dir)
    with slot.container():
        st.subheader("过程产物")
        if not files:
            st.info("当前还没有生成过程文件。")
            return
        st.dataframe(
            [
                {
                    "文件名": path.name,
                    "更新时间": _mtime(path),
                    "文件类型": path.suffix.lower() or "文件",
                }
                for path in files
            ],
            use_container_width=True,
            hide_index=True,
        )
        selected_name = st.selectbox(
            "选择文件预览",
            [path.name for path in files],
            key=f"checkpoint-preview-{output_dir.name}",
        )
        selected_path = next(path for path in files if path.name == selected_name)
        st.caption(f"内容预览：{selected_path.name}")
        st.code(_preview_file(selected_path), language=_preview_language(selected_path))
        st.download_button(
            "下载该文件",
            data=selected_path.read_bytes(),
            file_name=selected_path.name,
            mime=_mime_type(selected_path),
            key=f"download-checkpoint-{output_dir.name}-{selected_path.name}",
        )


def _render_final_report(container: Any, output_dir: Path) -> None:
    with container:
        st.subheader("最终报告")
        _render_score_summary(output_dir)
        report_path = output_dir / "final_report.md"
        if not report_path.exists():
            st.info("还没有生成 final_report.md。")
            return
        st.markdown(report_path.read_text(encoding="utf-8"))


def _render_score_summary(output_dir: Path) -> None:
    score_path = output_dir / "final_score.json"
    if not score_path.exists():
        return
    final_score = json.loads(score_path.read_text(encoding="utf-8"))
    total_score = final_score.get("total_score")
    final_grade = final_score.get("final_grade")
    if total_score is not None:
        st.metric("总分", f"{total_score}", final_grade or "")
    dimension_scores = final_score.get("dimension_scores")
    if isinstance(dimension_scores, list):
        st.dataframe(
            [
                {
                    "维度": item.get("dimension_name") or item.get("dimension"),
                    "分数": item.get("score"),
                    "权重": item.get("weight"),
                    "加权分": item.get("weighted_score"),
                }
                for item in dimension_scores
            ],
            use_container_width=True,
            hide_index=True,
        )

    diagnosis_path = output_dir / "low_score_diagnoses.json"
    if diagnosis_path.exists():
        diagnoses = json.loads(diagnosis_path.read_text(encoding="utf-8")).get("low_score_diagnoses", [])
        if diagnoses:
            st.write("低分维度摘要")
            for item in diagnoses:
                st.write(f"- {item.get('dimension_name') or item.get('dimension')}：{item.get('summary') or item.get('problem_summary') or '需重点复核'}")


def _render_downloads(container: Any, output_dir: Path) -> None:
    with container:
        st.subheader("下载")
        report_path = output_dir / "final_report.md"
        if report_path.exists():
            st.download_button(
                "下载最终报告",
                data=report_path.read_bytes(),
                file_name="final_report.md",
                mime="text/markdown",
                key=f"download-report-{output_dir.name}",
            )
        if output_dir.exists():
            st.download_button(
                "下载完整结果包",
                data=_zip_output(output_dir),
                file_name=f"{output_dir.name}.zip",
                mime="application/zip",
                key=f"download-zip-{output_dir.name}",
            )


def _checkpoint_files(output_dir: Path) -> list[Path]:
    checkpoint_dir = output_dir / "progress" / "checkpoints"
    if not checkpoint_dir.exists():
        return []
    return sorted((path for path in checkpoint_dir.iterdir() if path.is_file()), key=lambda item: item.stat().st_mtime)


def _preview_file(path: Path, limit: int = PREVIEW_LIMIT) -> str:
    try:
        if path.suffix.lower() == ".json":
            data = json.loads(path.read_text(encoding="utf-8"))
            text = json.dumps(data, ensure_ascii=False, indent=2)
        else:
            text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001 - Keep artifact listing usable.
        text = f"无法预览该文件：{exc}"
    if len(text) > limit:
        return text[:limit] + "\n\n...内容较长，完整内容请下载文件查看。"
    return text


def _preview_language(path: Path) -> str:
    if path.suffix.lower() == ".json":
        return "json"
    if path.suffix.lower() == ".md":
        return "markdown"
    return "text"


def _mime_type(path: Path) -> str:
    if path.suffix.lower() == ".json":
        return "application/json"
    if path.suffix.lower() == ".md":
        return "text/markdown"
    return "text/plain"


def _mtime(path: Path) -> str:
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")


def _zip_output(output_dir: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(output_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(output_dir.parent))
    buffer.seek(0)
    return buffer.getvalue()


if __name__ == "__main__":
    main()
