"""!
@brief U5 결정 기록 단위 테스트 (SWR-010~012, SWD 8장).
"""

from childlock.event_log import EventLog
from childlock.model import INITIAL_OUTPUT


def test_event_ids_start_at_one_and_increase():
    log = EventLog()
    first = log.append(INITIAL_OUTPUT, 0.0)
    second = log.append(INITIAL_OUTPUT, 0.01)
    assert (first.event_id, second.event_id) == (1, 2)
    assert [r.event_id for r in log.records()] == [1, 2]


def test_keeps_only_latest_100_in_order():
    # SWR-012: 101건 후 event_id 2~101
    log = EventLog()
    for i in range(101):
        log.append(INITIAL_OUTPUT, i * 0.01)
    ids = [r.event_id for r in log.records()]
    assert ids == list(range(2, 102))


def test_new_log_is_empty():
    # SWR-012: 휘발성. 새 인스턴스(재시작)는 0건
    assert EventLog().records() == ()


def test_record_keeps_caller_now_s():
    rec = EventLog().append(INITIAL_OUTPUT, 1.25)
    assert rec.now_s == 1.25
