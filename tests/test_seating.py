from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest

from classroom.core.errors import AppError
from classroom.web.app import create_app


def test_64_simultaneous_distinct_seats(services, active):
    _, seating = services
    cls, current = active
    def register(i):
        return seating.submit(current["id"], i, f"同学{i}", str(i), uuid4().hex)
    with ThreadPoolExecutor(max_workers=64) as executor:
        results = list(executor.map(register, range(1, 65)))
    assert all(r["accepted"] for r in results)
    arrangement = seating.get_arrangement(cls["id"])
    assert arrangement["count"] == 64
    assert {r["seat_no"] for r in arrangement["registrations"]} == set(range(1, 65))
    assert all("client_id" not in r and "group" in r and "id" in r for r in arrangement["registrations"])


def test_64_contenders_only_one_success(services, active):
    _, seating = services
    cls, current = active
    def register(i):
        try:
            seating.submit(current["id"], 1, "同学" + str(i), str(i), uuid4().hex)
            return "accepted"
        except AppError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=64) as executor:
        results = list(executor.map(register, range(64)))
    assert results.count("accepted") == 1
    assert results.count("seat_taken") == 63
    assert seating.get_arrangement(cls["id"])["count"] == 1


def test_idempotent_retry_after_close_correction_and_clear(services, active):
    _, seating = services
    cls, current = active
    rid = current["id"]
    first = seating.submit(rid, 8, "王同学", "client", "request")
    retry = seating.submit(rid, 8, "王同学", "client", "request")
    assert retry["duplicate"] and first["registration_id"] == retry["registration_id"]
    seating.close_round(rid)
    seating.correct(rid, 8, "李同学")
    assert seating.submit(rid, 8, "王同学", "client", "request")["duplicate"]
    assert seating.get_arrangement(cls["id"])["registrations"][0]["name"] == "李同学"
    seating.correct(rid, 8, "")
    assert seating.submit(rid, 8, "王同学", "client", "request")["duplicate"]
    assert seating.get_arrangement(cls["id"])["count"] == 0
    with pytest.raises(AppError, match="登记已结束"):
        seating.submit(rid, 9, "王同学", "other", "new-request")


def test_identity_is_not_name_and_one_browser_per_round(services, active):
    _, seating = services
    cls, current = active
    rid = current["id"]
    seating.submit(rid, 1, "张伟", "client-a", "req-a")
    with pytest.raises(AppError, match="同名"):
        seating.submit(rid, 2, "张伟", "client-b", "req-b")
    seating.correct(rid, 2, "张伟", force_new=True)
    assert seating.get_arrangement(cls["id"])["count"] == 2
    with pytest.raises(AppError, match="本浏览器已经登记"):
        seating.submit(rid, 3, "另一人", "client-a", "req-c")
    with pytest.raises(AppError, match="重复请求的内容不同"):
        seating.submit(rid, 4, "张伟", "client-a", "req-a")
    seating.correct(rid, 1, "")
    seating.submit(rid, 3, "其他同学", "client-a", "req-new")


def test_rounds_classes_and_readonly_history(services, active):
    classes, seating = services
    cls, current = active
    second = classes.create("高二（1）班")
    with pytest.raises(AppError, match="高一"):
        seating.open_round(second["id"])
    seating.correct(current["id"], 64, "旧同学")
    seating.close_round(current["id"])
    new = seating.open_round(cls["id"])
    assert new["round"]["number"] == 2 and new["count"] == 0
    history = seating.get_arrangement(cls["id"], current["id"])
    assert history["count"] == 1 and not history["is_current"]
    with pytest.raises(AppError, match="历史存档只读"):
        seating.correct(current["id"], 64, "篡改")
    with pytest.raises(AppError, match="不属于"):
        seating.get_arrangement(second["id"], current["id"])
    seating.close_round(new["round"]["id"])
    other_round = seating.open_round(second["id"])
    assert other_round["count"] == 0
    assert seating.get_arrangement(cls["id"])["round"]["number"] == 2


def test_restart_preserves_records(app, services, active):
    _, seating = services
    cls, current = active
    seating.correct(current["id"], 32, "恢复同学")
    other = create_app(app.config["DATA_DIR"])
    assert other.extensions["seating"].get_arrangement(cls["id"])["registrations"][0]["name"] == "恢复同学"


@pytest.mark.parametrize("seat", [0, 65, True, "1", 1.5, None, {}])
def test_invalid_seats(services, active, seat):
    with pytest.raises(AppError):
        services[1].submit(active[1]["id"], seat, "同学", "client", "req")


@pytest.mark.parametrize("name", ["", "  ", "a" * 31, "换\n行", "\ud800", "\uffff", {}, None])
def test_invalid_names(services, active, name):
    with pytest.raises(AppError):
        services[1].submit(active[1]["id"], 1, name, "client", "req")
