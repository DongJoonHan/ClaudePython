"""!
@brief C5 결정 기록: event_id 발급과 최근 100건 메모리 보존 (SWR-010~012).

SWD-ECL-001 8장. 파일·네트워크 입출력이 없다(휘발성).
"""

from collections import deque

from childlock.model import EVENT_LOG_CAPACITY, DecisionRecord, Output


class EventLog:
    """!@brief 최근 결정 기록 저장소 (메모리 전용)."""

    def __init__(self) -> None:
        """!@brief 빈 기록과 event_id 1로 시작한다."""
        self._records: deque[DecisionRecord] = deque(maxlen=EVENT_LOG_CAPACITY)
        self._next_id = 1

    def append(self, output: Output, now_s: float) -> DecisionRecord:
        """!
        @brief 출력으로 기록을 만들어 추가한다.

        100건을 넘으면 가장 오래된 기록을 버린다.
        @param output 틱 출력
        @param now_s 틱 시각 (호출자가 넘긴 값 그대로)
        @return 추가한 기록
        """
        record = DecisionRecord.from_output(self._next_id, now_s, output)
        self._records.append(record)
        self._next_id += 1
        return record

    def records(self) -> tuple[DecisionRecord, ...]:
        """!
        @brief 보존 중인 기록을 event_id 오름차순으로 돌려준다.
        @return 기록 튜플
        """
        return tuple(self._records)
