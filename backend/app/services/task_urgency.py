"""任务紧急度规则的 SQL 版本：与 utils/urgency.py 同一份规则的查询表达式。

列表排序、提醒清单、看板排名都通过这里的表达式取数，
保证三处口径一致；规则参数（权重、分档、提醒周期）只在 utils/urgency.py 维护。
"""

from datetime import timedelta

from sqlalchemy import and_, case, or_

from ..models.maintenance_task import OPEN_STATUSES, MaintenanceTask
from ..utils.dates import today
from ..utils.urgency import DATE_BANDS, PRIORITY_SCORE, PRIORITY_WEIGHTS, REMINDER_CYCLE_DAYS


def _priority_score_sql():
    """优先级权重分：低=25 … 紧急=100。"""

    return case(
        *[
            (MaintenanceTask.priority == priority, weight * PRIORITY_SCORE)
            for priority, weight in PRIORITY_WEIGHTS.items()
        ],
        else_=0,
    )


def _date_score_sql(reference):
    """临期分：与 utils/urgency.date_score 相同的分档，用日期比较实现（SQLite/PG 通用）。"""

    return case(
        *[
            (MaintenanceTask.plan_date <= reference + timedelta(days=upper), score)
            for upper, score in DATE_BANDS
        ],
        else_=0,
    )


def urgency_score_sql(reference=None):
    """紧急度得分表达式：未完成任务按规则计分，已关闭（完成/取消）任务恒为 0。"""

    reference = reference or today()
    return case(
        (
            MaintenanceTask.status.in_(OPEN_STATUSES),
            _priority_score_sql() + _date_score_sql(reference),
        ),
        else_=0,
    )


def urgency_order_by(reference=None):
    """统一排序：紧急度得分高者在前；同分时未完成的临期在前，已关闭的近期在前。

    未完成任务得分至少为 25，已关闭恒为 0，因此得分天然把两组分开。
    """

    reference = reference or today()
    is_open = MaintenanceTask.status.in_(OPEN_STATUSES)
    is_closed = MaintenanceTask.status.notin_(OPEN_STATUSES)
    return (
        urgency_score_sql(reference).desc(),
        case((is_open, MaintenanceTask.plan_date), else_=None).asc(),
        case((is_closed, MaintenanceTask.plan_date), else_=None).desc(),
        MaintenanceTask.id.asc(),
    )


def reminder_window_condition(reference=None):
    """进入提醒周期的条件：计划日期不超过该任务优先级对应的提醒周期（含已逾期）。"""

    reference = reference or today()
    return or_(
        *[
            and_(
                MaintenanceTask.priority == priority,
                MaintenanceTask.plan_date <= reference + timedelta(days=cycle),
            )
            for priority, cycle in REMINDER_CYCLE_DAYS.items()
        ]
    )
