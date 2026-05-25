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

from core.logger import logger

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=select_autoescape(enabled_extensions=("html", "j2")),
    trim_blocks=False,
    lstrip_blocks=False,
)


def _truthy(v: str | None) -> bool:
    return (v or "").lower() in {"1", "true", "yes", "on"}


def render_markdown(ctx: Dict[str, Any]) -> str:
    template = _env.get_template("trip_report.md")
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
# 统一入口函数（自动选择最优引擎）
# ============================================================

def convert_md_to_pdf_real(
        md_path: Path,
        pdf_path: Optional[Path] = None,
        engine: Optional[str] = None
) -> str:
    """
    跨平台 Markdown 转 PDF（自动选择最优引擎）

    Args:
        md_path: Markdown 文件路径
        pdf_path: 输出 PDF 路径（可选，默认与 md_path 同目录，扩展名改为 .pdf）
        engine: 指定转换引擎（可选: 'word', 'pandoc', 'weasyprint'），None 时自动选择

    Returns:
        转换结果描述字符串
    """
    # 参数验证
    md_path = Path(md_path)
    if not md_path.exists():
        return f"错误: 文件不存在 - {md_path}"
    if not md_path.suffix.lower() in ['.md', '.markdown']:
        return f"警告: 文件可能不是 Markdown 格式 - {md_path}"

    if pdf_path is None:
        pdf_path = md_path.with_suffix('.pdf')
    else:
        pdf_path = Path(pdf_path)

    # 确保输出目录存在
    pdf_path.parent.mkdir(parents=True, exist_ok=True)

    logger.info(f"开始转换: {md_path} -> {pdf_path}")

    # 引擎选择逻辑
    engines_to_try = []

    if engine:
        # 用户指定了引擎
        if engine == 'word':
            engines_to_try = [('word', _convert_with_word_com)]
        elif engine == 'pandoc':
            engines_to_try = [('pandoc', _convert_with_pandoc)]
        elif engine == 'weasyprint':
            engines_to_try = [('weasyprint', _convert_with_weasyprint)]
        else:
            return f"错误: 未知的引擎名称 '{engine}'，可选: 'word', 'pandoc', 'weasyprint'"
    else:
        # 自动选择：Windows 优先 Word，否则 pandoc，最后 weasyprint
        if _is_windows() and _check_win32com_available():
            engines_to_try = [
                ('word', _convert_with_word_com),
                ('pandoc', _convert_with_pandoc),
                ('weasyprint', _convert_with_weasyprint)
            ]
        else:
            engines_to_try = [
                ('pandoc', _convert_with_pandoc),
                ('weasyprint', _convert_with_weasyprint)
            ]

    # 依次尝试各个引擎
    for engine_name, converter_func in engines_to_try:
        logger.info(f"尝试引擎: {engine_name}")
        success, result_msg = converter_func(md_path, pdf_path)
        if success:
            return result_msg
        else:
            logger.warning(f"引擎 {engine_name} 失败: {result_msg}")

    # 所有引擎都失败
    return (
        f"转换失败: 所有可用引擎均无法转换。\n"
        f"建议安装所需依赖:\n"
        f"- Windows: pip install pywin32 markdown\n"
        f"- macOS/Linux: brew install pandoc && brew install --cask mactex (macOS) / apt install texlive-xetex (Linux)\n"
        f"- 纯 Python 后备方案: pip install weasyprint markdown"
    )

# ============================================================
# 引擎 1: Windows Word COM（Windows 专用，质量最高）
# ============================================================

def _convert_with_word_com(md_path: Path, pdf_path: Path) -> Tuple[bool, str]:
    """
    使用 Microsoft Word COM 将 Markdown 转换为 PDF（Windows only）
    """
    # 依赖检查
    if not _is_windows():
        return False, "Word COM 引擎仅支持 Windows 平台"
    if not _check_win32com_available():
        return False, "缺少 pywin32 依赖，请执行: pip install pywin32"
    if not _check_markdown_available():
        return False, "缺少 markdown 依赖，请执行: pip install markdown"

    try:
        import markdown
        import win32com.client
        import pythoncom
    except ImportError:
        pass

    temp_html_path = md_path.with_suffix('.temp.html')
    word_app = None

    try:
        # ---------- 步骤 1: Markdown → HTML ----------
        logger.info(f"[Word COM] 读取 Markdown: {md_path}")
        with open(md_path, 'r', encoding='utf-8') as f:
            md_content = f.read()

        # 转换 Markdown 为 HTML（启用表格和代码块扩展）
        html_body = markdown.markdown(md_content, extensions=['tables', 'fenced_code'])

        # 完整的 HTML 模板（带样式，确保中文正常）
        html_content = f"""
        <html>
        <head>
            <meta charset="UTF-8">
            <style>
                body {{ font-family: "Microsoft YaHei", "SimHei", "Segoe UI", sans-serif; margin: 2em; }}
                table {{ border-collapse: collapse; width: 100%; }}
                th, td {{ border: 1px solid #ccc; padding: 8px; text-align: left; }}
                th {{ background-color: #f2f2f2; }}
                pre {{ background-color: #f5f5f5; padding: 10px; border-radius: 4px; overflow-x: auto; }}
                code {{ font-family: "Consolas", "Monaco", monospace; }}
                blockquote {{ border-left: 4px solid #ddd; margin: 0; padding-left: 1em; color: #666; }}
                img {{ max-width: 100%; }}
            </style>
        </head>
        <body>
            {html_body}
        </body>
        </html>
        """

        with open(temp_html_path, 'w', encoding='utf-8') as f:
            f.write(html_content)
        logger.info(f"[Word COM] 生成临时 HTML: {temp_html_path}")

        # ---------- 步骤 2: HTML → PDF via Word COM ----------
        # 初始化 COM 库（必须在同一线程中调用）
        pythoncom.CoInitialize()

        # 创建 Word 应用程序对象
        word_app = win32com.client.Dispatch("Word.Application")
        word_app.Visible = False
        word_app.DisplayAlerts = False

        # 打开 HTML 文件
        doc = word_app.Documents.Open(str(temp_html_path.resolve()))

        # 保存为 PDF（FileFormat=17 表示 wdFormatPDF）
        doc.SaveAs(str(pdf_path.resolve()), FileFormat=17)
        doc.Close(SaveChanges=0)

        logger.info(f"[Word COM] PDF 已生成: {pdf_path}")

        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            return True, f"成功转换 (Word COM 引擎): {pdf_path}"
        else:
            return False, f"转换完成但未生成有效文件: {pdf_path}"

    except Exception as e:
        logger.error(f"[Word COM] 转换失败: {e}", exc_info=True)
        return False, f"Word COM 转换失败: {str(e)}"

    finally:
        # 资源清理
        if word_app:
            try:
                word_app.Quit()
            except:
                pass
        try:
            pythoncom.CoUninitialize()
        except:
            pass
        if temp_html_path.exists():
            try:
                temp_html_path.unlink()
            except:
                pass


# ============================================================
# 引擎 2: pandoc + xelatex（macOS / Linux / Windows 通用，质量较高）
# ============================================================

def _convert_with_pandoc(md_path: Path, pdf_path: Path) -> Tuple[bool, str]:
    """
    使用 pandoc + xelatex 将 Markdown 转换为 PDF（跨平台）
    """
    # 依赖检查
    if not _check_pandoc_available():
        return False, "未检测到 pandoc，请先安装: https://pandoc.org/installing.html"
    if not _check_xelatex_available():
        return False, "未检测到 xelatex。请安装 LaTeX 引擎: macOS: brew install --cask mactex; Linux: sudo apt install texlive-xetex; Windows: 安装 MiKTeX"

    try:
        # 构建 pandoc 命令
        cmd = [
            'pandoc',
            str(md_path),
            '-o', str(pdf_path),
            '--pdf-engine=xelatex',
            '-V', 'geometry:margin=1in',
            '-V', 'mainfont=Helvetica',  # macOS 默认字体
            '-V', 'CJKmainfont=PingFang SC',  # 中文主字体
            '-V', 'fontsize=12pt',
            '--highlight-style=tango'
        ]

        # Linux 环境调整中文字体配置
        if _is_linux():
            cmd.extend(['-V', 'CJKmainfont=Noto Sans CJK SC'])

        logger.info(f"[pandoc] 执行命令: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode != 0:
            error_msg = result.stderr if result.stderr else "未知错误"
            logger.error(f"[pandoc] 转换失败: {error_msg}")
            return False, f"pandoc 转换失败: {error_msg}"

        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            logger.info(f"[pandoc] PDF 已生成: {pdf_path}")
            return True, f"成功转换 (pandoc + xelatex): {pdf_path}"
        else:
            return False, "转换完成但未生成有效 PDF 文件"

    except subprocess.TimeoutExpired:
        return False, "pandoc 转换超时（超过 60 秒）"
    except FileNotFoundError:
        return False, "未找到 pandoc 可执行文件"
    except Exception as e:
        logger.error(f"[pandoc] 异常: {e}", exc_info=True)
        return False, f"pandoc 转换异常: {str(e)}"


# ============================================================
# 引擎 3: weasyprint（纯 Python 实现，轻量级后备方案）
# ============================================================

def _convert_with_weasyprint(md_path: Path, pdf_path: Path) -> Tuple[bool, str]:
    """
    使用 WeasyPrint + markdown 将 Markdown 转换为 PDF（跨平台纯 Python）
    """
    # 依赖检查
    if not _check_markdown_available():
        return False, "缺少 markdown 依赖，请执行: pip install markdown"
    if not _check_weasyprint_available():
        return False, "缺少 weasyprint 依赖，请执行: pip install weasyprint"

    try:
        import markdown
        from weasyprint import HTML, CSS
        from weasyprint.text.fonts import FontConfiguration

        # ---------- 步骤 1: Markdown → HTML ----------
        logger.info(f"[WeasyPrint] 读取 Markdown: {md_path}")
        with open(md_path, 'r', encoding='utf-8') as f:
            md_content = f.read()

        html_body = markdown.markdown(md_content, extensions=['tables', 'fenced_code', 'nl2br'])

        # ---------- 步骤 2: 注入 CSS 样式 ----------
        # 跨平台中文字体配置
        font_families = []
        if _is_macos():
            font_families = ['PingFang SC', 'Helvetica Neue', 'Helvetica']
        elif _is_linux():
            font_families = ['Noto Sans CJK SC', 'WenQuanYi Micro Hei', 'sans-serif']
        else:  # Windows
            font_families = ['Microsoft YaHei', 'SimHei', 'Segoe UI']

        font_family = ', '.join(f'"{f}"' for f in font_families)

        css_style = f"""
        @page {{
            size: A4;
            margin: 2cm;
        }}
        body {{
            font-family: {font_family};
            line-height: 1.6;
            color: #333;
        }}
        h1, h2, h3, h4, h5, h6 {{
            margin-top: 1.5em;
            margin-bottom: 0.5em;
            font-weight: 600;
        }}
        table {{
            border-collapse: collapse;
            width: 100%;
            margin: 1em 0;
        }}
        th, td {{
            border: 1px solid #ddd;
            padding: 8px;
            text-align: left;
        }}
        th {{
            background-color: #f5f5f5;
        }}
        pre {{
            background-color: #f5f5f5;
            padding: 12px;
            border-radius: 6px;
            overflow-x: auto;
        }}
        code {{
            font-family: "Courier New", "Consolas", monospace;
        }}
        blockquote {{
            border-left: 4px solid #ddd;
            margin: 0;
            padding-left: 1em;
            color: #666;
        }}
        img {{
            max-width: 100%;
        }}
        """

        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="UTF-8">
            <title>{md_path.stem}</title>
        </head>
        <body>
            {html_body}
        </body>
        </html>
        """

        # ---------- 步骤 3: HTML → PDF ----------
        font_config = FontConfiguration()
        HTML(string=html_content).write_pdf(
            pdf_path,
            stylesheets=[CSS(string=css_style, font_config=font_config)],
            font_config=font_config
        )

        if pdf_path.exists() and pdf_path.stat().st_size > 0:
            logger.info(f"[WeasyPrint] PDF 已生成: {pdf_path}")
            return True, f"成功转换 (WeasyPrint 引擎): {pdf_path}"
        else:
            return False, "转换完成但未生成有效 PDF 文件"

    except Exception as e:
        logger.error(f"[WeasyPrint] 转换失败: {e}", exc_info=True)
        return False, f"WeasyPrint 转换失败: {str(e)}"




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
    project_root_path = Path(__file__).parents[1].resolve()
    source_file_path = project_root_path / "output/session_trip-c9baf0cd/trip_v1.md"
    target_file_path = project_root_path / "output/session_trip-c9baf0cd/trip_v1.pdf"
    result = convert_md_to_pdf_real(Path(source_file_path), Path(target_file_path))
    print(result)
