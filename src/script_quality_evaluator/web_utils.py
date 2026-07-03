from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path


ALLOWED_UPLOAD_SUFFIXES = {".md", ".txt"}


def sanitize_upload_filename(filename: str) -> str:
    path = Path(filename)
    suffix = path.suffix.lower()
    if suffix not in ALLOWED_UPLOAD_SUFFIXES:
        raise ValueError("请上传 .md 或 .txt 格式的剧本文件。")
    stem = safe_name(path.stem)
    return f"{stem}{suffix}"


def make_unique_run_name(output_base: Path, run_name: str) -> str:
    cleaned = safe_name(run_name)
    if not (output_base / cleaned).exists():
        return cleaned
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"{cleaned}_{timestamp}_{uuid.uuid4().hex[:6]}"


def mask_secret(message: object, secret: str | None) -> str:
    text = str(message)
    if secret:
        text = text.replace(secret, "[已隐藏]")
    return text


def safe_name(name: str) -> str:
    cleaned = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", name.strip(), flags=re.UNICODE).strip("._")
    return cleaned or "script"
