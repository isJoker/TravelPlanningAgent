"""Render the trip report as Markdown (always) and PDF (best-effort).

Multi-engine cross-platform Markdown -> PDF, ported from
``isJoker/DeepSearchResearcher`` (`utils/word_converter.py`'s
``convert_md_to_pdf_real``):

  - Windows:        word_com -> pandoc(+xelatex) -> weasyprint
  - macOS / Linux:  pandoc(+xelatex)             -> weasyprint

In addition to the reference behavior, this module also augments the
subprocess ``PATH`` on macOS so that a ``pandoc`` invocation can locate
xelatex installed by the official mactex/basictex packages
(``/Library/TeX/texbin``). On many macOS setups the GUI installer adds
that directory to login-shell init only, so a Python process launched
from an IDE / uvicorn / launchd never sees it - which is the most common
reason why "I installed pandoc but PDF still doesn't generate" on Mac.

The public entry ``render_report(ctx, output_dir, version)`` and its
return shape ``{"md_path": str, "pdf_path": str | None}`` are unchanged
so existing callers in ``agent/nodes.py`` are not affected. Engine
selection can also be forced via the ``PDF_ENGINE`` env var
(``word`` | ``pandoc`` | ``weasyprint``).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
#  Platform detection
# ============================================================

def _is_windows() -> bool:
    return sys.platform == "win32"


def _is_macos() -> bool:
    return sys.platform == "darwin"


def _is_linux() -> bool:
    return sys.platform.startswith("linux")


# ============================================================
#  PATH augmentation: find LaTeX/pandoc that GUI-launched processes miss
# ============================================================

def _extra_tool_paths() -> List[str]:
    """Common install locations of pandoc / xelatex that aren't always on PATH."""
    candidates: List[str] = []
    if _is_macos():
        candidates += [
            "/Library/TeX/texbin",                              # mactex / basictex
            "/usr/local/texlive/2025/bin/universal-darwin",
            "/usr/local/texlive/2024/bin/universal-darwin",
            "/usr/local/texlive/2023/bin/universal-darwin",
            "/opt/homebrew/bin",                                # apple silicon brew
            "/usr/local/bin",                                   # intel brew
        ]
    elif _is_linux():
        candidates += [
            "/usr/local/texlive/2025/bin/x86_64-linux",
            "/usr/local/texlive/2024/bin/x86_64-linux",
            "/usr/local/texlive/2023/bin/x86_64-linux",
            "/usr/local/bin",
        ]
    elif _is_windows():
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        candidates += [
            rf"{program_files}\MiKTeX\miktex\bin\x64",
            rf"{program_files}\Pandoc",
        ]
    return [p for p in candidates if Path(p).is_dir()]


def _augmented_env() -> Dict[str, str]:
    """Return os.environ extended with our extra tool paths prepended to PATH."""
    env = os.environ.copy()
    extras = _extra_tool_paths()
    if not extras:
        return env
    sep = ";" if _is_windows() else ":"
    env["PATH"] = sep.join([*extras, env.get("PATH", "")])
    return env


def _which(cmd: str) -> Optional[str]:
    """shutil.which but searches our augmented PATH so we can find tools
    installed in well-known locations that GUI processes often miss."""
    return shutil.which(cmd, path=_augmented_env().get("PATH"))


# ============================================================
#  Dependency probes
# ============================================================

def _check_pandoc_available() -> bool:
    return _which("pandoc") is not None


def _check_xelatex_available() -> bool:
    return _which("xelatex") is not None


def _check_weasyprint_available() -> bool:
    try:
        import weasyprint  # noqa: F401
        return True
    except Exception:
        # WeasyPrint can fail at import time on macOS when its native deps
        # (cairo / pango / gdk-pixbuf) are missing - treat as unavailable.
        return False


def _check_markdown_available() -> bool:
    try:
        import markdown  # noqa: F401
        return True
    except ImportError:
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
        # FileFormat=17 == wdFormatPDF
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
#  Engine 2: pandoc + xelatex (cross-platform, recommended)
# ============================================================

def _convert_with_pandoc(md_path: Path, pdf_path: Path) -> Tuple[bool, str]:
    if not _check_pandoc_available():
        return False, "未检测到 pandoc，请先安装: https://pandoc.org/installing.html"
    if not _check_xelatex_available():
        return False, (
            "未检测到 xelatex。请安装 LaTeX 引擎："
            "macOS: `brew install --cask mactex`（或更轻量 `brew install --cask basictex`）；"
            "Linux: `sudo apt install texlive-xetex`；"
            "Windows: 安装 MiKTeX 或 TeX Live。"
        )

    cmd = [
        "pandoc",
        str(md_path),
        "-o", str(pdf_path),
        "--pdf-engine=xelatex",
        "-V", "geometry:margin=1in",
        "-V", "mainfont=Helvetica",      # macOS default; LaTeX falls back if missing
        "-V", "CJKmainfont=PingFang SC", # CJK font for macOS
        "-V", "fontsize=12pt",
        "--highlight-style=tango",
    ]
    # Linux: append a second -V so pandoc uses the Linux-available CJK font.
    # (pandoc uses the LAST -V for a given key; this matches the reference
    # implementation, replacing my earlier buggy `cmd[-3] = ...`.)
    if _is_linux():
        cmd.extend(["-V", "CJKmainfont=Noto Sans CJK SC"])

    env = _augmented_env()
    try:
        logger.info(f"[pandoc] {' '.join(cmd)}")
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, env=env
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "未知错误").strip()
            logger.error(f"[pandoc] 转换失败: {err[:600]}")
            return False, f"pandoc 转换失败: {err[:600]}"
        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            return True, f"成功转换 (pandoc + xelatex): {pdf_path}"
        return False, "转换完成但未生成有效 PDF 文件"
    except subprocess.TimeoutExpired:
        return False, "pandoc 转换超时（>120s）"
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
            "缺少 weasyprint 依赖或其原生库。`pip install weasyprint` 后，"
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
#  Orchestrator (mirrors reference's `convert_md_to_pdf_real`)
# ============================================================

_ENGINES = {
    "word": _convert_with_word_com,
    "pandoc": _convert_with_pandoc,
    "weasyprint": _convert_with_weasyprint,
}


def convert_md_to_pdf_real(
    md_path: Path,
    pdf_path: Optional[Path] = None,
    engine: Optional[str] = None,
) -> str:
    """Cross-platform Markdown -> PDF with automatic engine fallback.

    Mirrors the reference implementation in DeepSearchResearcher. ``engine``
    may be forced via argument or the ``PDF_ENGINE`` env var; when omitted,
    engines are tried in platform-appropriate priority order.

    Returns a human-readable message string. Success is signalled by the
    substring ``"成功"`` (matching the reference's calling convention).
    """
    md_path = Path(md_path)
    if not md_path.exists():
        return f"错误: 文件不存在 - {md_path}"
    if md_path.suffix.lower() not in (".md", ".markdown"):
        logger.warning(f"[pdf] 文件后缀非 .md/.markdown，仍尝试转换: {md_path}")

    if pdf_path is None:
        pdf_path = md_path.with_suffix(".pdf")
    else:
        pdf_path = Path(pdf_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"开始转换: {md_path} -> {pdf_path}")

    forced = (engine or os.getenv("PDF_ENGINE") or "").strip().lower()
    if forced:
        if forced not in _ENGINES:
            return f"错误: 未知的引擎名称 '{forced}'，可选: 'word', 'pandoc', 'weasyprint'"
        engines_to_try = [(forced, _ENGINES[forced])]
    elif _is_windows() and _check_win32com_available():
        engines_to_try = [
            ("word", _convert_with_word_com),
            ("pandoc", _convert_with_pandoc),
            ("weasyprint", _convert_with_weasyprint),
        ]
    else:
        engines_to_try = [
            ("pandoc", _convert_with_pandoc),
            ("weasyprint", _convert_with_weasyprint),
        ]

    for name, fn in engines_to_try:
        logger.info(f"尝试引擎: {name}")
        success, msg = fn(md_path, pdf_path)
        if success:
            logger.info(msg)
            return msg
        logger.warning(f"引擎 {name} 失败: {msg}")

    return (
        "转换失败: 所有可用引擎均无法转换。\n"
        "建议安装其中一种依赖：\n"
        "  - macOS: `brew install pandoc && brew install --cask mactex`\n"
        "  - Linux: `sudo apt install pandoc texlive-xetex`\n"
        "  - Windows: `pip install pywin32 markdown`\n"
        "  - 跨平台后备: `pip install weasyprint markdown`"
    )


def convert_md_to_pdf(
    md_path: Path,
    pdf_path: Optional[Path] = None,
    engine: Optional[str] = None,
) -> Tuple[bool, str]:
    """Tuple-returning wrapper around :func:`convert_md_to_pdf_real` for
    callers that want an explicit success bool."""
    msg = convert_md_to_pdf_real(md_path, pdf_path, engine=engine)
    success = "成功" in msg
    return success, msg


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
    msg = convert_md_to_pdf_real(md_path, pdf_path)
    pdf_ok = "成功" in msg

    return {
        "md_path": str(md_path),
        "pdf_path": str(pdf_path) if pdf_ok else None,
    }


# ============================================================
#  CLI test mode: `python -m services.pdf_renderer path/to/file.md`
# ============================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Markdown -> PDF (multi-engine).")
    parser.add_argument("md", type=Path, help="Path to source .md file")
    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Output PDF path (default: same dir, .pdf extension)",
    )
    parser.add_argument(
        "-e", "--engine", choices=("word", "pandoc", "weasyprint"), default=None,
        help="Force a specific engine (default: auto-select for platform)",
    )
    args = parser.parse_args()

    print(f"platform = {sys.platform}")
    print(f"pandoc   = {_which('pandoc')}")
    print(f"xelatex  = {_which('xelatex')}")
    print(f"extra PATH dirs: {_extra_tool_paths()}")
    print("---")
    print(convert_md_to_pdf_real(args.md, args.output, engine=args.engine))
