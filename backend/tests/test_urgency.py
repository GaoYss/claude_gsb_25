"""任务紧急度规则单元测试（utils/urgency.py，规则的唯一来源）。"""

from datetime import date, timedelta

from app.utils.urgency import in_reminder_window, reminder_level, urgency_score

TODAY = date(2026, 9, 18)


def test_urgency_score_combines_priority_and_plan_date():
    # 同一计划日期：优先级越高得分越高
    assert urgency_score("urgent", TODAY, TODAY) > urgency_score("low", TODAY, TODAY)
    # 同一优先级：日期越近得分越高，逾期高于未逾期
    assert urgency_score("medium", TODAY - timedelta(days=1), TODAY) > \
        urgency_score("medium", TODAY + timedelta(days=1), TODAY)
    # 联合规则：紧急的远期任务仍排在低优先级逾期任务之前
    assert urgency_score("urgent", TODAY + timedelta(days=20), TODAY) > \
        urgency_score("low", TODAY - timedelta(days=5), TODAY)
    # 逾期 30 天以上有额外加成
    assert urgency_score("low", TODAY - timedelta(days=31), TODAY) > \
        urgency_score("low", TODAY - timedelta(days=2), TODAY)


def test_reminder_window_depends_on_priority():
    # 提醒周期按优先级区分：紧急 14 天、高 7 天、中 3 天、低 1 天
    assert in_reminder_window("urgent", TODAY + timedelta(days=14), TODAY)
    assert not in_reminder_window("urgent", TODAY + timedelta(days=15), TODAY)
    assert in_reminder_window("high", TODAY + timedelta(days=7), TODAY)
    assert not in_reminder_window("medium", TODAY + timedelta(days=4), TODAY)
    assert in_reminder_window("low", TODAY + timedelta(days=1), TODAY)
    assert not in_reminder_window("low", TODAY + timedelta(days=2), TODAY)
    # 已逾期的任务始终在提醒周期内
    assert in_reminder_window("low", TODAY - timedelta(days=90), TODAY)


def test_reminder_level_requires_open_task_in_window():
    # 紧急且临期 → 紧急提醒；优先级低或日期尚远 → 级别递减
    assert reminder_level("urgent", TODAY, True, TODAY) == "critical"
    assert reminder_level("urgent", TODAY + timedelta(days=10), True, TODAY) == "important"
    assert reminder_level("medium", TODAY, True, TODAY) == "normal"
    # 已关闭或未到提醒周期的任务不带提醒级别
    assert reminder_level("urgent", TODAY, False, TODAY) is None
    assert reminder_level("low", TODAY + timedelta(days=30), True, TODAY) is None
