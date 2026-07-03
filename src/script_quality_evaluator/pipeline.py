from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable

from .extraction import extract_episode_maps, generate_issue_candidates, reduce_global, split_script, validate_input
from .io_utils import read_text, write_json, write_markdown
from .llm_client import LLMClient, PromptNodeRunner
from .report import render_report
from .schemas import DIMENSION_BY_ID, DIMENSIONS, LOW_SCORE_THRESHOLD, SCORE_STABILITY_TOLERANCE
from .scoring import calibrate_scores, collect_low_score_diagnoses, compute_final_score, ensure_low_score_diagnoses, score_all_dimensions


SCORE_PROMPTS = {
    "D1": "score_D1_suspense_information",
    "D2": "score_D2_character_chain",
    "D3": "score_D3_episode_structure",
    "D4": "score_D4_logic",
    "D5": "score_D5_scene_density",
    "D6": "score_D6_theme",
    "D7": "score_D7_ending",
}


def run_pipeline(
    input_path: str | Path,
    output_dir: str | Path,
    metadata_path: str | Path | None = None,
    mode: str = "rules",
    llm_client: LLMClient | None = None,
    prompt_dir: str | Path | None = None,
    prompt_runner: PromptNodeRunner | None = None,
    judge_model: str | None = None,
    run_name: str | None = None,
    progress: Callable[[str], None] | None = None,
    resume: bool = False,
    rerun_judging: bool = False,
) -> dict:
    if mode not in {"rules", "llm"}:
        raise ValueError("mode must be 'rules' or 'llm'")
    input_path = Path(input_path)
    output_dir = _run_output_dir(input_path, Path(output_dir), run_name)
    if mode == "llm":
        runner = prompt_runner or PromptNodeRunner(
            llm_client or LLMClient.from_env(),
            prompt_dir=prompt_dir,
            judge_client=LLMClient.judge_from_env(judge_model),
        )
        return _run_llm_pipeline(input_path, output_dir, metadata_path, runner, progress, resume, rerun_judging)

    _progress(progress, "读取输入")
    metadata = _read_metadata(metadata_path)
    raw_text = read_text(input_path)
    _check_run_manifest(output_dir, input_path, raw_text, resume)

    _progress(progress, "校验输入")
    input_profile = validate_input(raw_text, metadata)
    _progress(progress, "切分剧本")
    script_units = split_script(raw_text)
    _progress(progress, "抽取分集信息")
    episode_maps = extract_episode_maps(script_units)
    _progress(progress, "汇总全局事实")
    global_facts = reduce_global(input_profile, script_units, episode_maps)
    _progress(progress, "生成问题候选")
    issue_candidates = generate_issue_candidates(input_profile, global_facts)

    _progress(progress, "评分 Round A")
    scores_round_a = score_all_dimensions(input_profile, global_facts, issue_candidates, "A")
    _progress(progress, "评分 Round B")
    scores_round_b = score_all_dimensions(input_profile, global_facts, issue_candidates, "B")
    _progress(progress, "校准分数")
    calibrated_scores = calibrate_scores(scores_round_a["scores"], scores_round_b["scores"])

    _progress(progress, "生成最终报告")
    final_score = compute_final_score(calibrated_scores["calibrated_scores"], issue_candidates["issue_candidates"])

    # Low-score diagnoses should reflect calibrated final scores, while preserving detail from round A.
    scores_for_diagnosis = _merge_calibrated_into_scores(scores_round_a["scores"], calibrated_scores["calibrated_scores"])
    low_score_diagnoses = collect_low_score_diagnoses(scores_for_diagnosis)
    low_score_diagnoses = ensure_low_score_diagnoses(
        low_score_diagnoses,
        calibrated_scores,
        scores_round_a["scores"],
        global_facts,
    )

    final_report = render_report(input_profile, global_facts, issue_candidates, calibrated_scores, low_score_diagnoses, final_score)

    _progress(progress, "写入结果文件")
    _write_artifacts(
        output_dir,
        input_profile,
        script_units,
        episode_maps,
        global_facts,
        issue_candidates,
        scores_round_a,
        scores_round_b,
        calibrated_scores,
        low_score_diagnoses,
        final_score,
        final_report,
    )
    _write_run_manifest(output_dir, input_path, raw_text)

    return {
        "input_profile": input_profile,
        "script_units": script_units,
        "episode_maps": episode_maps,
        **global_facts,
        "issue_candidates": issue_candidates,
        "scores_round_a": scores_round_a,
        "scores_round_b": scores_round_b,
        "calibrated_scores": calibrated_scores,
        "low_score_diagnoses": low_score_diagnoses,
        "final_score": final_score,
        "final_report": final_report,
        "output_dir": str(output_dir),
    }


def _run_llm_pipeline(
    input_path: str | Path,
    output_dir: str | Path,
    metadata_path: str | Path | None,
    runner: PromptNodeRunner,
    progress: Callable[[str], None] | None = None,
    resume: bool = False,
    rerun_judging: bool = False,
) -> dict:
    input_path = Path(input_path)
    output_dir = Path(output_dir)
    checkpoints = _CheckpointStore(
        output_dir / "progress" / "checkpoints",
        resume,
        progress,
        refresh_prefixes=_judging_checkpoint_prefixes() if rerun_judging else (),
    )
    _progress(progress, "读取输入")
    metadata = _read_metadata(metadata_path)
    raw_text = read_text(input_path)
    _check_run_manifest(output_dir, input_path, raw_text, resume)

    input_profile = checkpoints.json(
        "00_input_validation",
        lambda: _checked_node("00_input_validation", runner.run("00_input_validation", {"raw_script": raw_text, "metadata": metadata})),
        "00 输入校验",
    )
    script_units = _normalize_script_units(checkpoints.json(
        "01_script_split",
        lambda: _checked_node("01_script_split", runner.run("01_script_split", {"raw_script": raw_text, "input_profile": input_profile})),
        "01 剧本切分",
    ))
    episode_maps = _llm_episode_maps(runner, input_profile, script_units, progress, checkpoints)
    global_facts = _normalize_global_facts(checkpoints.json(
        "07_global_reduce",
        lambda: _checked_node(
            "07_global_reduce",
            runner.run(
                "07_global_reduce",
                {
                    "input_profile": input_profile,
                    "script_units": script_units,
                    "episode_maps": episode_maps,
                },
            ),
        ),
        "07 汇总全局事实",
    ))
    issue_candidates = _checked_issue_candidates(checkpoints.json(
        "08_issue_candidates",
        lambda: runner.run("08_issue_candidates", {"input_profile": input_profile, "global_facts": global_facts}),
        "08 生成问题候选",
    ))
    scores_round_a = _llm_score_round(runner, "A", input_profile, global_facts, issue_candidates, progress, checkpoints)
    scores_round_b = _llm_score_round(runner, "B", input_profile, global_facts, issue_candidates, progress, checkpoints)
    calibrated_scores = _checked_calibrated_scores(checkpoints.json(
        "score_calibration",
        lambda: runner.run(
            "score_calibration",
            {
                "scores_round_a": scores_round_a,
                "scores_round_b": scores_round_b,
                "global_facts": global_facts,
                "issue_candidates": issue_candidates,
            },
        ),
        "校准分数",
    ))
    final_score = compute_final_score(calibrated_scores["calibrated_scores"], issue_candidates["issue_candidates"])
    if _has_low_scores(calibrated_scores):
        low_score_diagnoses = checkpoints.json(
            "low_score_diagnosis",
            lambda: _checked_node(
                "low_score_diagnosis",
                runner.run(
                    "low_score_diagnosis",
                    {
                        "calibrated_scores": calibrated_scores,
                        "global_facts": global_facts,
                        "issue_candidates": issue_candidates,
                    },
                ),
            ),
            "生成低分诊断",
        )
    else:
        _progress(progress, "跳过低分诊断：无 3.0 以下分项")
        low_score_diagnoses = {"low_score_diagnoses": []}
    low_score_diagnoses = ensure_low_score_diagnoses(
        low_score_diagnoses,
        calibrated_scores,
        scores_round_a["scores"],
        global_facts,
    )
    final_report = checkpoints.text(
        "final_report",
        lambda: runner.run_text(
            "final_report",
            {
                "input_profile": input_profile,
                "global_facts": global_facts,
                "issue_candidates": issue_candidates,
                "calibrated_scores": calibrated_scores,
                "low_score_diagnoses": low_score_diagnoses,
                "final_score": final_score,
            },
        ),
        "生成最终报告",
    )
    if _is_error_report(final_report) or _has_fragmented_risk_notes(final_report):
        _progress(progress, "模型报告不可用，使用本地报告模板")
        final_report = render_report(input_profile, global_facts, issue_candidates, calibrated_scores, low_score_diagnoses, final_score)
        write_markdown(output_dir / "progress" / "checkpoints" / "final_report.md", final_report)

    _progress(progress, "写入结果文件")
    _write_artifacts(
        output_dir,
        input_profile,
        script_units,
        episode_maps,
        global_facts,
        issue_candidates,
        scores_round_a,
        scores_round_b,
        calibrated_scores,
        low_score_diagnoses,
        final_score,
        final_report,
    )
    _write_run_manifest(output_dir, input_path, raw_text)

    return {
        "input_profile": input_profile,
        "script_units": script_units,
        "episode_maps": episode_maps,
        **global_facts,
        "issue_candidates": issue_candidates,
        "scores_round_a": scores_round_a,
        "scores_round_b": scores_round_b,
        "calibrated_scores": calibrated_scores,
        "low_score_diagnoses": low_score_diagnoses,
        "final_score": final_score,
        "final_report": final_report,
        "output_dir": str(output_dir),
    }


def _llm_episode_maps(
    runner: PromptNodeRunner,
    input_profile: dict,
    script_units: dict,
    progress: Callable[[str], None] | None = None,
    checkpoints: "_CheckpointStore | None" = None,
) -> dict:
    maps = {
        "episode_structures": [],
        "scene_functions": [],
        "character_actions": [],
        "information_release": [],
        "setup_candidates": [],
    }
    episodes = script_units["episodes"]
    for index, episode in enumerate(episodes, start=1):
        episode_id = episode["episode_id"]
        payload = {"input_profile": input_profile, "episode": episode}
        prefix = f"{episode_id} ({index}/{len(episodes)})"
        structure = _checkpoint_json(
            checkpoints,
            f"02_episode_structure_extract_{episode_id}",
            lambda: _checked_node("02_episode_structure_extract", runner.run("02_episode_structure_extract", payload)),
            f"02 分集结构 {prefix}",
            progress,
        )
        if "episode_id" not in structure:
            structure = {**structure, "episode_id": episode_id}
        maps["episode_structures"].append(structure)
        maps["scene_functions"].extend(
            _checkpoint_json(
                checkpoints,
                f"03_scene_function_extract_{episode_id}",
                lambda: _episode_result_items("03_scene_function_extract", runner.run("03_scene_function_extract", payload), "scene_functions", episode_id),
                f"03 场景功能 {prefix}",
                progress,
            )
        )
        maps["character_actions"].extend(
            _checkpoint_json(
                checkpoints,
                f"04_character_action_extract_{episode_id}",
                lambda: _episode_result_items("04_character_action_extract", runner.run("04_character_action_extract", payload), "character_actions", episode_id),
                f"04 人物行动 {prefix}",
                progress,
            )
        )
        maps["information_release"].extend(
            _checkpoint_json(
                checkpoints,
                f"05_information_release_extract_{episode_id}",
                lambda: _episode_result_items("05_information_release_extract", runner.run("05_information_release_extract", payload), "information_release", episode_id),
                f"05 信息释放 {prefix}",
                progress,
            )
        )
        maps["setup_candidates"].extend(
            _checkpoint_json(
                checkpoints,
                f"06_setup_candidate_extract_{episode_id}",
                lambda: _episode_result_items("06_setup_candidate_extract", runner.run("06_setup_candidate_extract", payload), "setup_candidates", episode_id),
                f"06 伏笔候选 {prefix}",
                progress,
            )
        )
    return maps


def _llm_score_round(
    runner: PromptNodeRunner,
    round_name: str,
    input_profile: dict,
    global_facts: dict,
    issue_candidates: dict,
    progress: Callable[[str], None] | None = None,
    checkpoints: "_CheckpointStore | None" = None,
) -> dict:
    scores = []
    for dimension in DIMENSIONS:
        node = SCORE_PROMPTS[dimension["id"]]
        score = _normalize_score_item(
            node,
            _checkpoint_json(
                checkpoints,
                f"score_round_{round_name}_{dimension['id']}",
                lambda: runner.run(
                    node,
                    {
                        "round": round_name,
                        "dimension": dimension,
                        "input_profile": input_profile,
                        "global_facts": global_facts,
                        "issue_candidates": issue_candidates,
                    },
                ),
                f"评分 Round {round_name} {dimension['id']}",
                progress,
            ),
            dimension,
        )
        scores.append(score)
    return {"round": round_name, "scores": scores}


class _CheckpointStore:
    def __init__(
        self,
        directory: Path,
        resume: bool,
        progress: Callable[[str], None] | None = None,
        refresh_prefixes: tuple[str, ...] = (),
    ) -> None:
        self.directory = directory
        self.resume = resume
        self.progress = progress
        self.refresh_prefixes = refresh_prefixes

    def json(self, name: str, compute: Callable[[], Any], label: str) -> Any:
        path = self.directory / f"{name}.json"
        if self.resume and path.exists() and not self._should_refresh(name):
            _progress(self.progress, f"复用 checkpoint: {label}")
            return json.loads(path.read_text(encoding="utf-8"))
        _progress(self.progress, label)
        result = compute()
        write_json(path, result)
        return result

    def text(self, name: str, compute: Callable[[], str], label: str) -> str:
        path = self.directory / f"{name}.md"
        if self.resume and path.exists() and not self._should_refresh(name):
            _progress(self.progress, f"复用 checkpoint: {label}")
            return path.read_text(encoding="utf-8")
        _progress(self.progress, label)
        result = compute()
        write_markdown(path, result)
        return result

    def _should_refresh(self, name: str) -> bool:
        return any(name.startswith(prefix) for prefix in self.refresh_prefixes)


def _checkpoint_json(
    checkpoints: _CheckpointStore | None,
    name: str,
    compute: Callable[[], Any],
    label: str,
    progress: Callable[[str], None] | None,
) -> Any:
    if checkpoints:
        return checkpoints.json(name, compute, label)
    _progress(progress, label)
    return compute()


def _judging_checkpoint_prefixes() -> tuple[str, ...]:
    return ("score_round_", "score_calibration", "low_score_diagnosis", "final_report")


def _run_output_dir(input_path: Path, output_base: Path, run_name: str | None = None) -> Path:
    return output_base / _safe_run_name(run_name or input_path.stem)


def _safe_run_name(name: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", name.strip(), flags=re.UNICODE).strip("._")
    return cleaned or "script"


def _check_run_manifest(output_dir: Path, input_path: Path, raw_text: str, resume: bool) -> None:
    manifest_path = output_dir / "progress" / "run_manifest.json"
    if not resume or not manifest_path.exists():
        return
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    current = _run_manifest(input_path, raw_text)
    if manifest.get("input_sha256") != current["input_sha256"]:
        raise RuntimeError(
            "当前 --resume 指向的输出文件夹属于另一份输入。"
            f"已有输入：{manifest.get('input_path', '未知')}；当前输入：{current['input_path']}。"
            "请换 --run-name，或删除/更换对应输出文件夹后重跑。"
        )


def _write_run_manifest(output_dir: Path, input_path: Path, raw_text: str) -> None:
    write_json(output_dir / "progress" / "run_manifest.json", _run_manifest(input_path, raw_text))


def _run_manifest(input_path: Path, raw_text: str) -> dict:
    return {
        "input_path": str(input_path),
        "input_name": input_path.name,
        "input_sha256": hashlib.sha256(raw_text.encode("utf-8")).hexdigest(),
    }


def _checked_issue_candidates(result: Any) -> dict:
    if isinstance(result, list):
        result = {"issue_candidates": result}
    checked = _checked_node("08_issue_candidates", result)
    items = checked.get("issue_candidates")
    if not isinstance(items, list):
        raise TypeError(f"08_issue_candidates.issue_candidates must be a JSON array, got {type(items).__name__}")
    return {"issue_candidates": [_normalize_issue_candidate(item, index) for index, item in enumerate(items, start=1)]}


def _normalize_issue_candidate(item: Any, index: int) -> dict:
    if not isinstance(item, dict):
        raise TypeError("08_issue_candidates.issue_candidates items must be JSON objects")
    normalized = dict(item)
    normalized.setdefault("issue_id", f"I{index:03d}")
    normalized.setdefault("issue_type", "待复核问题")
    normalized.setdefault("related_positions", [])
    normalized.setdefault("related_characters", [])
    normalized.setdefault("related_clues", [])
    normalized.setdefault("trigger_evidence", normalized.get("evidence", ""))
    normalized.setdefault("needs_review", normalized.get("review_note", normalized.get("trigger_evidence", "需人工复核")))
    for key in ["related_positions", "related_characters", "related_clues"]:
        if not isinstance(normalized[key], list):
            normalized[key] = [str(normalized[key])]
    return normalized


def _checked_calibrated_scores(result: Any) -> dict:
    if isinstance(result, list):
        result = {"calibrated_scores": result}
    checked = _checked_node("score_calibration", result)
    items = _first_list_value(checked, ["calibrated_scores", "arbitrated_scores", "scores", "calibrations", "results"])
    if items is None:
        raise ValueError("score_calibration did not return 'calibrated_scores'")
    return {"calibrated_scores": [_normalize_calibrated_score(item) for item in items]}


def _normalize_score_item(node: str, result: Any, dimension: dict) -> dict:
    checked = _checked_node(node, result)
    dimension_id = checked.get("dimension") or checked.get("dimension_id") or checked.get("id") or dimension["id"]
    if dimension_id != dimension["id"]:
        raise ValueError(f"{node} returned dimension {dimension_id}, expected {dimension['id']}")
    score = _score_value(checked, dimension["id"])
    if score is None:
        raise ValueError(f"{node} missing score")
    normalized = dict(checked)
    normalized["dimension"] = dimension["id"]
    normalized["dimension_name"] = normalized.get("dimension_name", dimension["name"])
    normalized["weight"] = int(normalized.get("weight") or dimension["weight"])
    normalized["score"] = round(float(score), 1)
    if "score_reason" not in normalized and isinstance(normalized.get("diagnosis"), str):
        normalized["score_reason"] = normalized["diagnosis"]
    normalized.setdefault("low_score_diagnosis", None)
    return normalized


def _normalize_global_facts(global_facts: dict) -> dict:
    checked = _checked_node("07_global_reduce", global_facts)
    normalized = dict(checked)
    if isinstance(normalized.get("episode_structure"), list):
        normalized["episode_structure"] = {
            "main_story_goal": "",
            "episodes": normalized["episode_structure"],
            "unclosed_mainline_questions": [],
        }
    if isinstance(normalized.get("scene_functions"), list):
        normalized["scene_functions"] = {
            "scene_functions": normalized["scene_functions"],
            "statistics": {},
        }
    if isinstance(normalized.get("character_chains"), list):
        normalized["character_chains"] = {"characters": normalized["character_chains"]}
    if isinstance(normalized.get("information_release"), list):
        normalized["information_release"] = {
            "information_release": normalized["information_release"],
            "knowledge_state_summary": "",
        }
    if isinstance(normalized.get("setup_payoff_map"), list):
        normalized["setup_payoff_map"] = {"setup_payoff_map": normalized["setup_payoff_map"]}
    return normalized


def _score_value(item: dict, dimension_id: str) -> Any:
    for key in ["score", "final_score", "calibrated_score", "arbitrated_score", dimension_id]:
        value = item.get(key)
        if isinstance(value, (int, float)):
            return value
    scores = item.get("scores")
    if isinstance(scores, dict):
        values = [value for value in scores.values() if isinstance(value, (int, float))]
        if values:
            return sum(values) / len(values)
    if isinstance(scores, list):
        values = [_score_value(score, dimension_id) for score in scores if isinstance(score, dict)]
        values = [value for value in values if isinstance(value, (int, float))]
        if values:
            return sum(values) / len(values)
    return None


def _is_error_report(content: str) -> bool:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, dict) and parsed.get("error") is True


def _has_fragmented_risk_notes(content: str) -> bool:
    return "\n- 涉\n- 及\n" in content


def _has_low_scores(calibrated_scores: dict) -> bool:
    return any(float(item.get("final_score", 0)) < LOW_SCORE_THRESHOLD for item in calibrated_scores.get("calibrated_scores", []))


def _first_list_value(data: dict, keys: list[str]) -> list[Any] | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, list):
            return value
    return None


def _normalize_calibrated_score(item: Any) -> dict:
    if not isinstance(item, dict):
        raise TypeError("score_calibration.calibrated_scores items must be JSON objects")
    dimension = item.get("dimension") or item.get("dimension_id") or item.get("id")
    if dimension not in {definition["id"] for definition in DIMENSIONS}:
        raise ValueError(f"score_calibration item has invalid dimension: {dimension}")
    final_score = item.get("final_score", item.get("score", item.get("arbitrated_score", item.get("calibrated_score"))))
    if final_score is None:
        raise ValueError(f"score_calibration {dimension} missing final_score")
    score_a = item.get("score_a", item.get("round_a_score"))
    score_b = item.get("score_b", item.get("round_b_score"))
    normalized = dict(item)
    normalized["dimension"] = dimension
    normalized["dimension_name"] = normalized.get("dimension_name", DIMENSION_BY_ID[dimension]["name"])
    normalized["weight"] = int(normalized.get("weight") or DIMENSION_BY_ID[dimension]["weight"])
    normalized["score_a"] = float(score_a) if score_a is not None else float(final_score)
    normalized["score_b"] = float(score_b) if score_b is not None else float(final_score)
    normalized["difference"] = float(normalized.get("difference", abs(normalized["score_a"] - normalized["score_b"])))
    normalized["status"] = normalized.get("status", "通过" if normalized["difference"] <= SCORE_STABILITY_TOLERANCE else "需仲裁")
    normalized["final_score"] = round(float(final_score), 1)
    normalized["arbitration_reason"] = normalized.get("arbitration_reason", normalized.get("reason", "模型校准输出"))
    return normalized


def _episode_result_items(node: str, result: Any, key: str, episode_id: str) -> list[dict]:
    if isinstance(result, list):
        return _with_episode_id(result, episode_id)
    checked = _checked_node(node, result)
    if key not in checked:
        raise ValueError(f"{node} did not return '{key}'")
    items = checked[key]
    if not isinstance(items, list):
        raise TypeError(f"{node}.{key} must be a JSON array, got {type(items).__name__}")
    return _with_episode_id(items, episode_id)


def _checked_node(node: str, result: dict) -> dict:
    if not isinstance(result, dict):
        raise TypeError(f"{node} must return a JSON object, got {type(result).__name__}")
    if result.get("error"):
        reason = result.get("reason", "unknown error")
        raise RuntimeError(f"{node} failed: {reason}")
    return result


def _progress(progress: Callable[[str], None] | None, message: str) -> None:
    if progress:
        progress(message)


def _normalize_script_units(script_units: dict) -> dict:
    episodes = script_units.get("episodes")
    if not isinstance(episodes, list):
        raise TypeError("01_script_split.episodes must be a JSON array")

    normalized_episodes = []
    for episode_index, episode in enumerate(episodes, start=1):
        if not isinstance(episode, dict):
            raise TypeError("01_script_split.episodes items must be JSON objects")
        source_episode_id = episode.get("episode_id")
        episode_id = _canonical_episode_id(source_episode_id, episode_index)
        scenes = episode.get("scenes") or []
        if not isinstance(scenes, list):
            raise TypeError(f"01_script_split {episode_id}.scenes must be a JSON array")
        normalized_scenes = []
        for scene_index, scene in enumerate(scenes, start=1):
            if not isinstance(scene, dict):
                raise TypeError(f"01_script_split {episode_id}.scenes items must be JSON objects")
            source_scene_id = scene.get("scene_id")
            scene_id = _canonical_scene_id(source_scene_id, episode_id, scene_index)
            copied = dict(scene)
            if source_scene_id and source_scene_id != scene_id and not copied.get("source_scene_id"):
                copied["source_scene_id"] = source_scene_id
            copied["scene_id"] = scene_id
            normalized_scenes.append(copied)
        copied_episode = dict(episode)
        if source_episode_id and source_episode_id != episode_id and not copied_episode.get("source_episode_id"):
            copied_episode["source_episode_id"] = source_episode_id
        copied_episode["episode_id"] = episode_id
        copied_episode["scenes"] = normalized_scenes
        normalized_episodes.append(copied_episode)
    return {**script_units, "episodes": normalized_episodes}


def _canonical_episode_id(value: Any, index: int) -> str:
    if isinstance(value, str):
        match = re.fullmatch(r"E0?(\d{1,2})", value.strip(), flags=re.IGNORECASE)
        if match:
            return f"E{int(match.group(1)):02d}"
    return f"E{index:02d}"


def _canonical_scene_id(value: Any, episode_id: str, index: int) -> str:
    if isinstance(value, str):
        match = re.fullmatch(r"E0?\d{1,2}-S0?(\d{1,2})", value.strip(), flags=re.IGNORECASE)
        if match:
            return f"{episode_id}-S{int(match.group(1)):02d}"
    return f"{episode_id}-S{index:02d}"


def _with_episode_id(items: list[dict], episode_id: str) -> list[dict]:
    normalized = []
    for item in items:
        if isinstance(item, dict) and "episode_id" not in item:
            copied = dict(item)
            copied["episode_id"] = episode_id
            normalized.append(copied)
        else:
            normalized.append(item)
    return normalized


def _read_metadata(metadata_path: str | Path | None) -> dict:
    if not metadata_path:
        return {}
    path = Path(metadata_path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _merge_calibrated_into_scores(scores: list[dict], calibrated: list[dict]) -> list[dict]:
    by_dimension = {item["dimension"]: item for item in calibrated}
    merged = []
    for score in scores:
        copied = dict(score)
        final = by_dimension[score["dimension"]]["final_score"]
        copied["score"] = final
        if final >= LOW_SCORE_THRESHOLD:
            copied["low_score_diagnosis"] = None
        elif copied.get("low_score_diagnosis"):
            copied["low_score_diagnosis"] = dict(copied["low_score_diagnosis"])
            copied["low_score_diagnosis"]["score"] = final
        else:
            copied["low_score_diagnosis"] = None
        merged.append(copied)
    return merged


def _write_artifacts(
    output_dir: Path,
    input_profile: dict,
    script_units: dict,
    episode_maps: dict,
    global_facts: dict,
    issue_candidates: dict,
    scores_round_a: dict,
    scores_round_b: dict,
    calibrated_scores: dict,
    low_score_diagnoses: dict,
    final_score: dict,
    final_report: str,
) -> None:
    write_json(output_dir / "low_score_diagnoses.json", low_score_diagnoses)
    write_json(output_dir / "final_score.json", final_score)
    write_markdown(output_dir / "final_report.md", final_report)
    progress_dir = output_dir / "progress"
    write_json(progress_dir / "input_profile.json", input_profile)
    write_json(progress_dir / "script_units.json", script_units)
    _write_episode_map_artifacts(progress_dir, script_units, episode_maps)
    write_json(progress_dir / "episode_structure.json", global_facts["episode_structure"])
    write_json(progress_dir / "scene_functions.json", global_facts["scene_functions"])
    write_json(progress_dir / "character_chains.json", global_facts["character_chains"])
    write_json(progress_dir / "information_release.json", global_facts["information_release"])
    write_json(progress_dir / "setup_payoff_map.json", global_facts["setup_payoff_map"])
    write_json(progress_dir / "issue_candidates.json", issue_candidates)
    write_json(progress_dir / "scores_round_a.json", scores_round_a)
    write_json(progress_dir / "scores_round_b.json", scores_round_b)
    write_json(progress_dir / "calibrated_scores.json", calibrated_scores)


def _write_episode_map_artifacts(output_dir: Path, script_units: dict, episode_maps: dict) -> None:
    episode_dir = output_dir / "episode_map"
    grouped = {episode["episode_id"]: {} for episode in script_units.get("episodes", [])}
    for key in ["episode_structures", "scene_functions", "character_actions", "information_release", "setup_candidates"]:
        for item in episode_maps[key]:
            episode_id = item["episode_id"]
            grouped.setdefault(episode_id, {}).setdefault(key, []).append(item)
    name_map = {
        "episode_structures": "structure",
        "scene_functions": "scene_functions",
        "character_actions": "character_actions",
        "information_release": "information_release",
        "setup_candidates": "setup_candidates",
    }
    for episode_id, values in grouped.items():
        for key in ["episode_structures", "scene_functions", "character_actions", "information_release", "setup_candidates"]:
            items = values.get(key, [])
            payload = items[0] if key == "episode_structures" and len(items) == 1 else {"episode_id": episode_id, key: items}
            write_json(episode_dir / f"{episode_id}_{name_map[key]}.json", payload)
