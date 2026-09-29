"""Deep analytical report assembler (spec M6 / Phase 4).

Combines the numeric analytics (metrics, correlations, scenarios) into one
structured Markdown document, optionally enriched with Claude's narrative
analysis and a disclaimer-wrapped opinion section. The document is returned as
a string and can be saved to reports/ for export.

The numeric sections always render — they need no API key. The Claude sections
are added only when the research layer is available; otherwise a short note
explains why.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from analysis import correlations, metrics, research, scenarios
from config.settings import PROJECT_ROOT

logger = logging.getLogger(__name__)

REPORTS_DIR = PROJECT_ROOT / "reports"


def _numeric_sections() -> str:
    m = metrics.build_metrics()
    c = correlations.build_report()
    s = scenarios.build_report()
    parts = [
        "## Метрики риска",
        "```",
        research._format_metrics(m),
        "```",
        "",
        "## Корреляции и скрытая концентрация",
        "```",
        research._format_correlations(c),
        "```",
        "",
        "## Стресс-тесты и сценарии",
        "```",
        research._format_scenarios(s),
        "```",
    ]
    return "\n".join(parts)


def build_markdown(include_opinion: bool = False) -> str:
    """Assemble the full report as a Markdown string."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# Глубокий аналитический отчёт по портфелю",
        f"_Сформировано: {now}_",
        "",
        "> " + research.DISCLAIMER,
        "",
        "---",
        "",
    ]

    if research.is_available():
        analysis = research.deep_analysis(include_opinion=include_opinion)
        if analysis.available:
            lines.append(analysis.text)
        else:
            lines.append(f"_Анализ Claude недоступен: {analysis.note}_")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("# Приложение: числовые показатели")
        lines.append("")
        lines.append(_numeric_sections())
    else:
        lines.append(
            "_Слой Claude отключён — показаны только числовые показатели. "
            "Добавьте ANTHROPIC_API_KEY в .env, чтобы получить текстовый анализ._"
        )
        lines.append("")
        lines.append(_numeric_sections())

    if include_opinion:
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("> **Важно.** " + research.DISCLAIMER)

    return "\n".join(lines)


def save_report(markdown: str, name: str | None = None) -> Path:
    """Write a report to reports/ and return its path."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = name or f"report_{stamp}.md"
    path = REPORTS_DIR / filename
    path.write_text(markdown, encoding="utf-8")
    logger.info("Saved report to %s", path)
    return path


def generate(include_opinion: bool = False, save: bool = True) -> tuple[str, Path | None]:
    """Build the report and optionally save it. Returns (markdown, path|None)."""
    md = build_markdown(include_opinion=include_opinion)
    path = save_report(md) if save else None
    return md, path
