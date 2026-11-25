"""UiPath 없이 로봇(Dispatcher·Performer)의 서버 호출 흐름을 흉내 낸다 (R-12).

테스트(`tests/integration/test_robot_simulation.py`)와 실제 서버 점검 양쪽에서 쓴다.

실제 서버에 대고 실행(서버가 떠 있고, 이 PC의 IP가 ROBOT_ALLOWED_IPS에 있어야 한다):

    cd backend
    uv run python -m scripts.simulate_robot --base-url http://localhost:8000 --api-key <키>

주의: 실행할 때마다 서버에 시뮬레이션용 건이 등록된다. 운영 DB에는 쓰지 않는다.
"""

import argparse
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLES = REPO_ROOT / "uipath" / "samples" / "test_cases"

# 서버가 파일 시그니처로 wav를 판별하므로 앞부분만 올바르면 된다.
_WAV_HEADER = b"RIFF" + (36).to_bytes(4, "little") + b"WAVEfmt "


def make_wav(seed: str, size: int = 2048) -> bytes:
    """seed마다 내용(= SHA-256)이 다른 가짜 wav 파일 바이트."""
    body = hashlib.sha256(seed.encode()).digest() * (size // 32)
    return _WAV_HEADER + body


def load_sample(name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((SAMPLES / f"{name}.json").read_text(encoding="utf-8"))
    return data


class DispatchAction(StrEnum):
    """등록 응답에 따른 Dispatcher의 다음 행동 (docs/input_flow.md §6.2)."""

    QUEUED = "QUEUED"  # 신규 등록 → Queue 추가 → QUEUED 보고
    RESUMED = "RESUMED"  # 409 REGISTERED: 이전 실행이 중단됨 → Queue 추가부터 이어서
    LEAVE = "LEAVE"  # 409 처리 중: 아무것도 하지 않음
    MOVE_DONE = "MOVE_DONE"  # 409 STORED·NEEDS_REVIEW: 파일을 done/으로
    MOVE_FAILED = "MOVE_FAILED"  # 409 FAILED: 파일을 failed/로


_ACTION_BY_EXISTING_STATUS = {
    "REGISTERED": DispatchAction.RESUMED,
    "QUEUED": DispatchAction.LEAVE,
    "STT_DONE": DispatchAction.LEAVE,
    "RETRY_REQUESTED": DispatchAction.LEAVE,
    "STORED": DispatchAction.MOVE_DONE,
    "NEEDS_REVIEW": DispatchAction.MOVE_DONE,
    "FAILED": DispatchAction.MOVE_FAILED,
}


@dataclass
class DispatchResult:
    action: DispatchAction
    call_id: int


class RobotSimulator:
    """`client`는 httpx.Client 또는 FastAPI TestClient. 인증 헤더는 client에 설정해 둔다."""

    def __init__(self, client: httpx.Client) -> None:
        self.client = client
        self._queue_item_seq = 1000

    # ------------------------------------------------------------ Dispatcher

    def register(
        self,
        audio: bytes,
        *,
        name: str = "20261124_1512_김지현_한빛물산.wav",
        source_type: str = "DRIVE",
        **metadata: Any,
    ) -> httpx.Response:
        """`POST /api/robot/calls`. metadata로 값을 바꾸거나(None이면 생략) 추가한다."""
        form: dict[str, Any] = {
            "file_hash": hashlib.sha256(audio).hexdigest(),
            "original_name": name,
            "source_type": source_type,
            "source_ref": f"drive-{hashlib.sha256(name.encode()).hexdigest()[:8]}",
            "call_datetime": "2026-11-24T15:12:00+09:00",
            "agent_name": "김지현",
            "client_company": "한빛물산",
        }
        form.update(metadata)
        form = {key: value for key, value in form.items() if value is not None}
        return self.client.post(
            "/api/robot/calls", data=form, files={"file": (name, audio, "audio/wav")}
        )

    def queue(self, call_id: int, queue_item_id: int | None = None) -> httpx.Response:
        """Queue에 넣은 뒤 `PATCH .../status`로 QUEUED 보고."""
        if queue_item_id is None:
            self._queue_item_seq += 1
            queue_item_id = self._queue_item_seq
        return self.client.patch(
            f"/api/robot/calls/{call_id}/status",
            json={"status": "QUEUED", "queue_item_id": queue_item_id},
        )

    def dispatch(self, audio: bytes, **register_args: Any) -> DispatchResult:
        """등록 → (신규 또는 중단 복구면) Queue 추가·QUEUED 보고까지 Dispatcher 한 건 처리."""
        response = self.register(audio, **register_args)
        if response.status_code == 201:
            call_id = int(response.json()["call_id"])
            self._expect(self.queue(call_id), 200)
            return DispatchResult(DispatchAction.QUEUED, call_id)
        if response.status_code == 409:
            detail = response.json()["detail"]
            call_id = int(detail["existing_id"])
            action = _ACTION_BY_EXISTING_STATUS[detail["status"]]
            if action is DispatchAction.RESUMED:
                self._expect(self.queue(call_id), 200)
            return DispatchResult(action, call_id)
        raise AssertionError(f"등록 실패 {response.status_code}: {response.text}")

    def retry_targets(self) -> list[dict[str, int]]:
        """`GET /api/robot/calls?status=RETRY_REQUESTED`: 다음 주기에 다시 Queue에 넣을 건."""
        response = self.client.get("/api/robot/calls", params={"status": "RETRY_REQUESTED"})
        self._expect(response, 200)
        items: list[dict[str, int]] = response.json()["items"]
        return items

    def download_audio(self, call_id: int) -> httpx.Response:
        """`GET .../audio`: 재처리 때 서버의 음성 사본을 내려받는다."""
        return self.client.get(f"/api/robot/calls/{call_id}/audio")

    def redispatch(self) -> list[DispatchResult]:
        """Dispatcher의 재처리 주기: 대상 조회 → 음성 다운로드 → Queue 추가·QUEUED 보고."""
        results = []
        for target in self.retry_targets():
            call_id = target["call_id"]
            self._expect(self.download_audio(call_id), 200)
            self._expect(self.queue(call_id), 200)
            results.append(DispatchResult(DispatchAction.QUEUED, call_id))
        return results

    # ------------------------------------------------------------ Performer

    def put_transcript(self, call_id: int, result: dict[str, Any]) -> httpx.Response:
        """결과 JSON(call_schema.json)의 전사 부분을 `PUT .../transcript`로 보낸다."""
        transcript = result["transcript"]
        return self.client.put(
            f"/api/robot/calls/{call_id}/transcript",
            json={
                "segments": transcript["segments"],
                "full_text": transcript["full_text"],
                "stt_engine": result["processing"]["stt_engine"],
            },
        )

    def put_analysis(self, call_id: int, result: dict[str, Any]) -> httpx.Response:
        """결과 JSON을 그대로 `PUT .../analysis`로 보낸다."""
        return self.client.put(f"/api/robot/calls/{call_id}/analysis", json=result)

    def report_failure(
        self, call_id: int, *, step: str, stage: str, reason: str, job_id: str | None = None
    ) -> httpx.Response:
        """재시도를 모두 쓴 뒤 최종 실패를 한 번 보고 (`POST .../logs`, status=FAIL)."""
        body: dict[str, Any] = {"step": step, "status": "FAIL", "stage": stage, "message": reason}
        if job_id:
            body["orchestrator_job_id"] = job_id
        return self.client.post(f"/api/robot/calls/{call_id}/logs", json=body)

    def perform(self, call_id: int, result: dict[str, Any]) -> httpx.Response:
        """Performer 한 건: 성공·검토 필요면 전사 → 분석 적재, 실패면 실패 보고한다."""
        if result["status"] == "FAILED":
            error = result["error"]
            return self.report_failure(
                call_id,
                step=_step_for_stage(error["stage"]),
                stage=error["stage"],
                reason=error["reason"],
            )
        self._expect(self.put_transcript(call_id, result), 200)
        return self.put_analysis(call_id, result)

    # ------------------------------------------------------------ 조회

    def status(self, call_id: int) -> str:
        response = self.client.get(f"/api/calls/{call_id}")
        self._expect(response, 200)
        return str(response.json()["status"])

    @staticmethod
    def _expect(response: httpx.Response, expected: int) -> None:
        if response.status_code != expected:
            raise AssertionError(
                f"{response.request.method} {response.request.url.path} → "
                f"{response.status_code} (기대 {expected}): {response.text}"
            )


def _step_for_stage(stage: str) -> str:
    """결과 JSON의 error.stage → 로그 단계(step). 입력·STT·PII는 STT 단계, 나머지는 GENAI."""
    return {"INPUT": "STT", "STT": "STT", "PII": "STT"}.get(stage, "GENAI")


# ---------------------------------------------------------------- 서버 점검용 실행


def run_scenarios(sim: RobotSimulator, run_id: str) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []

    def check(title: str, ok: bool, detail: str) -> None:
        results.append((title, ok, detail))

    success = sim.dispatch(make_wav(f"{run_id}-success"))
    sim.perform(success.call_id, load_sample("case01_success"))
    check(
        "성공 건: 등록 → QUEUED → 전사 → 분석",
        sim.status(success.call_id) == "STORED",
        sim.status(success.call_id),
    )

    review = sim.dispatch(make_wav(f"{run_id}-review"))
    sim.perform(review.call_id, load_sample("case02_needs_review"))
    check("검토 필요 건", sim.status(review.call_id) == "NEEDS_REVIEW", sim.status(review.call_id))

    failed = sim.dispatch(make_wav(f"{run_id}-failed"))
    sim.perform(failed.call_id, load_sample("case03_failed"))
    check(
        "실패 건: FAIL 보고 → FAILED",
        sim.status(failed.call_id) == "FAILED",
        sim.status(failed.call_id),
    )

    for title, seed, call, expected in [
        ("409 재등록: STORED → done/", "success", success, DispatchAction.MOVE_DONE),
        ("409 재등록: NEEDS_REVIEW → done/", "review", review, DispatchAction.MOVE_DONE),
        ("409 재등록: FAILED → failed/", "failed", failed, DispatchAction.MOVE_FAILED),
    ]:
        again = sim.dispatch(make_wav(f"{run_id}-{seed}"))
        check(title, again.action is expected and again.call_id == call.call_id, again.action)

    interrupted = sim.register(make_wav(f"{run_id}-interrupted"))  # Queue 추가 전에 중단된 건
    resumed = sim.dispatch(make_wav(f"{run_id}-interrupted"))
    check(
        "409 재등록: REGISTERED → 이어서 QUEUED",
        interrupted.status_code == 201
        and resumed.action is DispatchAction.RESUMED
        and sim.status(resumed.call_id) == "QUEUED",
        resumed.action,
    )

    in_progress = sim.dispatch(make_wav(f"{run_id}-interrupted"))
    check(
        "409 재등록: QUEUED → 그대로 둠",
        in_progress.action is DispatchAction.LEAVE,
        in_progress.action,
    )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="로봇 API 시뮬레이션 (UiPath 없이)")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--api-key", default=os.environ.get("ROBOT_API_KEY"))
    args = parser.parse_args()
    if not args.api_key:
        print("--api-key 또는 환경 변수 ROBOT_API_KEY가 필요합니다", file=sys.stderr)
        return 2

    run_id = os.urandom(4).hex()
    with httpx.Client(
        base_url=args.base_url, headers={"X-API-Key": args.api_key}, timeout=30
    ) as client:
        results = run_scenarios(RobotSimulator(client), run_id)

    for title, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {title}  ({detail})")
    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} 통과 (run {run_id})")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
