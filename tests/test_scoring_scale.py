from __future__ import annotations

import unittest

from script_quality_evaluator.pipeline import _has_low_scores, _merge_calibrated_into_scores
from script_quality_evaluator.scoring import calibrate_scores, compute_final_score, ensure_low_score_diagnoses
from script_quality_evaluator.schemas import score_band


class ScoringScaleTest(unittest.TestCase):
    def test_compute_final_score_uses_five_point_dimension_scores_for_weighted_total(self) -> None:
        final = compute_final_score(
            [
                {"dimension": "D1", "dimension_name": "悬疑信息控制", "weight": 20, "final_score": 3.5},
                {"dimension": "D2", "dimension_name": "人物行动链", "weight": 20, "final_score": 4.0},
                {"dimension": "D3", "dimension_name": "分集结构与节奏推进", "weight": 20, "final_score": 2.5},
                {"dimension": "D4", "dimension_name": "情节因果与逻辑可信度", "weight": 15, "final_score": 3.0},
                {"dimension": "D5", "dimension_name": "场景戏剧张力与有效密度", "weight": 10, "final_score": 4.5},
                {"dimension": "D6", "dimension_name": "主题表达与现实质感", "weight": 10, "final_score": 3.0},
                {"dimension": "D7", "dimension_name": "结尾回收与整体完成度", "weight": 5, "final_score": 2.0},
            ],
            [],
        )

        self.assertEqual(final["total_score"], 66.0)
        self.assertEqual(final["dimension_scores"][0]["weighted_score"], 14.0)
        self.assertEqual(final["dimension_scores"][0]["score_scale"], 5)

    def test_score_band_uses_five_point_anchors(self) -> None:
        self.assertEqual(score_band(4.6), "4.5-5.0 成熟可开发")
        self.assertEqual(score_band(3.2), "3.0-3.4 勉强可读")
        self.assertEqual(score_band(2.4), "2.0-2.9 关键机制不稳")

    def test_low_score_threshold_is_below_three_on_five_point_scale(self) -> None:
        calibrated = {
            "calibrated_scores": [
                {"dimension": "D1", "final_score": 3.0},
                {"dimension": "D2", "final_score": 2.9},
            ]
        }
        self.assertTrue(_has_low_scores(calibrated))

        merged = _merge_calibrated_into_scores(
            [
                {"dimension": "D1", "low_score_diagnosis": {"score": 2.5}},
                {"dimension": "D2", "low_score_diagnosis": {"score": 2.5}},
            ],
            calibrated["calibrated_scores"],
        )
        self.assertIsNone(merged[0]["low_score_diagnosis"])
        self.assertEqual(merged[1]["low_score_diagnosis"]["score"], 2.9)

        diagnoses = ensure_low_score_diagnoses(
            {"low_score_diagnoses": []},
            calibrated,
            [{"dimension": "D1"}, {"dimension": "D2"}],
            {"scene_functions": {"scene_functions": []}},
        )
        self.assertEqual([item["dimension"] for item in diagnoses["low_score_diagnoses"]], ["D2"])

    def test_calibration_flags_difference_over_ten_percent_of_five_point_scale(self) -> None:
        calibrated = calibrate_scores(
            [{"dimension": "D3", "dimension_name": "分集结构与节奏推进", "weight": 20, "score": 3.5}],
            [{"dimension": "D3", "dimension_name": "分集结构与节奏推进", "weight": 20, "score": 4.3}],
        )

        item = calibrated["calibrated_scores"][0]
        self.assertEqual(item["difference"], 0.8)
        self.assertEqual(item["status"], "需仲裁")
        self.assertEqual(item["final_score"], 3.5)


if __name__ == "__main__":
    unittest.main()
