"""任务紧急度规则：优先级 × 计划日期共同决定排序、提醒级别与提醒周期。

本模块是规则的唯一来源（纯数值计算，不依赖模型）：
- 任务列表默认排序、/statistics/reminders 提醒清单、看板「逾期/临期」排名
  全部使用同一套规则，SQL 版本见 services/task_urgency.py；
- 提醒周期按优先级区分：优先级越高，越早进入提醒清单；
- 提醒级别由紧急度得分划分，得分 = 优先级权重 × 25 + 临期分。
"""

from ..constants import REMINDER_LEVEL, TASK_PRIORITY
from .dates import today

# 优先级权重：字典定义顺序即权重（低=1 … 紧急=4）
PRIORITY_WEIGHTS = {value: weight for weight, value in enumerate(TASK_PRIORITY.values, start=1)}

# 提醒周期（天）：计划日期进入该窗口（或已逾期）的未完成任务出现在提醒清单
REMINDER_CYCLE_DAYS = {"low": 1, "medium": 3, "high": 7, "urgent": 14}

# 临期分档：距计划日期的天数（负数表示逾期）→ 分值，按上界升序、首个命中生效
DATE_BANDS = (
    (-30, 60),  # 逾期 30 天及以上
    (-1, 45),   # 逾期 1~29 天
    (0, 30),    # 今天到期
    (3, 20),    # 1~3 天后到期
    (7, 10),    # 4~7 天后到期
)
# 其余（7 天以后）0 分

PRIORITY_SCORE = 25  # 每级优先级权重分

# 提醒级别分档：按紧急度得分降序取首个命中
LEVEL_BANDS = (
    (130, "critical"),
    (90, "important"),
    (0, "normal"),
)


def date_score(days_left):
    """临期分：逾期越久、到期越近，分值越高。"""

    for upper, score in DATE_BANDS:
        if days_left <= upper:
            return score
    return 0


def urgency_score(priority, plan_date, reference=None):
    """紧急度得分：优先级权重 × 25 + 临期分，得分越高越应优先处理。"""

    reference = reference or today()
    weight = PRIORITY_WEIGHTS.get(priority, 0)
    return weight * PRIORITY_SCORE + date_score((plan_date - reference).days)


def in_reminder_window(priority, plan_date, reference=None):
    """是否进入提醒周期：已逾期，或计划日期不超过该优先级的提醒周期。"""

    reference = reference or today()
    cycle = REMINDER_CYCLE_DAYS.get(priority, 0)
    return (plan_date - reference).days <= cycle


def reminder_level(priority, plan_date, is_open, reference=None):
    """提醒级别：仅对进入提醒周期（或已逾期）的未完成任务给出级别，否则为 None。"""

    if not is_open or not in_reminder_window(priority, plan_date, reference):
        return None
    score = urgency_score(priority, plan_date, reference)
    for threshold, level in LEVEL_BANDS:
        if score >= threshold:
            return level
    return REMINDER_LEVEL.default()
