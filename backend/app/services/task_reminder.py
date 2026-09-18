"""任务提醒与排序的统一规则。

任务优先级与计划日期共同决定提醒级别与排列顺序：

- 提醒周期按优先级区分（``REMINDER_LEAD_DAYS``），优先级越高提前提醒的天数越多；
- 计划日期早于今天为「已逾期」，等于今天为「今日到期」，
  落入该优先级提醒周期内为「临期」，其余为「未到期」；
- 排序先按提醒级别（已逾期 → 今日到期 → 临期 → 未到期），同级内按计划日期升序，
  再按优先级（紧急优先）与编号排列；已办结（已完成/已取消）的任务不参与提醒，
  在列表中排在未办结任务之后。

任务列表默认排序、提醒清单与看板任务排名共用本模块，保证三处口径一致。
"""

from datetime import timedelta

from sqlalchemy import and_, case, or_

from ..constants import TASK_PRIORITY
from ..models.maintenance_task import OPEN_STATUSES, MaintenanceTask
from ..utils.dates import today

# 提醒周期：各优先级提前提醒的天数
REMINDER_LEAD_DAYS = {
    "urgent": 7,
    "high": 5,
    "medium": 3,
    "low": 1,
}

LEVEL_OVERDUE = "overdue"
LEVEL_DUE_TODAY = "due_today"
LEVEL_DUE_SOON = "due_soon"
LEVEL_NORMAL = "normal"


def _thresholds(reference):
    """各优先级的提醒上限日期：计划日期不晚于该日期即进入提醒。"""

    return {
        priority: reference + timedelta(days=days)
        for priority, days in REMINDER_LEAD_DAYS.items()
    }


# ------------------------------------------------------------ Python 侧判定
def reminder_level(plan_date, priority, reference=None):
    """提醒级别：由计划日期与优先级对应的提醒周期共同决定。"""

    reference = reference or today()
    if plan_date < reference:
        return LEVEL_OVERDUE
    if plan_date == reference:
        return LEVEL_DUE_TODAY
    if plan_date <= reference + timedelta(days=REMINDER_LEAD_DAYS.get(priority, 0)):
        return LEVEL_DUE_SOON
    return LEVEL_NORMAL


def reminder_fields(task, reference=None):
    """序列化补充字段：提醒级别与距到期天数（负数表示已逾期天数）。

    已办结任务不参与提醒，两个字段均为 None。
    """

    reference = reference or today()
    if task.status not in OPEN_STATUSES:
        return {"reminder_level": None, "due_in_days": None}
    return {
        "reminder_level": reminder_level(task.plan_date, task.priority, reference),
        "due_in_days": (task.plan_date - reference).days,
    }


# ------------------------------------------------------------ SQL 侧表达式
def reminder_filter(reference=None):
    """进入提醒清单的过滤条件：计划日期落入该优先级的提醒周期（含逾期与当天）。"""

    reference = reference or today()
    return or_(
        *[
            and_(
                MaintenanceTask.priority == priority,
                MaintenanceTask.plan_date <= threshold,
            )
            for priority, threshold in _thresholds(reference).items()
        ]
    )


def _priority_rank():
    """优先级次序：紧急 < 高 < 中 < 低。"""

    order = {value: index for index, value in enumerate(reversed(TASK_PRIORITY.values))}
    return case(order, value=MaintenanceTask.priority, else_=len(order))


def attention_order(reference=None):
    """统一排序：提醒级别 → 计划日期 → 优先级 → 编号；已办结任务排在最后。"""

    reference = reference or today()
    rank = case(
        (MaintenanceTask.status.notin_(OPEN_STATUSES), 4),
        (MaintenanceTask.plan_date < reference, 0),
        (MaintenanceTask.plan_date == reference, 1),
        (reminder_filter(reference), 2),
        else_=3,
    )
    return (
        rank.asc(),
        MaintenanceTask.plan_date.asc(),
        _priority_rank().asc(),
        MaintenanceTask.id.asc(),
    )
