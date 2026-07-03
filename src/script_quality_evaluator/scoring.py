from __future__ import annotations

from collections import defaultdict

from .schemas import (
    CAP_RULES,
    DIMENSION_BY_ID,
    DIMENSIONS,
    ISSUE_TO_DIMENSION,
    LOW_SCORE_THRESHOLD,
    SCORE_SCALE,
    SCORE_STABILITY_TOLERANCE,
    cap_grade,
    grade_for_total,
    score_band,
)


def score_all_dimensions(input_profile: dict, global_facts: dict, issue_candidates: dict, round_name: str = "A") -> dict:
    scores = []
    for dimension in DIMENSIONS:
        scores.append(score_dimension(dimension["id"], input_profile, global_facts, issue_candidates, round_name))
    return {"round": round_name, "scores": scores}


def score_dimension(dimension_id: str, input_profile: dict, global_facts: dict, issue_candidates: dict, round_name: str = "A") -> dict:
    definition = DIMENSION_BY_ID[dimension_id]
    evidence = evidence_sufficiency(input_profile, global_facts)
    related = _related_issues(dimension_id, issue_candidates)
    base = _base_score(input_profile, global_facts)
    penalty = min(2.2, sum(_issue_penalty(issue["issue_type"]) for issue in related))
    score = max(0, base - penalty)
    caps = _triggered_caps(dimension_id, input_profile, global_facts, related)
    caps.append({"rule": "材料证据不充分", "cap": evidence["max_score_allowed"], "reason": evidence["reason"]}) if evidence["max_score_allowed"] < SCORE_SCALE else None
    for cap in caps:
        score = min(score, float(cap["cap"]))
    if round_name == "B":
        score = max(0, min(SCORE_SCALE, score - _round_b_adjustment(dimension_id, related)))
    score = round(score, 1)
    diagnosis = _low_score_diagnosis(definition, score, related, global_facts) if score < LOW_SCORE_THRESHOLD else None
    return {
        "dimension": dimension_id,
        "dimension_name": definition["name"],
        "weight": definition["weight"],
        "evidence_sufficiency": evidence,
        "checks": _checks(definition, related),
        "triggered_score_caps": caps,
        "score": score,
        "score_band": score_band(score),
        "score_reason": _score_reason(definition["name"], score, related),
        "positive_evidence": _positive_evidence(dimension_id, global_facts),
        "negative_evidence": [issue["trigger_evidence"] for issue in related[:5] if issue["trigger_evidence"]],
        "low_score_diagnosis": diagnosis,
    }


def evidence_sufficiency(input_profile: dict, global_facts: dict) -> dict:
    if input_profile["confidence_level"] == "高":
        return {"status": "充分", "reason": "材料集数与场景粒度满足第一版适用范围", "missing_evidence": [], "max_score_allowed": SCORE_SCALE}
    if input_profile["confidence_level"] == "中":
        missing = input_profile.get("cannot_evaluate", [])
        return {"status": "部分充分", "reason": "材料可评但局部粒度不足", "missing_evidence": missing, "max_score_allowed": 4}
    return {
        "status": "不充分",
        "reason": "材料不足以支撑高置信度评分",
        "missing_evidence": input_profile.get("cannot_evaluate", []),
        "max_score_allowed": LOW_SCORE_THRESHOLD,
    }


def severity_for_score(score: float) -> str:
    if score >= 2.5:
        return "中等问题"
    if score >= 2:
        return "严重问题"
    return "结构性硬伤"


def collect_low_score_diagnoses(scores: list[dict]) -> dict:
    diagnoses = [score["low_score_diagnosis"] for score in scores if score.get("low_score_diagnosis")]
    return {"low_score_diagnoses": diagnoses}


def ensure_low_score_diagnoses(
    low_score_diagnoses: dict,
    calibrated_scores: dict,
    reference_scores: list[dict],
    global_facts: dict,
) -> dict:
    diagnoses = low_score_diagnoses.get("low_score_diagnoses", []) if isinstance(low_score_diagnoses, dict) else []
    if not isinstance(diagnoses, list):
        diagnoses = []

    by_dimension = {item.get("dimension"): dict(item) for item in diagnoses if isinstance(item, dict) and item.get("dimension")}
    reference_by_dimension = {item["dimension"]: item for item in reference_scores}

    for score in calibrated_scores.get("calibrated_scores", []):
        dimension_id = score["dimension"]
        final_score = float(score["final_score"])
        if final_score >= LOW_SCORE_THRESHOLD:
            by_dimension.pop(dimension_id, None)
            continue
        diagnosis = by_dimension.get(dimension_id)
        if not diagnosis:
            reference = reference_by_dimension.get(dimension_id, {})
            diagnosis = dict(reference.get("low_score_diagnosis") or _low_score_diagnosis(DIMENSION_BY_ID[dimension_id], final_score, [], global_facts))
        diagnosis["score"] = round(final_score, 1)
        diagnosis["severity"] = severity_for_score(final_score)
        by_dimension[dimension_id] = diagnosis

    ordered = [
        by_dimension[score["dimension"]]
        for score in calibrated_scores.get("calibrated_scores", [])
        if score["dimension"] in by_dimension
    ]
    return {"low_score_diagnoses": ordered}


def calibrate_scores(round_a: list[dict], round_b: list[dict]) -> dict:
    by_b = {item["dimension"]: item for item in round_b}
    calibrated = []
    for score_a in round_a:
        score_b = by_b[score_a["dimension"]]
        difference = round(abs(score_a["score"] - score_b["score"]), 1)
        caps = score_a.get("triggered_score_caps", []) + score_b.get("triggered_score_caps", [])
        if difference > SCORE_STABILITY_TOLERANCE:
            cap_values = [float(item["cap"]) for item in caps]
            final_score = min([score_a["score"], score_b["score"]] + cap_values) if cap_values else min(score_a["score"], score_b["score"])
            status = "需仲裁"
            reason = "两轮评分差异超过 0.5，按 0-5 分制 10% 稳定性目标取更保守仲裁分"
        else:
            final_score = round((score_a["score"] + score_b["score"]) / 2, 1)
            status = "通过"
            reason = "两轮评分差异不超过 0.5，采用平均分"
        calibrated.append(
            {
                "dimension": score_a["dimension"],
                "dimension_name": score_a.get("dimension_name", ""),
                "weight": score_a.get("weight", 0),
                "score_a": score_a["score"],
                "score_b": score_b["score"],
                "difference": difference,
                "status": status,
                "final_score": round(final_score, 1),
                "arbitration_reason": reason,
            }
        )
    return {"calibrated_scores": calibrated}


def compute_final_score(scores: list[dict], top_issues: list[dict]) -> dict:
    dimension_scores = []
    total = 0.0
    score_map = {}
    for item in scores:
        score = float(item.get("final_score", item.get("score", 0)))
        weight = int(item.get("weight", DIMENSION_BY_ID[item["dimension"]]["weight"]))
        weighted_score = round(score * weight / SCORE_SCALE, 2)
        total += weighted_score
        score_map[item["dimension"]] = score
        dimension_scores.append(
            {
                "dimension": item["dimension"],
                "dimension_name": item.get("dimension_name", DIMENSION_BY_ID[item["dimension"]]["name"]),
                "weight": weight,
                "score": score,
                "score_scale": SCORE_SCALE,
                "weighted_score": weighted_score,
            }
        )
    total = round(total, 1)
    raw_grade = grade_for_total(total)
    final_grade, risk_flags = apply_grade_gates(raw_grade, score_map)
    if total < 70:
        risk_flags.append("总分低于 70，需输出 Top 5 问题")
    if total < 60:
        risk_flags.append("总分低于 60，需判断是否继续开发与是否大修")
    return {
        "total_score": total,
        "raw_grade": raw_grade,
        "final_grade": final_grade,
        "dimension_scores": dimension_scores,
        "risk_flags": sorted(set(risk_flags)),
        "top_issues": top_issues[:5],
    }


def apply_grade_gates(raw_grade: str, score_map: dict[str, float]) -> tuple[str, list[str]]:
    final_grade = raw_grade
    flags = []
    if any(score_map.get(item, SCORE_SCALE) < 2.5 for item in ["D1", "D2", "D3", "D4"]):
        final_grade = cap_grade(final_grade, "C")
        flags.append("核心机制风险")
    if score_map.get("D7", SCORE_SCALE) < LOW_SCORE_THRESHOLD:
        flags.append("结尾完成度风险")
    if score_map.get("D7", SCORE_SCALE) < 2.5:
        final_grade = cap_grade(final_grade, "C")
    if any(score < 2.0 for score in score_map.values()):
        flags.append("结构性硬伤诊断")
    return final_grade, flags


def _base_score(input_profile: dict, global_facts: dict) -> float:
    if input_profile["confidence_level"] == "高":
        base = 4.1
    elif input_profile["confidence_level"] == "中":
        base = 3.5
    else:
        base = 2.9
    functionless_ratio = global_facts["scene_functions"]["statistics"]["functionless_ratio"]
    return max(0, base - min(1.0, functionless_ratio * 2))


def _related_issues(dimension_id: str, issue_candidates: dict) -> list[dict]:
    return [
        issue
        for issue in issue_candidates["issue_candidates"]
        if dimension_id in ISSUE_TO_DIMENSION.get(issue["issue_type"], [])
    ]


def _issue_penalty(issue_type: str) -> float:
    if issue_type in {"后置硬解释", "结尾仓促", "伏笔未回收", "人物动机断裂"}:
        return 0.4
    if issue_type in {"信息释放突兀", "主线推进不明显", "场景功能不明"}:
        return 0.3
    return 0.2


def _triggered_caps(dimension_id: str, input_profile: dict, global_facts: dict, related: list[dict]) -> list[dict]:
    caps = []
    issue_types = {issue["issue_type"] for issue in related}
    unclosed = bool(global_facts["episode_structure"]["unclosed_mainline_questions"])
    if dimension_id == "D1":
        if input_profile["episode_count"] < 2:
            caps.append(_cap(dimension_id, "核心谜题不清晰启动", "材料不足以确认核心谜题启动"))
        if "信息释放突兀" in issue_types:
            caps.append(_cap(dimension_id, "关键真相无前置线索", "信息释放节点过少或过晚"))
        if "伏笔未回收" in issue_types or unclosed:
            caps.append(_cap(dimension_id, "核心谜题未完成回收", "存在未回收伏笔或主线疑问"))
    if dimension_id == "D2":
        if not global_facts["character_chains"]["characters"]:
            caps.append(_cap(dimension_id, "主角没有可追踪外部目标", "未抽取到人物行动链"))
        if "人物动机断裂" in issue_types:
            caps.append(_cap(dimension_id, "2 个以上关键行动无前置动机依据", "多个行动缺少动机证据"))
        if "人物行动无后果" in issue_types:
            caps.append(_cap(dimension_id, "多数关键行动没有后果或代价", "行动后果抽取不足"))
    if dimension_id == "D3":
        if input_profile["episode_count"] < 2:
            caps.append(_cap(dimension_id, "前 2 集未清晰启动主线", "缺少前两集材料"))
        if "场景功能不明" in issue_types:
            caps.append(_cap(dimension_id, "某一集超过 30% 场景功能不明", "场景功能不明影响节奏判断"))
        if unclosed:
            caps.append(_cap(dimension_id, "核心主线未回收", "结尾没有明确闭合信号"))
    if dimension_id == "D4":
        if "信息释放突兀" in issue_types:
            caps.append(_cap(dimension_id, "关键反转缺少前置条件", "关键真相缺少递进证据"))
    if dimension_id == "D5" and "场景功能不明" in issue_types:
        caps.append(_cap(dimension_id, "场景普遍只有对白解释，没有局面变化", "部分场景未抽取到行动或状态变化"))
    if dimension_id == "D6" and input_profile["confidence_level"] != "高":
        caps.append(_cap(dimension_id, "现实背景只是装饰，不影响人物行动", "材料粒度不足以证明主题由行动承载"))
    if dimension_id == "D7":
        if unclosed:
            caps.append(_cap(dimension_id, "核心主线未闭合", "存在未闭合主线问题"))
        if input_profile["episode_count"] < 8:
            caps.append(_cap(dimension_id, "缺少完整结尾材料", "材料不满足 8-12 集完整体量"))
    return caps


def _cap(dimension_id: str, rule: str, reason: str) -> dict:
    return {"rule": rule, "cap": CAP_RULES[dimension_id][rule], "reason": reason}


def _round_b_adjustment(dimension_id: str, related: list[dict]) -> float:
    if not related:
        return 0.0
    return 0.1 if dimension_id in {"D1", "D2", "D3", "D4"} else 0.1


def _checks(definition: dict, related: list[dict]) -> list[dict]:
    has_issues = bool(related)
    checks = []
    for index, check_id in enumerate(definition["checks"], start=1):
        issue = related[(index - 1) % len(related)] if has_issues and index % 3 == 0 else None
        checks.append(
            {
                "check_id": check_id,
                "check_name": f"{definition['name']}检查 {check_id}",
                "result": "部分成立" if issue else "成立",
                "evidence": [issue["trigger_evidence"]] if issue and issue["trigger_evidence"] else [],
                "issue": issue["issue_type"] if issue else "",
            }
        )
    return checks


def _score_reason(name: str, score: float, related: list[dict]) -> str:
    if related:
        names = "、".join(sorted({issue["issue_type"] for issue in related}))
        return f"{name}存在{name and names}等问题，按证据和硬性规则扣分。"
    return f"{name}证据链较完整，未触发明显硬性降分规则。"


def _positive_evidence(dimension_id: str, global_facts: dict) -> list[str]:
    if dimension_id in {"D1", "D4"}:
        return [item["information"] for item in global_facts["information_release"]["information_release"][:5]]
    if dimension_id == "D2":
        return [item["character_name"] for item in global_facts["character_chains"]["characters"][:5]]
    if dimension_id in {"D3", "D5"}:
        return [item["core_event"] for item in global_facts["episode_structure"]["episodes"][:5]]
    if dimension_id == "D6":
        return [item["evidence"] for item in global_facts["scene_functions"]["scene_functions"] if "THEME" in item["function_tags"]][:5]
    return [item["setup_content"] for item in global_facts["setup_payoff_map"]["setup_payoff_map"][:5]]


def _low_score_diagnosis(definition: dict, score: float, related: list[dict], global_facts: dict) -> dict:
    first_issue = related[0] if related else _fallback_issue(global_facts)
    suggestions = _suggestions_for_issue(first_issue["issue_type"])
    return {
        "dimension": definition["id"],
        "dimension_name": definition["name"],
        "score": score,
        "severity": severity_for_score(score),
        "core_problem": first_issue["issue_type"],
        "specific_positions": first_issue["related_positions"] or ["全剧"],
        "evidence": [first_issue["trigger_evidence"]] if first_issue["trigger_evidence"] else [],
        "impact": "会影响追看动力、人物可信度、悬疑公平感或结构闭合，需要优先复核。",
        "revision_suggestions": suggestions,
    }


def _fallback_issue(global_facts: dict) -> dict:
    first_scene = "全剧"
    scenes = global_facts["scene_functions"]["scene_functions"]
    if scenes:
        first_scene = scenes[0]["scene_id"]
    return {
        "issue_type": "证据不足",
        "related_positions": [first_scene],
        "trigger_evidence": "该维度缺少足够结构化证据",
    }


def _suggestions_for_issue(issue_type: str) -> list[str]:
    mapping = {
        "信息释放突兀": ["把关键真相拆成至少 3 个前置线索，分别放入前中后段。", "为每个真相节点补一个人物主动追查动作。"],
        "伏笔未回收": ["删除不服务主线的伏笔，或在结尾前增加明确回收场景。", "把回收位置标注到具体集和场，避免只靠台词解释。"],
        "人物动机断裂": ["在行动前增加目标、压力、利益或情感触发点。", "让行动之后产生关系、风险或局面变化。"],
        "结尾仓促": ["把结尾解释前移，分散到倒数 2-3 集。", "为主线、关系线和主题线分别设置可见回收动作。"],
        "场景功能不明": ["合并只重复信息的场景。", "给保留场景增加信息增量、冲突变化或人物关系变化。"],
    }
    return mapping.get(issue_type, ["补充具体证据节点。", "把抽象问题改写成可执行的集/场修改动作。"])
