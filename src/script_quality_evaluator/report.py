from __future__ import annotations

from .schemas import LOW_SCORE_THRESHOLD, SCORE_SCALE


def render_report(
    input_profile: dict,
    global_facts: dict,
    issue_candidates: dict,
    calibrated_scores: dict,
    low_score_diagnoses: dict,
    final_score: dict,
) -> str:
    lines = [
        "# 电视剧剧本内容质量评估报告",
        "",
        "## 一、项目基础信息",
        f"- 项目名称：{input_profile['project_name']}",
        f"- 集数：{input_profile['episode_count']}",
        f"- 类型声明：{input_profile['genre_claimed']}",
        f"- 材料类型：{input_profile['material_type']}",
        "",
        "## 二、评估材料说明",
        f"- 完整度：{'完整' if input_profile['is_complete'] else '不完整'}",
        f"- 置信度：{input_profile['confidence_level']}",
        f"- 可评估范围：{'、'.join(input_profile['can_evaluate']) or '无'}",
        f"- 不可评估范围：{'、'.join(input_profile['cannot_evaluate']) or '无'}",
        "",
        "## 三、总分与等级",
        f"- 总分：{final_score['total_score']}",
        f"- 原始等级：{final_score['raw_grade']}",
        f"- 最终等级：{final_score['final_grade']}",
        f"- 风险标记：{'、'.join(final_score['risk_flags']) or '无'}",
        "",
        "## 四、分项评分概览",
    ]
    for item in final_score["dimension_scores"]:
        scale = item.get("score_scale", SCORE_SCALE)
        lines.append(f"- {item['dimension']} {item['dimension_name']}：{item['score']} / {scale}，权重 {item['weight']}，加权 {item['weighted_score']}")

    lines.extend(["", "## 五、核心优点"])
    positives = _positive_points(global_facts)
    lines.extend([f"- {item}" for item in positives] or ["- 当前结构化证据不足以稳定总结核心优点。"])

    lines.extend(["", "## 六、主要问题 Top 5"])
    lines.extend(_issue_lines(final_score["top_issues"]) or ["- 未触发明显 Top 问题。"])

    lines.extend(["", "## 七、低分项专项诊断"])
    diagnoses = low_score_diagnoses["low_score_diagnoses"]
    if diagnoses:
        for diagnosis in diagnoses:
            lines.append(f"- {diagnosis['dimension']} {diagnosis.get('dimension_name', '')}（{diagnosis['score']}）：{diagnosis['core_problem']}；位置：{'、'.join(diagnosis['specific_positions'])}；建议：{'；'.join(diagnosis['revision_suggestions'])}")
    else:
        lines.append(f"- 暂无 {LOW_SCORE_THRESHOLD:.1f} 以下低分项。")

    lines.extend(["", "## 八、分集问题定位"])
    lines.extend(_episode_problem_lines(issue_candidates) or ["- 未发现明确分集级问题候选。"])

    lines.extend(["", "## 九、人物问题定位"])
    lines.extend(_character_problem_lines(issue_candidates) or ["- 未发现明确人物行动链问题候选。"])

    lines.extend(["", "## 十、悬疑机制问题定位"])
    lines.extend(_type_problem_lines(issue_candidates, {"信息释放突兀", "伏笔未回收", "后置硬解释", "单集钩子不足"}) or ["- 未发现明确悬疑机制问题候选。"])

    lines.extend(["", "## 十一、逻辑与因果问题定位"])
    lines.extend(_type_problem_lines(issue_candidates, {"人物动机断裂", "人物行动无后果", "主线推进不明显", "冲突悬置"}) or ["- 未发现明确逻辑与因果问题候选。"])

    lines.extend(["", "## 十二、修改优先级"])
    lines.extend(_revision_priority(final_score, diagnoses))

    lines.extend(["", "## 十三、开发建议"])
    lines.extend(_development_advice(final_score))

    lines.extend(["", "## 十四、置信度与评估限制"])
    lines.append(f"- 本报告基于结构化抽取结果生成，当前置信度为{input_profile['confidence_level']}。")
    risk_notes = input_profile["risk_notes"]
    if isinstance(risk_notes, str):
        lines.append(f"- {risk_notes}")
    elif risk_notes:
        lines.extend([f"- {note}" for note in risk_notes])
    lines.append("- 本系统定位为辅助评估，建议结合人工复核关键证据与创作意图。")
    return "\n".join(lines)


def _positive_points(global_facts: dict) -> list[str]:
    points = []
    if global_facts["information_release"]["information_release"]:
        points.append("已抽取到可追踪的信息释放节点，可支撑悬疑信息控制复核。")
    if global_facts["character_chains"]["characters"]:
        points.append("已形成主要人物行动链，可定位动机、后果和关系变化。")
    if global_facts["setup_payoff_map"]["setup_payoff_map"]:
        points.append("已形成伏笔/回收候选表，可检查悬疑公平性。")
    return points


def _issue_lines(issues: list[dict]) -> list[str]:
    return [
        f"- {issue['issue_id']} {issue['issue_type']}：位置 {'、'.join(issue['related_positions']) or '全剧'}；证据：{issue['trigger_evidence']}"
        for issue in issues
    ]


def _episode_problem_lines(issue_candidates: dict) -> list[str]:
    return _issue_lines([issue for issue in issue_candidates["issue_candidates"] if any(pos.startswith("E") for pos in issue["related_positions"])])


def _character_problem_lines(issue_candidates: dict) -> list[str]:
    return _issue_lines([issue for issue in issue_candidates["issue_candidates"] if issue["related_characters"]])


def _type_problem_lines(issue_candidates: dict, types: set[str]) -> list[str]:
    return _issue_lines([issue for issue in issue_candidates["issue_candidates"] if issue["issue_type"] in types])


def _revision_priority(final_score: dict, diagnoses: list[dict]) -> list[str]:
    if diagnoses:
        return [f"- 优先处理 {item['dimension']}：{item['core_problem']}，先改 {'、'.join(item['specific_positions'])}。" for item in diagnoses[:3]]
    if final_score["top_issues"]:
        return [f"- 优先复核 {issue['issue_type']}：{issue['needs_review']}。" for issue in final_score["top_issues"][:3]]
    return ["- 当前可先做人工复核，再决定是否进入细化改稿。"]


def _development_advice(final_score: dict) -> list[str]:
    total = final_score["total_score"]
    if total < 55:
        return ["- 暂不建议直接进入开发，应先完成核心机制重构。", "- 建议大修：是。", "- 最优先修改：主线闭合、人物行动链、悬疑线索前置。"]
    if total < 60:
        return ["- 可保留题材方向，但不建议立即进入强开发。", "- 建议大修：是。", "- 最优先修改：低分维度对应的前三个具体位置。"]
    if total < 75:
        return ["- 具备继续开发可能，但应先完成结构和人物专项修改。"]
    return ["- 整体具备开发价值，建议围绕 Top 问题做定向优化。"]
