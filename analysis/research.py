"""Claude-powered research layer (spec M6 / Phase 4).

Turns the numeric analytics (metrics, correlations, scenarios) plus cached
news into natural-language analysis using the Anthropic API. Two strict rules
shape this module:

  1. The API key (ANTHROPIC_API_KEY) is read from the environment only. It is
     never hardcoded, logged, or persisted (spec §7, §9).
  2. By default Claude produces FACTS and CONTEXT, not buy/sell signals. An
     optional "opinion" section can be enabled by the user; it is always
     wrapped in a disclaimer that it is informational, not financial advice
     (spec §3, §4 — explicit, user-toggled departure).

Every entry point degrades gracefully: if the key is missing, the SDK is not
installed, or a request fails, callers get a clear note instead of a crash.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from analysis import correlations, metrics, scenarios
from config import get_settings
from storage import News, session_scope

logger = logging.getLogger(__name__)

try:
    import anthropic

    _SDK_AVAILABLE = True
except Exception as exc:  # pragma: no cover - import-time environment issue
    anthropic = None  # type: ignore[assignment]
    _SDK_AVAILABLE = False
    logger.warning("anthropic SDK unavailable, Claude analysis disabled: %s", exc)


DISCLAIMER = (
    "Это аналитический материал, сгенерированный ИИ на основе ваших данных. "
    "Он носит информационный характер и НЕ является индивидуальной "
    "инвестиционной рекомендацией, сигналом на покупку/продажу или гарантией "
    "результата. Решения вы принимаете самостоятельно."
)

_OPINION_INSTRUCTION = (
    "В конце добавь раздел '## Мнение Claude (опционально)'. В нём можешь "
    "высказать взвешенную точку зрения о сильных и слабых сторонах портфеля и "
    "о том, на что стоит обратить внимание. Не давай прямых указаний "
    "покупать/продавать конкретные бумаги — формулируй как наблюдения и "
    "вопросы для размышления."
)


@dataclass
class ResearchResult:
    text: str
    available: bool
    cached_tokens: int = 0
    note: str | None = None


def _api_key() -> str | None:
    key = os.getenv("ANTHROPIC_API_KEY")
    return key.strip() if key else None


def is_available() -> bool:
    """True only if the SDK is importable AND a key is present in the env."""
    return _SDK_AVAILABLE and _api_key() is not None


_client = None


def _get_client():
    global _client
    if _client is None:
        _client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    return _client


def _unavailable_note() -> str:
    if not _SDK_AVAILABLE:
        return "Пакет 'anthropic' не установлен — анализ Claude недоступен."
    return (
        "ANTHROPIC_API_KEY не задан — анализ Claude отключён. "
        "Добавьте ключ в .env, чтобы включить."
    )


# --- Context builders (pure formatting of numeric reports) ----------------

def recent_news(limit: int = 40, days: int = 14) -> list[News]:
    """Most recent cached news headlines across the portfolio."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    with session_scope() as session:
        rows = (
            session.query(News)
            .filter((News.published_at.is_(None)) | (News.published_at >= cutoff))
            .order_by(News.published_at.desc().nullslast())
            .limit(limit)
            .all()
        )
        session.expunge_all()
    return rows


def _format_metrics(m: metrics.PortfolioMetrics) -> str:
    if m.note and not m.positions:
        return f"Метрики недоступны: {m.note}"
    lines = [
        f"Стоимость портфеля: {m.total_value:,.2f}",
        f"Годовая доходность (реализ.): {m.annual_return:.2%}",
        f"Годовая волатильность: {m.annual_vol:.2%}",
        f"Бета к {m.benchmark}: {m.beta:.2f}",
        f"VaR 95% (истор.): {m.var_95_hist:.2%}  | VaR 95% (парам.): {m.var_95_param:.2%}",
        f"Макс. просадка: {m.max_drawdown:.2%}",
        f"Sharpe: {m.sharpe:.2f}  | Sortino: {m.sortino:.2f}",
        f"Дней истории: {m.n_days}",
        "",
        "Позиции (вес / годовая волат. / бета):",
    ]
    for p in m.positions:
        lines.append(
            f"  {p.ticker}: {p.weight:.1%} / {p.annual_vol:.1%} / {p.beta:.2f}"
        )
    return "\n".join(lines)


def _format_correlations(c: correlations.CorrelationReport) -> str:
    if c.note:
        return f"Корреляции недоступны: {c.note}"
    lines = [f"Порог высокой корреляции: {c.threshold:.2f}; дней: {c.n_days}", ""]
    if c.high_pairs:
        lines.append("Сильно коррелированные пары:")
        for p in c.high_pairs[:15]:
            lines.append(f"  {p.a} ~ {p.b}: {p.corr:.2f}")
    else:
        lines.append("Сильно коррелированных пар не найдено.")
    if c.clusters:
        lines.append("")
        lines.append("Кластеры (скрытая концентрация — суммарный вес):")
        for cl in c.clusters:
            tickers = ", ".join(cl.tickers)
            lines.append(
                f"  [{tickers}] вес {cl.weight:.1%}, средняя корр. {cl.avg_corr:.2f}"
            )
    return "\n".join(lines)


def _format_scenarios(s: scenarios.ScenarioReport) -> str:
    if s.note and not s.results:
        return f"Сценарии недоступны: {s.note}"
    lines = [
        f"Стоимость портфеля: {s.total_value:,.2f}; бета: {s.portfolio_beta:.2f}",
        "",
        "Стресс-сценарии (изменение стоимости):",
    ]
    for r in s.results:
        lines.append(
            f"  {r.name}: {r.pct_impact:+.2%}  ({r.value_impact:+,.2f})"
        )
    if s.note:
        lines.append("")
        lines.append(f"Примечание: {s.note}")
    return "\n".join(lines)


def _format_news(items: list[News]) -> str:
    if not items:
        return "Свежих новостей в кэше нет."
    lines = []
    for n in items:
        when = n.published_at.date().isoformat() if n.published_at else "—"
        src = f" ({n.source})" if n.source else ""
        lines.append(f"  [{when}] {n.ticker}: {n.headline}{src}")
    return "\n".join(lines)


# --- Claude calls ---------------------------------------------------------

def _call(system: str, user: str, *, cache_system: bool = True) -> ResearchResult:
    """Single Claude message with optional prompt caching on the system block."""
    if not is_available():
        return ResearchResult(
            text=_unavailable_note(), available=False, note=_unavailable_note()
        )
    settings = get_settings()
    system_blocks: list[dict] = [{"type": "text", "text": system}]
    if cache_system:
        system_blocks[0]["cache_control"] = {"type": "ephemeral"}
    try:
        client = _get_client()
        resp = client.messages.create(
            model=settings.claude_model,
            max_tokens=settings.claude_max_tokens,
            thinking={"type": "adaptive"},
            system=system_blocks,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(
            block.text for block in resp.content if block.type == "text"
        ).strip()
        cached = getattr(resp.usage, "cache_read_input_tokens", 0) or 0
        return ResearchResult(text=text, available=True, cached_tokens=cached)
    except anthropic.AuthenticationError:
        note = "Ключ ANTHROPIC_API_KEY недействителен (ошибка аутентификации)."
        logger.warning("Anthropic auth failed")
        return ResearchResult(text=note, available=False, note=note)
    except anthropic.RateLimitError:
        note = "Превышен лимит запросов к Anthropic. Повторите позже."
        logger.warning("Anthropic rate limit")
        return ResearchResult(text=note, available=False, note=note)
    except Exception as exc:  # pragma: no cover - network/runtime
        note = f"Запрос к Claude не удался: {exc}"
        logger.warning("Anthropic request failed: %s", exc)
        return ResearchResult(text=note, available=False, note=note)


_NEWS_SYSTEM = (
    "Ты финансовый аналитик-ассистент. Кратко суммируй новости по портфелю на "
    "русском языке: 3-6 пунктов о ключевых событиях и их возможном влиянии на "
    "конкретные бумаги. Оперируй фактами из переданных заголовков, не выдумывай "
    "цифры. Не давай рекомендаций покупать или продавать."
)


def summarize_news(limit: int = 40, days: int = 14) -> ResearchResult:
    """Short natural-language digest of recent cached news."""
    items = recent_news(limit=limit, days=days)
    if not items:
        return ResearchResult(
            text="Свежих новостей в кэше нет. Запустите загрузку новостей.",
            available=False,
            note="no news",
        )
    user = "Заголовки новостей по портфелю:\n\n" + _format_news(items)
    return _call(_NEWS_SYSTEM, user)


_DIGEST_SYSTEM = (
    "Ты риск-аналитик портфеля. На русском языке дай сжатую сводку (5-8 "
    "пунктов): главные риски концентрации, что показывают метрики риска, "
    "уязвимость к стресс-сценариям. Только факты и наблюдения, без советов "
    "покупать/продавать."
)


def portfolio_digest() -> ResearchResult:
    """Compact risk-focused digest of the whole portfolio."""
    m = metrics.build_metrics()
    c = correlations.build_report()
    s = scenarios.build_report()
    user = (
        "## Метрики риска\n" + _format_metrics(m) + "\n\n"
        "## Корреляции и кластеры\n" + _format_correlations(c) + "\n\n"
        "## Стресс-сценарии\n" + _format_scenarios(s)
    )
    return _call(_DIGEST_SYSTEM, user)


_REPORT_SYSTEM_BASE = (
    "Ты старший инвестиционный аналитик. Составь развёрнутый структурированный "
    "аналитический отчёт по портфелю на русском языке в формате Markdown. "
    "Разделы: '## Обзор портфеля', '## Анализ риска и волатильности', "
    "'## Корреляции и скрытая концентрация', '## Стресс-тесты и сценарии', "
    "'## Контекст новостей', '## Итоги и на что обратить внимание'. "
    "Опирайся строго на переданные данные, интерпретируй цифры понятным языком, "
    "не выдумывай значения. По умолчанию давай факты и контекст, а НЕ сигналы "
    "на покупку/продажу."
)


def deep_analysis(include_opinion: bool = False) -> ResearchResult:
    """Full structured analytical report assembled from all Phase 4 analytics.

    include_opinion=True appends a clearly-labelled, disclaimer-wrapped opinion
    section per the user's hybrid choice. The disclaimer is added by the caller
    layer (report/UI) so it is always visible regardless of model output.
    """
    m = metrics.build_metrics()
    c = correlations.build_report()
    s = scenarios.build_report()
    news = recent_news()

    system = _REPORT_SYSTEM_BASE
    if include_opinion:
        system = system + "\n\n" + _OPINION_INSTRUCTION

    user = (
        "Данные для отчёта.\n\n"
        "## Метрики риска\n" + _format_metrics(m) + "\n\n"
        "## Корреляции и кластеры\n" + _format_correlations(c) + "\n\n"
        "## Стресс-сценарии\n" + _format_scenarios(s) + "\n\n"
        "## Свежие новости\n" + _format_news(news)
    )
    return _call(system, user)
