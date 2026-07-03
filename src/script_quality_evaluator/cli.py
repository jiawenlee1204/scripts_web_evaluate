from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .pipeline import run_pipeline


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate 8-12 episode suspense scripts.")
    parser.add_argument("--input", default="input/wuxian_episode_script.md", help="Path to raw script or outline markdown.")
    parser.add_argument("--output", default="output", help="Base directory for generated report folders.")
    parser.add_argument("--run-name", default=None, help="Optional folder name under --output for this evaluation run.")
    parser.add_argument("--metadata", default=None, help="Optional metadata.json path.")
    parser.add_argument("--mode", choices=["rules", "llm"], default="llm", help="Use DeepSeek-backed LLM nodes or local rules.")
    parser.add_argument("--prompt-dir", default=None, help="Optional prompt template directory.")
    parser.add_argument("--judge-model", default=None, help="Model for scoring, calibration, diagnosis, and final report.")
    parser.add_argument("--resume", action="store_true", help="Reuse completed LLM node checkpoints from the output directory.")
    parser.add_argument("--rerun-judging", action="store_true", help="With --resume, reuse extraction checkpoints but recompute scoring and reports.")
    args = parser.parse_args(argv)

    try:
        result = run_pipeline(
            Path(args.input),
            Path(args.output),
            Path(args.metadata) if args.metadata else None,
            mode=args.mode,
            prompt_dir=Path(args.prompt_dir) if args.prompt_dir else None,
            judge_model=args.judge_model,
            run_name=args.run_name,
            progress=lambda message: print(f"[进度] {message}", file=sys.stderr, flush=True),
            resume=args.resume,
            rerun_judging=args.rerun_judging,
        )
    except RuntimeError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    final = result["final_score"]
    report_path = Path(result["output_dir"]) / "final_report.md"
    print(f"Mode: {args.mode}")
    print(f"Report files written to {Path(result['output_dir']).resolve()}")
    print(f"Total score: {final['total_score']} ({final['final_grade']})")
    print(f"Report: {report_path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
