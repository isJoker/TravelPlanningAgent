"""Render the trip report as Markdown (always) and PDF (best-effort, multi-engine).

Strategy (inspired by ``isJoker/DeepSearchResearcher`` ``convert_md_to_pdf_real``):
the previous implementation only tried WeasyPrint, which is unreliable on macOS
because the native deps (cairo / pango / gdk-pixbuf) are not installed by default.
This refactor auto-selects the best available engine for the current platform:

  - Windows:        word_com  -> pandoc(+xelatex)  -> weasyprint
  - macOS / Linux:  pandoc(+xelatex)               -> weasyprint

Each engine is gracefully skipped when its dependencies are missing, with a
clear log message; the function always returns a Markdown file and only a PDF
when at least one engine succeeded.

The public entry point ``render_report(ctx, output_dir, version)`` and its
return shape ``{"md_path": str, "pdf_path": str | None}`` are unchanged so
existing callers in ``agent/nodes.py`` are not affected.

Engine selection can be forced via the ``PDF_ENGINE`` env var
(``word`` | ``pandoc`` | ``weasyprint``).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

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


# ============================================================
#  Platform & dependency detection
# ============================================================

def _is_windows() -> bool:
    return sys.platform == "win32"


def _is_macos() -> bool:
    return sys.platform == "darwin"


def _is_linux() -> bool:
    return sys.platform.startswith("linux")


def _check_pandoc_available() -> bool:
    return shutil.which("pandoc") is not None


def _check_xelatex_available() -> bool:
    return shutil.which("xelatex") is not None


def _check_markdown_available() -> bool:
    try:
        import markdown  # noqa: F401
        return True
    except ImportError:
        return False


def _check_weasyprint_available() -> bool:
    try:
        import weasyprint  # noqa: F401
        return True
    except Exception:
        # WeasyPrint can fail at import time on macOS when its native deps
        # (cairo / pango / gdk-pixbuf) are missing - treat as unavailable.
        return False


def _check_win32com_available() -> bool:
    if not _is_windows():
        return False
    try:
        import pythoncom  # noqa: F401
        import win32com.client  # noqa: F401
        return True
    except ImportError:
        return False


# ============================================================
#  Engine 1: Microsoft Word COM (Windows only, highest quality)
# ============================================================

def _convert_with_word_com(md_path: Path, pdf_path: Path) -> Tuple[bool, str]:
    if not _is_windows():
        return False, "Word COM 引擎仅支持 Windows 平台"
    if not _check_win32com_available():
        return False, "缺少 pywin32 依赖，请执行: pip install pywin32"
    if not _check_markdown_available():
        return False, "缺少 markdown 依赖，请执行: pip install markdown"

    import markdown
    import pythoncom
    import win32com.client

    temp_html_path = md_path.with_suffix(".temp.html")
    word_app = None
    try:
        md_content = md_path.read_text(encoding="utf-8")
        html_body = markdown.markdown(md_content, extensions=["tables", "fenced_code"])
        html_content = (
            "<html><head><meta charset='UTF-8'>"
            "<style>"
            "body{font-family:'Microsoft YaHei','SimHei','Segoe UI',sans-serif;margin:2em;}"
            "table{border-collapse:collapse;width:100%;}"
            "th,td{border:1px solid #ccc;padding:8px;text-align:left;}"
            "th{background:#f2f2f2;}"
            "pre{background:#f5f5f5;padding:10px;border-radius:4px;overflow-x:auto;}"
            "code{font-family:'Consolas','Monaco',monospace;}"
            "blockquote{border-left:4px solid #ddd;margin:0;padding-left:1em;color:#666;}"
            "img{max-width:100%;}"
            "</style></head><body>"
            f"{html_body}"
            "</body></html>"
        )
        temp_html_path.write_text(html_content, encoding="utf-8")

        pythoncom.CoInitialize()
        word_app = win32com.client.Dispatch("Word.Application")
        word_app.Visible = False
        word_app.DisplayAlerts = False
        doc = word_app.Documents.Open(str(temp_html_path.resolve()))
        # FileFormat=17 is wdFormatPDF
        doc.SaveAs(str(pdf_path.resolve()), FileFormat=17)
        doc.Close(SaveChanges=0)

        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            return True, f"成功转换 (Word COM 引擎): {pdf_path}"
        return False, f"转换完成但未生成有效 PDF 文件: {pdf_path}"
    except Exception as e:
        logger.error(f"[Word COM] 转换失败: {e}")
        return False, f"Word COM 转换失败: {e}"
    finally:
        if word_app is not None:
            try:
                word_app.Quit()
            except Exception:
                pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass
        if temp_html_path.exists():
            try:
                temp_html_path.unlink()
            except Exception:
                pass


# ============================================================
#  Engine 2: pandoc + xelatex (macOS / Linux / Windows, recommended)
# ============================================================

def _convert_with_pandoc(md_path: Path, pdf_path: Path) -> Tuple[bool, str]:
    if not _check_pandoc_available():
        return False, (
            "未检测到 pandoc。安装方式：macOS: `brew install pandoc`; "
            "Linux: `apt install pandoc`; Windows: 安装 pandoc 官方包。"
        )
    if not _check_xelatex_available():
        return False, (
            "未检测到 xelatex。安装方式：macOS: `brew install --cask mactex`; "
            "Linux: `sudo apt install texlive-xetex`; Windows: 安装 MiKTeX 或 TeX Live。"
        )

    cmd = [
        "pandoc",
        str(md_path),
        "-o", str(pdf_path),
        "--pdf-engine=xelatex",
        "-V", "geometry:margin=1in",
        "-V", "mainfont=Helvetica",
        "-V", "CJKmainfont=PingFang SC",
        "-V", "fontsize=12pt",
        "--highlight-style=tango",
    ]
    if _is_linux():
        # Override CJK font for Linux where PingFang SC is not present.
        cmd[-3] = "CJKmainfont=Noto Sans CJK SC"

    try:
        logger.info(f"[pandoc] {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            err = result.stderr.strip() or "未知错误"
            return False, f"pandoc 转换失败: {err}"
        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            return True, f"成功转换 (pandoc + xelatex): {pdf_path}"
        return False, "转换完成但未生成有效 PDF 文件"
    except subprocess.TimeoutExpired:
        return False, "pandoc 转换超时（>60s）"
    except FileNotFoundError:
        return False, "未找到 pandoc 可执行文件"
    except Exception as e:
        logger.error(f"[pandoc] 异常: {e}")
        return False, f"pandoc 转换异常: {e}"


# ============================================================
#  Engine 3: WeasyPrint (pure-Python fallback)
# ============================================================

def _convert_with_weasyprint(md_path: Path, pdf_path: Path) -> Tuple[bool, str]:
    if not _check_markdown_available():
        return False, "缺少 markdown 依赖，请执行: pip install markdown"
    if not _check_weasyprint_available():
        return False, (
            "缺少 weasyprint 依赖或其原生库。安装方式：pip install weasyprint，"
            "macOS 还需 `brew install pango cairo gdk-pixbuf libffi`。"
        )

    try:
        import markdown
        from weasyprint import CSS, HTML
        from weasyprint.text.fonts import FontConfiguration

        md_content = md_path.read_text(encoding="utf-8")
        html_body = markdown.markdown(
            md_content, extensions=["tables", "fenced_code", "nl2br"]
        )

        if _is_macos():
            font_families = ["PingFang SC", "Helvetica Neue", "Helvetica"]
        elif _is_linux():
            font_families = ["Noto Sans CJK SC", "WenQuanYi Micro Hei", "sans-serif"]
        else:
            font_families = ["Microsoft YaHei", "SimHei", "Segoe UI"]
        font_family = ", ".join(f'"{f}"' for f in font_families)

        css_style = f"""
        @page {{ size: A4; margin: 2cm; }}
        body {{ font-family: {font_family}; line-height: 1.6; color: #333; }}
        h1, h2, h3, h4, h5, h6 {{ margin-top: 1.5em; margin-bottom: 0.5em; font-weight: 600; }}
        h1 {{ border-bottom: 2px solid #4E75F6; padding-bottom: 6px; }}
        table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; font-size: 12px; }}
        th {{ background-color: #f0f3ff; }}
        pre {{ background-color: #f5f5f5; padding: 12px; border-radius: 6px; overflow-x: auto; }}
        code {{ font-family: "Courier New", "Consolas", monospace; }}
        blockquote {{ border-left: 4px solid #ddd; margin: 0; padding-left: 1em; color: #666; }}
        img {{ max-width: 100%; }}
        """

        html_content = (
            "<!DOCTYPE html><html><head><meta charset='UTF-8'>"
            f"<title>{md_path.stem}</title></head><body>"
            f"{html_body}"
            "</body></html>"
        )

        font_config = FontConfiguration()
        HTML(string=html_content).write_pdf(
            str(pdf_path),
            stylesheets=[CSS(string=css_style, font_config=font_config)],
            font_config=font_config,
        )

        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            return True, f"成功转换 (WeasyPrint 引擎): {pdf_path}"
        return False, "转换完成但未生成有效 PDF 文件"
    except Exception as e:
        logger.error(f"[WeasyPrint] 转换失败: {e}")
        return False, f"WeasyPrint 转换失败: {e}"


# ============================================================
#  Orchestrator: auto-select best engine for the platform
# ============================================================

_ENGINES = {
    "word": _convert_with_word_com,
    "pandoc": _convert_with_pandoc,
    "weasyprint": _convert_with_weasyprint,
}


def convert_md_to_pdf(
    md_path: Path,
    pdf_path: Optional[Path] = None,
    engine: Optional[str] = None,
) -> Tuple[bool, str]:
    """Cross-platform Markdown → PDF with automatic engine fallback.

    ``engine`` may be forced via argument or the ``PDF_ENGINE`` env var; when
    omitted, engines are tried in platform-appropriate priority order.
    """
    md_path = Path(md_path)
    if not md_path.exists():
        return False, f"错误: 文件不存在 - {md_path}"
    if md_path.suffix.lower() not in (".md", ".markdown"):
        logger.warning(f"[pdf] {md_path} 后缀不是 .md/.markdown，仍将尝试转换")

    if pdf_path is None:
        pdf_path = md_path.with_suffix(".pdf")
    else:
        pdf_path = Path(pdf_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    forced = (engine or os.getenv("PDF_ENGINE") or "").strip().lower()
    if forced:
        if forced not in _ENGINES:
            return False, f"未知的引擎名称 '{forced}'，可选: word, pandoc, weasyprint"
        order = [(forced, _ENGINES[forced])]
    elif _is_windows() and _check_win32com_available():
        order = [
            ("word", _convert_with_word_com),
            ("pandoc", _convert_with_pandoc),
            ("weasyprint", _convert_with_weasyprint),
        ]
    else:
        # macOS / Linux: pandoc is the most reliable; weasyprint is the fallback.
        order = [
            ("pandoc", _convert_with_pandoc),
            ("weasyprint", _convert_with_weasyprint),
        ]

    logger.info(f"[pdf] {md_path} -> {pdf_path}")
    last_msg = ""
    for name, fn in order:
        logger.info(f"[pdf] 尝试引擎: {name}")
        ok, msg = fn(md_path, pdf_path)
        if ok:
            logger.info(f"[pdf] {msg}")
            return True, msg
        logger.warning(f"[pdf] 引擎 {name} 失败: {msg}")
        last_msg = msg

    return False, (
        "PDF 转换失败：所有可用引擎均未成功。" + (f" 最后一次错误：{last_msg}" if last_msg else "") +
        "\n建议安装其中一种依赖：\n"
        "  - macOS: `brew install pandoc && brew install --cask mactex`\n"
        "  - Linux: `sudo apt install pandoc texlive-xetex`\n"
        "  - Windows: `pip install pywin32 markdown`\n"
        "  - 跨平台后备: `pip install weasyprint markdown`"
    )


# ============================================================
#  Public entry: render the full trip report (Markdown + best-effort PDF)
# ============================================================

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
    pdf_ok, _msg = convert_md_to_pdf(md_path, pdf_path)

    return {
        "md_path": str(md_path),
        "pdf_path": str(pdf_path) if pdf_ok else None,
    }
