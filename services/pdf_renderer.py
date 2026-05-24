"""Render the trip report as Markdown (always) and PDF (best-effort).

Strategy:
  1. Render a Markdown report from the Jinja template — always works.
  2. Try ``weasyprint`` to also produce a PDF. If WeasyPrint or its system
     deps are missing, log a warning and skip PDF gracefully.

Returns the dict ``{"md": <abs path>, "pdf": <abs path | None>}``.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from jinja2 import Environment, FileSystemLoader, select_autoescape

from api.logger import logger

_TEMPLATE_DIR = Path(__file__).parents[1] / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(enabled_extensions=("html", "j2")),
    trim_blocks=False,
    lstrip_blocks=False,
)


def _truthy(v: str | None) -> bool:
    return (v or "").lower() in {"1", "true", "yes", "on"}


def render_markdown(ctx: Dict[str, Any]) -> str:
    template = _env.get_template("trip_report.md.j2")
    return template.render(**ctx)


def _md_to_pdf(md_text: str, pdf_path: Path) -> bool:
    """Best-effort Markdown → HTML → PDF via WeasyPrint."""
    try:
        import markdown
        from weasyprint import CSS, HTML  # type: ignore
    except Exception as e:
        logger.info(f"[pdf] WeasyPrint unavailable, skipping PDF: {e}")
        return False

    try:
        html_body = markdown.markdown(md_text, extensions=["tables", "fenced_code"])
        html = (
            "<!doctype html><html><head><meta charset='utf-8'>"
            "<style>"
            "body{font-family:'Noto Sans CJK SC','PingFang SC','Microsoft YaHei',sans-serif;"
            "padding:24px;color:#222;line-height:1.55;}"
            "h1{border-bottom:2px solid #4E75F6;padding-bottom:6px;}"
            "h2{margin-top:24px;color:#2c3e50;}"
            "table{border-collapse:collapse;width:100%;margin:8px 0;}"
            "th,td{border:1px solid #ddd;padding:6px 8px;font-size:12px;}"
            "th{background:#f0f3ff;}"
            "blockquote{color:#666;border-left:3px solid #ccc;padding-left:8px;}"
            "</style></head><body>"
            f"{html_body}"
            "</body></html>"
        )
        HTML(string=html).write_pdf(str(pdf_path), stylesheets=[CSS(string="@page { size: A4; margin: 18mm; }")])
        return True
    except Exception as e:
        logger.warning(f"[pdf] WeasyPrint render failed: {e}")
        return False


def render_report(
    ctx: Dict[str, Any],
    output_dir: Path,
    version: int,
) -> Dict[str, str | None]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ctx = dict(ctx)
    ctx.setdefault("version", version)
    ctx.setdefault("generated_at", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    ctx.setdefault("mock_mode", _truthy(os.getenv("USE_MOCK_TOOLS", "true")))
    ctx.setdefault("title", f"{ctx.get('destination', '')} {ctx.get('days_num', '')}天行程")

    md_text = render_markdown(ctx)
    md_path = output_dir / f"trip_v{version}.md"
    md_path.write_text(md_text, encoding="utf-8")

    pdf_path = output_dir / f"trip_v{version}.pdf"
    pdf_ok = _md_to_pdf(md_text, pdf_path)

    return {
        "md_path": str(md_path),
        "pdf_path": str(pdf_path) if pdf_ok else None,
    }
