"""
Потолок расхода и журнал трат.

Потолок ставит администратор школы, месячный: календарный месяц кончается сам,
и это единственная граница, которую не надо ни обнулять по расписанию, ни
объяснять. Проверяется он **до** вызова, а стоимость известна только после, —
значит перешагнуть его можно ровно на цену одного вызова, доли цента. Это
названо честно, а не спрятано: альтернатива — резервировать оценку заранее и
возвращать разницу, и она сложнее ровно настолько, насколько бессмысленна.

Ноль в потолке значит «нельзя», а не «без ограничений»: школа, которой забыли
поставить лимит, не должна тратить.
"""

from __future__ import annotations

from datetime import datetime, timezone

from django.db.models import Sum

from config.errors import Codes, api_error

from . import prices
from .client import read_header, read_questions
from .models import AiSpend


def month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def spent_this_month(school) -> int:
    """Сколько школа потратила с первого числа, в микродолларах."""
    total = AiSpend.objects.filter(
        school=school, created_at__gte=month_start()
    ).aggregate(total=Sum("cost_micros"))["total"]
    return total or 0


def limit_micros(school) -> int:
    return int(school.ai_month_limit_cents) * 10_000


def budget(school) -> dict:
    """Состояние потолка — то же самое, что показывается на экране."""
    limit = limit_micros(school)
    spent = spent_this_month(school)
    return {
        "limit_micros": limit,
        "spent_micros": spent,
        "left_micros": max(0, limit - spent),
        "month_start": month_start().date().isoformat(),
    }


def check_budget(school) -> None:
    state = budget(school)
    if state["left_micros"] <= 0:
        raise api_error(
            Codes.AI_BUDGET_EXCEEDED,
            "The school has spent its monthly limit for reading scans.",
            limit=state["limit_micros"],
            spent=state["spent_micros"],
        )


def read_and_charge(
    *,
    school,
    user,
    work,
    image: bytes,
    media_type: str = "image/jpeg",
    candidates: list[str] | None = None,
    model: str = prices.HAIKU,
    purpose: str = AiSpend.SCAN_HEADER,
) -> dict:
    """
    Прочитать полоску и записать трату. Одна дверь: считать, не заплатив, нельзя.
    """
    check_budget(school)
    data, input_tokens, output_tokens = read_header(
        image,
        media_type=media_type,
        candidates=candidates,
        model=model,
    )
    _charge(school, user, work, purpose, model, input_tokens, output_tokens)
    return data


def _charge(school, user, work, purpose, model, input_tokens, output_tokens):
    AiSpend.objects.create(
        school=school,
        user=user,
        work=work,
        purpose=purpose,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_micros=prices.cost_micros(model, input_tokens, output_tokens),
    )


def questions_and_charge(
    *,
    school,
    user,
    work,
    image: bytes,
    media_type: str = "image/jpeg",
    model: str = prices.SONNET,
) -> list:
    """Прочитать лист условий и записать трату. Та же дверь, что у шапок."""
    check_budget(school)
    found, input_tokens, output_tokens = read_questions(
        image, media_type=media_type, model=model
    )
    _charge(
        school, user, work, AiSpend.SCAN_QUESTIONS, model, input_tokens, output_tokens
    )
    return found
