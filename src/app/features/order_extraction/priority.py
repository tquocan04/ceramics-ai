"""Priority derivation (plan §14).

The model may suggest a priority, but the workshop's scheduling rule is a
business decision, not a language one. So the deterministic rule below is
authoritative and the model's opinion travels alongside it as `ai_priority`.
When the two disagree we say so in a warning -- a persistent disagreement is a
signal that the rule's thresholds need revisiting, which is only visible if we
record both.

Thresholds are transcribed from `derivePriority` in frontend/lib/mock/ai.ts.
"""

from __future__ import annotations

from app.common.enums import Priority, WarningCode
from app.common.responses import AnalysisWarning

__all__ = ["derive_priority"]

#: Applied when the customer stated no deadline: assume a comfortable horizon
#: rather than inventing urgency.
_ASSUMED_DEADLINE_DAYS = 30


def derive_priority(
    *,
    quantity: int | None,
    deadline_days: int | None,
    ai_priority: Priority | None = None,
) -> tuple[Priority, str, list[AnalysisWarning]]:
    """Return the authoritative priority, its reason, and any disagreement."""
    qty = quantity or 0
    days = deadline_days if deadline_days is not None else _ASSUMED_DEADLINE_DAYS

    if qty >= 300 or days <= 5:
        priority = Priority.URGENT
        reason = f"Số lượng {qty} sản phẩm với deadline {days} ngày — cần ưu tiên tối đa"
    elif qty >= 150 and days <= 10:
        priority = Priority.HIGH
        reason = f"Số lượng {qty} sản phẩm và deadline {days} ngày"
    elif 0 < qty < 50 and days >= 14:
        priority = Priority.LOW
        reason = f"Số lượng nhỏ ({qty}) và thời gian rộng rãi ({days} ngày)"
    else:
        priority = Priority.NORMAL
        reason = f"Số lượng {qty} sản phẩm, deadline {days} ngày — trong khả năng đáp ứng"

    warnings: list[AnalysisWarning] = []
    if ai_priority is not None and ai_priority != priority:
        warnings.append(
            AnalysisWarning(
                code=WarningCode.AI_PRIORITY_OVERRIDDEN,
                field="priority",
                message=(
                    f"AI đề xuất {ai_priority.value}, quy tắc nghiệp vụ xác định "
                    f"{priority.value}. Đang dùng giá trị theo quy tắc."
                ),
            )
        )

    return priority, reason, warnings
