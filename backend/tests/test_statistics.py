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

    reminders = api.data(api.get("/api/v1/statistics/reminders"))["items"]
    assert len(reminders) == 2
    assert reminders[0]["reminder_level"] == "overdue"
    assert reminders[0]["due_in_days"] == -3
    assert reminders[0]["is_overdue"] is True
    assert reminders[1]["reminder_level"] == "due_soon"
    assert reminders[1]["due_in_days"] == 2


def test_reminder_window_depends_on_priority(api, make_space, make_task):
    """提醒周期按优先级区分：紧急提前 7 天、高 5 天、中 3 天、低 1 天。"""

    space = make_space()
    urgent = make_task(space=space, priority="urgent", plan_date=date.today() + timedelta(days=6))
    high = make_task(space=space, priority="high", plan_date=date.today() + timedelta(days=6))
    low = make_task(space=space, priority="low", plan_date=date.today() + timedelta(days=2))
    make_task(space=space, priority="medium", plan_date=date.today() + timedelta(days=10))

    items = api.data(api.get("/api/v1/statistics/reminders"))["items"]
    # 只有紧急任务（窗口 7 天）落入提醒周期；高 5 天、低 1 天的窗口均未覆盖
    assert {item["id"]: item["reminder_level"] for item in items} == {urgent.id: "due_soon"}
    assert low.id not in {item["id"] for item in items}

    overview = api.data(api.get("/api/v1/statistics/overview"))
    assert overview["task"]["due_soon_count"] == 1


def test_reminder_ordering_shared_by_list_reminders_and_dashboard(api, make_space, make_task):
    """列表排序、提醒清单与看板排名使用同一套规则。"""

    space = make_space()
    today = date.today()
    normal = make_task(space=space, priority="urgent", plan_date=today + timedelta(days=30))
    due_soon = make_task(space=space, priority="low", plan_date=today + timedelta(days=1))
    overdue_low = make_task(space=space, priority="low", plan_date=today - timedelta(days=1))
    overdue_urgent = make_task(space=space, priority="urgent", plan_date=today - timedelta(days=1))
    due_today = make_task(space=space, priority="medium", plan_date=today)
    closed = make_task(space=space, priority="urgent",
                       plan_date=today - timedelta(days=2), status="completed")

    # 提醒清单：已逾期（同级按优先级）→ 今日到期 → 临期；未到期任务不进入提醒
    expected_reminders = [overdue_urgent.id, overdue_low.id, due_today.id, due_soon.id]
    reminders = api.data(api.get("/api/v1/statistics/reminders"))["items"]
    assert [item["id"] for item in reminders] == expected_reminders

    dashboard = api.data(api.get("/api/v1/statistics/dashboard"))
    assert [item["id"] for item in dashboard["task_reminders"]] == expected_reminders

    # 任务列表默认排序与提醒清单一致，未到期任务随后，已办结任务排在最后
    listed = api.data(api.get("/api/v1/maintenance-tasks", page_size=50))["items"]
    assert [item["id"] for item in listed] == expected_reminders + [normal.id, closed.id]

    by_id = {item["id"]: item for item in listed}
    assert by_id[overdue_urgent.id]["reminder_level"] == "overdue"
    assert by_id[due_today.id]["reminder_level"] == "due_today"
    assert by_id[due_soon.id]["reminder_level"] == "due_soon"
    assert by_id[normal.id]["reminder_level"] == "normal"
    assert by_id[closed.id]["reminder_level"] is None
    assert by_id[closed.id]["due_in_days"] is None


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
        "overview", "distributions", "trends", "ranking",
        "task_reminders", "recent_activity",
    }
    assert len(data["trends"]) == 6
    assert data["recent_activity"]["records"]
    assert data["recent_activity"]["replacements"]
