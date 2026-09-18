"""统计看板接口测试。"""

from datetime import date, timedelta


def test_overview_reflects_seeded_data(api, seeded):
    data = api.data(api.get("/api/v1/statistics/overview"))
    assert data["green_space"]["total"] == seeded["green_space"]
    assert data["green_space"]["total_area"] > 0
    assert data["green_space"]["by_status"]["archived"] == 1

    assert data["task"]["total"] == seeded["maintenance_task"]
    assert data["task"]["by_status"]["cancelled"] == 1
    assert 0 <= data["task"]["completion_rate"] <= 100

    assert data["record"]["total"] == seeded["maintenance_record"]
    assert data["record"]["total_work_hours"] > 0
    assert data["replacement"]["total"] == seeded["plant_replacement"]
    assert data["replacement"]["total_amount"] > 0


def test_overdue_and_due_soon_reminders(api, make_space, make_task):
    space = make_space()
    make_task(space=space, plan_date=date.today() - timedelta(days=3), status="pending")
    make_task(space=space, plan_date=date.today() + timedelta(days=2), status="pending")
    make_task(space=space, plan_date=date.today() - timedelta(days=3), status="completed")

    overview = api.data(api.get("/api/v1/statistics/overview"))
    assert overview["task"]["overdue_count"] == 1
    assert overview["task"]["due_soon_count"] == 1

    reminders = api.data(api.get("/api/v1/statistics/reminders"))
    assert len(reminders["overdue"]) == 1
    assert reminders["overdue"][0]["is_overdue"] is True
    assert len(reminders["upcoming"]) == 1


def test_reminder_window_follows_priority_cycle(api, make_space, make_task):
    """提醒周期按优先级区分：紧急 14 天、高 7 天、中 3 天、低 1 天。"""

    space = make_space()
    today = date.today()
    urgent_in_cycle = make_task(space=space, plan_date=today + timedelta(days=10), priority="urgent")
    low_out_of_cycle = make_task(space=space, plan_date=today + timedelta(days=2), priority="low")
    high_out_of_cycle = make_task(space=space, plan_date=today + timedelta(days=8), priority="high")
    make_task(space=space, plan_date=today + timedelta(days=1), priority="low", status="completed")

    reminders = api.data(api.get("/api/v1/statistics/reminders"))
    assert reminders["reminder_cycles"] == {"urgent": 14, "high": 7, "medium": 3, "low": 1}

    upcoming_ids = [item["id"] for item in reminders["upcoming"]]
    assert upcoming_ids == [urgent_in_cycle.id]
    assert low_out_of_cycle.id not in upcoming_ids
    assert high_out_of_cycle.id not in upcoming_ids

    overview = api.data(api.get("/api/v1/statistics/overview"))
    assert overview["task"]["due_soon_count"] == 1


def test_reminder_level_combines_priority_and_plan_date(api, make_space, make_task):
    """提醒级别由优先级 × 计划日期共同决定，未进入提醒周期的任务不带级别。"""

    space = make_space()
    today = date.today()
    urgent_overdue = make_task(space=space, plan_date=today - timedelta(days=1), priority="urgent")
    urgent_far = make_task(space=space, plan_date=today + timedelta(days=10), priority="urgent")
    low_far = make_task(space=space, plan_date=today + timedelta(days=30), priority="low")

    reminders = api.data(api.get("/api/v1/statistics/reminders"))
    levels = {item["id"]: item["reminder_level"] for item in reminders["overdue"] + reminders["upcoming"]}
    assert levels[urgent_overdue.id] == "critical"    # 紧急且已逾期
    assert levels[urgent_far.id] == "important"       # 紧急但尚有 10 天
    assert low_far.id not in levels                   # 低优先级且未到提醒周期

    listed = api.data(api.get("/api/v1/maintenance-tasks"))["items"]
    listed_levels = {item["id"]: item["reminder_level"] for item in listed}
    assert listed_levels[urgent_overdue.id] == "critical"
    assert listed_levels[low_far.id] is None


def test_reminder_ranking_uses_shared_urgency_rule(api, make_space, make_task):
    """提醒清单与看板排名同一套规则：紧急且临期在前，而非单纯按计划日期。"""

    space = make_space()
    today = date.today()
    low_long_overdue = make_task(space=space, plan_date=today - timedelta(days=40), priority="low")
    high_overdue = make_task(space=space, plan_date=today - timedelta(days=2), priority="high")

    reminders = api.data(api.get("/api/v1/statistics/reminders"))
    assert [item["id"] for item in reminders["overdue"]] == [high_overdue.id, low_long_overdue.id]

    dashboard = api.data(api.get("/api/v1/statistics/dashboard"))
    assert [item["id"] for item in dashboard["overdue_tasks"]] == [high_overdue.id, low_long_overdue.id]
    assert dashboard["reminder_cycles"]["urgent"] == 14


def test_distributions_cover_all_dimensions(api, make_task, make_replacement, make_record):
    task = make_task()
    record = make_record(task=task)
    make_replacement(record=record, plant_category="shrub", reason="aging", quantity=30, unit_price=10)

    data = api.data(api.get("/api/v1/statistics/distributions"))
    assert {item["value"] for item in data["green_space_by_type"]} == {"park"}
    assert {item["value"] for item in data["green_space_by_grade"]} == {"level2"}
    assert data["green_space_by_district"][0]["value"] == "西湖区"
    assert {item["value"] for item in data["task_by_type"]} == {"prune"}
    assert data["replacement_by_category"][0]["amount"] == 300.0
    assert data["replacement_by_reason"][0]["quantity"] == 30.0


def test_trends_return_requested_month_window(api, seeded):
    data = api.data(api.get("/api/v1/statistics/trends", months=6))
    items = data["items"]
    assert len(items) == 6
    assert items[-1]["month"] == f"{date.today():%Y-%m}"
    assert sum(item["record_count"] for item in items) == seeded["maintenance_record"]
    for item in items:
        assert set(item) == {
            "month", "record_count", "work_hours",
            "replacement_count", "replacement_quantity", "replacement_amount",
        }


def test_ranking_orders_by_record_count(api, make_space, make_record):
    busy = make_space(name="高频养护绿地")
    quiet = make_space(name="低频养护绿地")
    make_record(space=busy)
    make_record(space=busy, record_date=date(2026, 4, 2))
    make_record(space=quiet)

    items = api.data(api.get("/api/v1/statistics/ranking"))["items"]
    assert items[0]["name"] == "高频养护绿地"
    assert items[0]["record_count"] == 2
    assert items[0]["green_space_id"] == busy.id


def test_dashboard_returns_all_sections(api, seeded):
    data = api.data(api.get("/api/v1/statistics/dashboard"))
    assert set(data) == {
        "overview", "distributions", "trends", "ranking", "reminder_cycles",
        "overdue_tasks", "upcoming_tasks", "recent_activity",
    }
    assert len(data["trends"]) == 6
    assert data["recent_activity"]["records"]
    assert data["recent_activity"]["replacements"]
