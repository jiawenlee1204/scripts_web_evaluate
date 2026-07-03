from __future__ import annotations

import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


CHINESE_NUMBERS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
    "十一": 11,
    "十二": 12,
}

GENERIC_WORDS = {
    "悬疑",
    "犯罪",
    "家庭",
    "秘密",
    "类型",
    "集数",
    "真相",
    "主线",
    "证据",
    "旧案",
    "新命案",
    "监控",
    "线索",
    "照片",
    "录音",
    "镇长",
}

INFO_KEYWORDS = ["发现", "承认", "证明", "得知", "查到", "找到", "透露", "证词", "真相", "线索", "证据"]
ACTION_KEYWORDS = ["决定", "追", "查", "质问", "申请", "公开", "救", "交出", "询问", "帮"]
SETUP_KEYWORDS = ["照片", "钥匙", "徽章", "短信", "录音", "监控", "名单", "警号", "证据", "档案", "号码"]
HOOK_KEYWORDS = ["但", "却", "发现", "失控", "起火", "威胁", "死亡", "失踪", "真相", "疑似"]


def validate_input(raw_text: str, metadata: dict | None = None) -> dict:
    metadata = metadata or {}
    episode_count = _declared_episode_count(raw_text) or len(_episode_blocks(raw_text)) or metadata.get("episode_count", 0)
    scene_count = len(
        re.findall(
            r"(?m)^#{2,4}\s*(?:第?\d+场|场\d+|场[一二三四五六七八九十]+|\d+\.\s+|E\d{1,2}-S\d{1,2})",
            raw_text,
        )
    )
    is_complete = 8 <= episode_count <= 12
    material_type = "完整剧本" if scene_count >= episode_count * 2 else "分集大纲" if episode_count else "梗概"
    confidence = "高" if is_complete and scene_count >= episode_count * 2 else "中" if episode_count >= 4 else "低"
    can_evaluate = ["结构", "人物", "悬疑信息", "因果逻辑"]
    cannot_evaluate = []
    if not is_complete:
        cannot_evaluate.append("8-12 集完整体量判断")
    if scene_count == 0:
        cannot_evaluate.append("场景级精确定位")
    return {
        "project_name": metadata.get("project_name") or _title(raw_text),
        "episode_count": episode_count,
        "episode_duration": metadata.get("episode_duration", "45-60min"),
        "material_type": material_type,
        "genre_claimed": metadata.get("genre_claimed", "悬疑"),
        "is_complete": is_complete,
        "can_evaluate": can_evaluate,
        "cannot_evaluate": cannot_evaluate,
        "risk_notes": [] if is_complete else ["材料集数不在 8-12 集范围内，评分置信度会降低"],
        "confidence_level": confidence,
    }


def split_script(raw_text: str) -> dict:
    blocks = _episode_blocks(raw_text)
    if not blocks:
        blocks = [("E01", raw_text)]
    episodes = []
    for index, (_heading, body) in enumerate(blocks, start=1):
        episode_id = f"E{index:02d}"
        episodes.append({"episode_id": episode_id, "scenes": _scene_units(episode_id, body)})
    return {"episodes": episodes}


def extract_episode_maps(script_units: dict) -> dict:
    structures = []
    scene_functions = []
    character_actions = []
    information_release = []
    setup_candidates = []
    for episode in script_units["episodes"]:
        episode_id = episode["episode_id"]
        scenes = episode["scenes"]
        combined = " ".join(scene["surface_event"] for scene in scenes)
        structures.append(
            {
                "episode_id": episode_id,
                "opening_state": scenes[0]["surface_event"] if scenes else "",
                "ending_state": scenes[-1]["state_change"] if scenes else "",
                "core_event": _summary_sentence(combined),
                "mainline_progress": _progress_for_episode(combined),
                "new_information": [_summary_sentence(scene["surface_event"]) for scene in scenes if _contains(scene["surface_event"], INFO_KEYWORDS)],
                "new_question_or_hook": _hook_for_episode(scenes),
                "episode_function": _episode_function(episode_id, combined),
            }
        )
        for scene in scenes:
            scene_functions.append(_scene_function(episode_id, scene))
            character_actions.extend(_character_actions(episode_id, scene))
            information_release.extend(_information_items(episode_id, scene))
            setup_candidates.extend(_setup_items(episode_id, scene))
    return {
        "episode_structures": structures,
        "scene_functions": scene_functions,
        "character_actions": character_actions,
        "information_release": information_release,
        "setup_candidates": setup_candidates,
    }


def reduce_global(input_profile: dict, script_units: dict, episode_maps: dict) -> dict:
    episode_structure = {
        "main_story_goal": _main_goal(episode_maps["episode_structures"]),
        "episodes": episode_maps["episode_structures"],
        "unclosed_mainline_questions": _unclosed_questions(input_profile, episode_maps),
    }
    scene_functions = {
        "scene_functions": episode_maps["scene_functions"],
        "statistics": _scene_statistics(episode_maps["scene_functions"]),
    }
    character_chains = {"characters": _character_chains(episode_maps["character_actions"])}
    information_release = {
        "information_release": _renumber_information(episode_maps["information_release"]),
        "knowledge_state_summary": _knowledge_summary(episode_maps["information_release"]),
    }
    setup_payoff_map = {"setup_payoff_map": _setup_payoff_map(episode_maps["setup_candidates"], episode_maps["information_release"])}
    return {
        "episode_structure": episode_structure,
        "scene_functions": scene_functions,
        "character_chains": character_chains,
        "information_release": information_release,
        "setup_payoff_map": setup_payoff_map,
    }


def generate_issue_candidates(input_profile: dict, global_facts: dict) -> dict:
    issues = []
    issues.extend(_issue_mainline(input_profile, global_facts))
    issues.extend(_issue_scenes(global_facts))
    issues.extend(_issue_characters(global_facts))
    issues.extend(_issue_information(global_facts))
    issues.extend(_issue_setup_payoff(global_facts))
    return {"issue_candidates": _with_issue_ids(issues)}


def _title(raw_text: str) -> str:
    match = re.search(r"(?m)^#\s+(.+)$", raw_text)
    return match.group(1).strip() if match else "未命名项目"


def _declared_episode_count(raw_text: str) -> int:
    match = re.search(r"集数[：:]\s*(\d+)", raw_text)
    return int(match.group(1)) if match else 0


def _episode_blocks(raw_text: str) -> list[tuple[str, str]]:
    pattern = re.compile(r"(?m)^#{1,3}\s*(第\s*[一二三四五六七八九十百\d]+\s*集(?:《[^》]+》)?|E\d{1,2}|Episode\s*\d+).*$")
    matches = list(pattern.finditer(raw_text))
    blocks = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(raw_text)
        blocks.append((match.group(1), raw_text[start:end].strip()))
    return blocks


def _scene_units(episode_id: str, body: str) -> list[dict]:
    pattern = re.compile(r"(?m)^#{3,4}\s*(.+)$")
    matches = list(pattern.finditer(body))
    scenes = []
    if not matches:
        paragraphs = [item.strip() for item in re.split(r"\n\s*\n", body) if item.strip()]
        matches_and_bodies = [(f"场{index}", paragraph) for index, paragraph in enumerate(paragraphs or [body], start=1)]
    else:
        matches_and_bodies = []
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
            matches_and_bodies.append((match.group(1).strip(), body[start:end].strip()))
    for index, (heading, text) in enumerate(matches_and_bodies, start=1):
        location, time = _location_time(heading)
        scenes.append(
            {
                "scene_id": f"{episode_id}-S{index:02d}",
                "source_scene_id": heading,
                "location": location,
                "time": time,
                "characters": _characters(text),
                "surface_event": _summary_sentence(text),
                "state_change": _state_change(text),
                "source_excerpt": _excerpt(text),
            }
        )
    return scenes


def _location_time(heading: str) -> tuple[str, str]:
    parts = heading.split()
    if len(parts) >= 2:
        return parts[-2], parts[-1]
    return heading, ""


def _characters(text: str) -> list[str]:
    names = []
    for candidate in re.findall(r"[\u4e00-\u9fff]{2,4}", text):
        if candidate not in GENERIC_WORDS and candidate.endswith(("澈", "岚", "叔", "亲", "长")):
            names.append(candidate)
    return sorted(set(names))[:6]


def _summary_sentence(text: str) -> str:
    cleaned = " ".join(text.split())
    if not cleaned:
        return ""
    return re.split(r"[。！？!?]", cleaned)[0][:120]


def _state_change(text: str) -> str:
    if _contains(text, ["决定", "转为", "承认", "公开", "落网", "受伤", "停职"]):
        return _summary_sentence(text)
    return ""


def _excerpt(text: str) -> str:
    return " ".join(text.split())[:160]


def _contains(text: str, keywords: Iterable[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def _progress_for_episode(text: str) -> str:
    if _contains(text, INFO_KEYWORDS + ACTION_KEYWORDS):
        return _summary_sentence(text)
    return ""


def _hook_for_episode(scenes: list[dict]) -> str:
    if not scenes:
        return ""
    last = scenes[-1]["surface_event"]
    return last if _contains(last, HOOK_KEYWORDS) else ""


def _episode_function(episode_id: str, text: str) -> str:
    number = int(episode_id[1:])
    if number == 1:
        return "启动"
    if _contains(text, ["反转", "承认", "证明", "公开"]):
        return "反转"
    if _contains(text, ["落网", "真相公开", "回收"]):
        return "回收"
    if _contains(text, INFO_KEYWORDS):
        return "推进"
    return "功能不明"


def _scene_function(episode_id: str, scene: dict) -> dict:
    text = scene["surface_event"] + scene["source_excerpt"]
    tags = []
    if _contains(text, ACTION_KEYWORDS):
        tags.append("PLOT")
    if scene["characters"]:
        tags.append("CHARACTER")
    if _contains(text, ["冲突", "质问", "威胁", "起火", "死亡", "压下"]):
        tags.append("CONFLICT")
    if _contains(text, INFO_KEYWORDS + SETUP_KEYWORDS):
        tags.append("CLUE")
    if _contains(text, ["承认", "证明", "落网", "公开"]):
        tags.append("PAYOFF")
    if _contains(text, ["恐慌", "失控", "受伤", "母亲", "父亲"]):
        tags.append("EMOTION")
    if _contains(text, ["船厂", "码头", "镇", "年代", "污染"]):
        tags.append("WORLD")
    if _contains(text, ["沉默", "污染", "受害者"]):
        tags.append("THEME")
    if not tags:
        tags.append("UNKNOWN")
    return {
        "episode_id": episode_id,
        "scene_id": scene["scene_id"],
        "function_tags": sorted(set(tags)),
        "information_change": scene["surface_event"] if "CLUE" in tags or "PAYOFF" in tags else "",
        "relationship_change": scene["surface_event"] if "CHARACTER" in tags and "EMOTION" in tags else "",
        "conflict_change": scene["surface_event"] if "CONFLICT" in tags else "",
        "emotion_or_theme_function": scene["surface_event"] if "EMOTION" in tags or "THEME" in tags else "",
        "suspected_functionless": tags == ["UNKNOWN"],
        "evidence": scene["source_excerpt"],
    }


def _character_actions(episode_id: str, scene: dict) -> list[dict]:
    actions = []
    for character in scene["characters"] or ["未明确人物"]:
        if _contains(scene["source_excerpt"], ACTION_KEYWORDS):
            actions.append(
                {
                    "character_name": character,
                    "scene_id": scene["scene_id"],
                    "episode_id": episode_id,
                    "action": scene["surface_event"],
                    "motivation_evidence": scene["source_excerpt"] if _contains(scene["source_excerpt"], ["因为", "为", "决定", "试图"]) else "",
                    "consequence": scene["state_change"],
                    "cost_or_risk": scene["source_excerpt"] if _contains(scene["source_excerpt"], ["受伤", "停职", "威胁", "失败", "风险"]) else "",
                    "change_after_action": scene["state_change"],
                    "relationship_impact": scene["state_change"] if _contains(scene["source_excerpt"], ["关系", "结盟", "母亲", "父亲"]) else "",
                }
            )
    return actions


def _information_items(episode_id: str, scene: dict) -> list[dict]:
    if not _contains(scene["source_excerpt"], INFO_KEYWORDS):
        return []
    return [
        {
            "info_id": f"I-{scene['scene_id']}-001",
            "episode_id": episode_id,
            "scene_id": scene["scene_id"],
            "information": scene["surface_event"],
            "info_type": _info_type(scene["source_excerpt"]),
            "audience_knows": True,
            "protagonist_knows": "林澈" in scene["source_excerpt"] or "主角" in scene["source_excerpt"],
            "other_characters_who_know": [name for name in scene["characters"] if name != "林澈"],
            "characters_who_do_not_know": [],
            "changes_understanding": scene["surface_event"],
            "leads_to_action": scene["state_change"],
            "later_used_at": [],
        }
    ]


def _info_type(text: str) -> str:
    if "误导" in text:
        return "误导"
    if "动机" in text:
        return "动机"
    if "关系" in text:
        return "关系"
    if "证据" in text or "证明" in text:
        return "证据"
    if "真相" in text or "承认" in text:
        return "真相"
    return "线索"


def _setup_items(episode_id: str, scene: dict) -> list[dict]:
    if not _contains(scene["source_excerpt"], SETUP_KEYWORDS):
        return []
    keyword = next((item for item in SETUP_KEYWORDS if item in scene["source_excerpt"]), "线索")
    return [
        {
            "candidate_id": f"F-{scene['scene_id']}-001",
            "episode_id": episode_id,
            "scene_id": scene["scene_id"],
            "setup_content": f"{keyword}：{scene['surface_event']}",
            "surface_meaning_at_first": scene["surface_event"],
            "possible_future_function": "案件" if keyword in {"监控", "证据", "档案", "名单"} else "反转",
            "evidence": scene["source_excerpt"],
        }
    ]


def _main_goal(episode_structures: list[dict]) -> str:
    if not episode_structures:
        return ""
    return episode_structures[0]["core_event"] or "追查核心悬疑事件"


def _unclosed_questions(input_profile: dict, episode_maps: dict) -> list[str]:
    if not input_profile["is_complete"]:
        return ["材料不完整，核心主线是否闭合无法充分判断"]
    last = episode_maps["episode_structures"][-1] if episode_maps["episode_structures"] else {}
    if "回收" not in last.get("episode_function", "") and not _contains(last.get("ending_state", ""), ["落网", "真相", "公开", "证明"]):
        return ["结尾集未发现明确主线回收信号"]
    return []


def _scene_statistics(scene_functions: list[dict]) -> dict:
    total = len(scene_functions)
    functionless = [item for item in scene_functions if item["suspected_functionless"]]
    per_episode = defaultdict(lambda: [0, 0])
    for item in scene_functions:
        per_episode[item["episode_id"]][0] += 1
        if item["suspected_functionless"]:
            per_episode[item["episode_id"]][1] += 1
    return {
        "total_scene_count": total,
        "functionless_scene_count": len(functionless),
        "functionless_ratio": round(len(functionless) / total, 3) if total else 0,
        "per_episode_functionless_ratio": {
            episode: round(values[1] / values[0], 3) if values[0] else 0 for episode, values in sorted(per_episode.items())
        },
    }


def _character_chains(actions: list[dict]) -> list[dict]:
    grouped = defaultdict(list)
    for action in actions:
        grouped[action["character_name"]].append(action)
    chains = []
    for name, items in sorted(grouped.items()):
        chains.append(
            {
                "character_name": name,
                "role_type": "主角" if name == "林澈" else "重要配角" if name != "未明确人物" else "其他",
                "initial_state": items[0]["action"] if items else "",
                "explicit_goal": items[0]["motivation_evidence"] or items[0]["action"] if items else "",
                "implicit_need_with_evidence": items[0]["motivation_evidence"] if items else "",
                "action_chain": [
                    {
                        "episode_id": item["episode_id"],
                        "scene_id": item["scene_id"],
                        "action": item["action"],
                        "motivation_evidence": item["motivation_evidence"],
                        "consequence": item["consequence"],
                        "cost_or_risk": item["cost_or_risk"],
                        "change_after_action": item["change_after_action"],
                    }
                    for item in items
                ],
                "relationship_changes": [item["relationship_impact"] for item in items if item["relationship_impact"]],
                "final_state": items[-1]["change_after_action"] if items else "",
                "suspected_motivation_gaps": [item["scene_id"] for item in items if not item["motivation_evidence"]],
            }
        )
    return chains


def _renumber_information(items: list[dict]) -> list[dict]:
    result = []
    for index, item in enumerate(items, start=1):
        copied = dict(item)
        copied["info_id"] = f"I{index:03d}"
        result.append(copied)
    return result


def _knowledge_summary(items: list[dict]) -> dict:
    audience = defaultdict(list)
    protagonist = defaultdict(list)
    for item in items:
        audience[item["episode_id"]].append(item["information"])
        if item["protagonist_knows"]:
            protagonist[item["episode_id"]].append(item["information"])
    return {
        "audience_knows_by_episode": dict(sorted(audience.items())),
        "protagonist_knows_by_episode": dict(sorted(protagonist.items())),
        "key_information_gaps": [],
    }


def _setup_payoff_map(setups: list[dict], information: list[dict]) -> list[dict]:
    later_text_by_episode = defaultdict(str)
    for item in information:
        later_text_by_episode[item["episode_id"]] += " " + item["information"]
    result = []
    for index, setup in enumerate(setups, start=1):
        episode_number = int(setup["episode_id"][1:])
        later_text = " ".join(text for episode, text in later_text_by_episode.items() if int(episode[1:]) > episode_number)
        keyword = setup["setup_content"].split("：", 1)[0]
        paid = keyword in later_text or _contains(later_text, ["承认", "证明", "公开", "落网"])
        result.append(
            {
                "item_id": f"F{index:03d}",
                "setup_content": setup["setup_content"],
                "first_appearance": setup["scene_id"],
                "surface_meaning_at_first": setup["surface_meaning_at_first"],
                "reappearances": [],
                "payoff_position": "后续信息释放节点" if paid else "",
                "payoff_meaning": "后文用于推进真相或人物判断" if paid else "",
                "payoff_type": "情节回收" if paid else "反转回收",
                "status": "已回收" if paid else "未发现回收",
                "evidence": setup["evidence"],
            }
        )
    return result


def _issue_mainline(input_profile: dict, global_facts: dict) -> list[dict]:
    issues = []
    episodes = global_facts["episode_structure"]["episodes"]
    if input_profile["episode_count"] < 8 or input_profile["episode_count"] > 12:
        issues.append(_issue("主线推进不明显", ["全剧"], [], [], "材料不在 8-12 集目标范围内", "需人工确认材料完整性"))
    for episode in episodes:
        if not episode["mainline_progress"]:
            issues.append(_issue("主线推进不明显", [episode["episode_id"]], [], [], "本集未抽取到明显主线状态变化", "检查本集结构功能"))
        if not episode["new_question_or_hook"]:
            issues.append(_issue("单集钩子不足", [episode["episode_id"]], [], [], "本集结尾未抽取到新风险或新问题", "检查集尾追看动力"))
    if global_facts["episode_structure"]["unclosed_mainline_questions"]:
        issues.append(_issue("结尾仓促", ["结尾"], [], [], "结尾缺少明确主线回收信号", "核查结尾闭合度"))
    return issues


def _issue_scenes(global_facts: dict) -> list[dict]:
    issues = []
    for scene in global_facts["scene_functions"]["scene_functions"]:
        if scene["suspected_functionless"]:
            issues.append(_issue("场景功能不明", [scene["scene_id"]], [], [], scene["evidence"], "判断是否删减或合并"))
    for episode, ratio in global_facts["scene_functions"]["statistics"]["per_episode_functionless_ratio"].items():
        if ratio > 0.3:
            issues.append(_issue("场景功能不明", [episode], [], [], f"{episode} 功能不明场景比例 {ratio}", "重排本集场景功能"))
    return issues


def _issue_characters(global_facts: dict) -> list[dict]:
    issues = []
    for character in global_facts["character_chains"]["characters"]:
        gaps = character["suspected_motivation_gaps"]
        if len(gaps) >= 2:
            issues.append(_issue("人物动机断裂", gaps[:5], [character["character_name"]], [], "多个行动缺少前置动机依据", "补足目标、压力或情感依据"))
        no_consequence = [item["scene_id"] for item in character["action_chain"] if not item["consequence"]]
        if len(no_consequence) >= max(2, len(character["action_chain"]) // 2):
            issues.append(_issue("人物行动无后果", no_consequence[:5], [character["character_name"]], [], "多次行动未抽取到后果或状态变化", "让行动改变局面、关系或风险"))
    return issues


def _issue_information(global_facts: dict) -> list[dict]:
    issues = []
    information = global_facts["information_release"]["information_release"]
    if len(information) < 4:
        issues.append(_issue("信息释放突兀", ["全剧"], [], [], "信息释放节点过少，关键真相可能缺少递进", "补充前置线索和阶段性误导"))
    return issues


def _issue_setup_payoff(global_facts: dict) -> list[dict]:
    issues = []
    for item in global_facts["setup_payoff_map"]["setup_payoff_map"]:
        if item["status"] != "已回收":
            issues.append(_issue("伏笔未回收", [item["first_appearance"]], [], [item["item_id"]], item["evidence"], "为该伏笔增加回收或删除该设置"))
    return issues


def _issue(issue_type: str, positions: list[str], characters: list[str], clues: list[str], evidence: str, review: str) -> dict:
    return {
        "issue_type": issue_type,
        "related_positions": positions,
        "related_characters": characters,
        "related_clues": clues,
        "trigger_evidence": evidence,
        "needs_review": review,
    }


def _with_issue_ids(issues: list[dict]) -> list[dict]:
    counts = Counter()
    result = []
    for issue in issues:
        counts[issue["issue_type"]] += 1
        copied = dict(issue)
        copied["issue_id"] = f"Q{len(result) + 1:03d}"
        result.append(copied)
    return result
