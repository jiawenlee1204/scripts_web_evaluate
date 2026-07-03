from __future__ import annotations

DIMENSIONS = [
    {
        "id": "D1",
        "name": "悬疑信息控制",
        "weight": 20,
        "checks": ["S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8"],
    },
    {
        "id": "D2",
        "name": "人物行动链",
        "weight": 20,
        "checks": ["C1", "C2", "C3", "C4", "C5", "C6", "C7", "C8"],
    },
    {
        "id": "D3",
        "name": "分集结构与节奏推进",
        "weight": 20,
        "checks": ["E1", "E2", "E3", "E4", "E5", "E6", "E7", "E8"],
    },
    {
        "id": "D4",
        "name": "情节因果与逻辑可信度",
        "weight": 15,
        "checks": ["L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8"],
    },
    {
        "id": "D5",
        "name": "场景戏剧张力与有效密度",
        "weight": 10,
        "checks": ["SCE1", "SCE2", "SCE3", "SCE4", "SCE5", "SCE6", "SCE7", "SCE8"],
    },
    {
        "id": "D6",
        "name": "主题表达与现实质感",
        "weight": 10,
        "checks": ["T1", "T2", "T3", "T4", "T5", "T6", "T7", "T8"],
    },
    {
        "id": "D7",
        "name": "结尾回收与整体完成度",
        "weight": 5,
        "checks": ["END1", "END2", "END3", "END4", "END5", "END6", "END7", "END8"],
    },
]

DIMENSION_BY_ID = {item["id"]: item for item in DIMENSIONS}

SCORE_SCALE = 5
LOW_SCORE_THRESHOLD = 3.0
SCORE_STABILITY_TOLERANCE = 0.5

FUNCTION_TAGS = {
    "PLOT",
    "CHARACTER",
    "CONFLICT",
    "CLUE",
    "PAYOFF",
    "EMOTION",
    "WORLD",
    "THEME",
    "TRANSITION",
    "UNKNOWN",
}

GRADE_ORDER = ["A", "B", "C", "D", "E"]

ISSUE_TO_DIMENSION = {
    "主线推进不明显": ["D3", "D4"],
    "场景功能不明": ["D3", "D5"],
    "场景功能重复": ["D5"],
    "人物动机断裂": ["D2", "D4"],
    "人物行动无后果": ["D2", "D5"],
    "冲突悬置": ["D3", "D4"],
    "信息释放突兀": ["D1", "D4"],
    "伏笔未回收": ["D1", "D7"],
    "后置硬解释": ["D1", "D4", "D7"],
    "单集钩子不足": ["D1", "D3"],
    "支线悬空": ["D3", "D7"],
    "主题直给": ["D6"],
    "结尾仓促": ["D3", "D7"],
}

CAP_RULES = {
    "D1": {
        "核心谜题不清晰启动": 3.2,
        "关键真相无前置线索": 2.7,
        "结尾主要靠新人物/新证据解释": 2.5,
        "连续两集无有效信息增量": 3.5,
        "核心谜题未完成回收": 2.5,
    },
    "D2": {
        "主角没有可追踪外部目标": 2.5,
        "2 个以上关键行动无前置动机依据": 2.7,
        "多数关键行动没有后果或代价": 3.0,
        "主要人物结尾状态与初始状态无明显差异": 3.0,
        "没有完整结尾": 3.2,
    },
    "D3": {
        "前 2 集未清晰启动主线": 3.2,
        "超过 2 集结构功能不明": 3.0,
        "连续两集没有有效结尾钩子": 3.5,
        "某一集超过 30% 场景功能不明": 3.0,
        "核心主线未回收": 2.5,
    },
    "D4": {
        "核心真相依赖后置补丁解释": 2.5,
        "主线关键节点主要靠巧合推动": 2.7,
        "人物行为与其已知信息明显矛盾": 3.0,
        "关键反转缺少前置条件": 2.7,
    },
    "D5": {
        "某一集超过 30% 场景功能不明": 3.0,
        "多场戏重复释放同一信息，且无新变化": 3.2,
        "场景普遍只有对白解释，没有局面变化": 2.7,
    },
    "D6": {
        "主题主要靠台词口号表达": 3.0,
        "案件/悬疑线与主题线明显脱节": 3.2,
        "现实背景只是装饰，不影响人物行动": 3.2,
    },
    "D7": {
        "核心主线未闭合": 2.5,
        "关键真相未解释": 2.5,
        "结尾主要靠集中口述解释": 3.0,
        "缺少完整结尾材料": 3.0,
    },
}


def score_band(score: float) -> str:
    if score >= 4.5:
        return "4.5-5.0 成熟可开发"
    if score >= 4:
        return "4.0-4.4 整体成立"
    if score >= 3.5:
        return "3.5-3.9 成立但有明确修改点"
    if score >= 3:
        return "3.0-3.4 勉强可读"
    if score >= 2:
        return "2.0-2.9 关键机制不稳"
    if score >= 1:
        return "1.0-1.9 大面积失效"
    return "0-0.9 基本不成立"


def grade_for_total(total_score: float) -> str:
    if total_score >= 85:
        return "A"
    if total_score >= 75:
        return "B"
    if total_score >= 65:
        return "C"
    if total_score >= 55:
        return "D"
    return "E"


def cap_grade(grade: str, max_grade: str) -> str:
    return grade if GRADE_ORDER.index(grade) >= GRADE_ORDER.index(max_grade) else max_grade
