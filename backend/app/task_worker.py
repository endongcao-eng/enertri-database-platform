from __future__ import annotations

import multiprocessing as mp
import os
import signal
import socket
import time
import uuid

from .task_queue import claim_next_task, fail_claimed_task, heartbeat_task, recover_expired_tasks, task_state
from .task_service import run_claimed_task

POLL_SECONDS = max(0.2, float(os.getenv("TASK_POLL_SECONDS", "1.0")))
HEARTBEAT_SECONDS = max(5.0, float(os.getenv("TASK_HEARTBEAT_SECONDS", "20")))


def default_worker_id() -> str:
    return os.getenv("WORKER_ID") or f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


class DatabaseTaskWorker:
    def __init__(self, worker_id: str | None = None):
        self.worker_id = worker_id or default_worker_id()
        self.running = True

    def stop(self, *_args) -> None:
        self.running = False

    def execute_claim(self, claim: dict) -> None:
        task_id = int(claim["id"])
        timeout_seconds = max(30, int(claim.get("timeout_seconds") or 1800))
        process = mp.Process(target=run_claimed_task, args=(task_id, self.worker_id), daemon=False)
        process.start()
        started = time.monotonic()
        last_heartbeat = 0.0
        while process.is_alive() and self.running:
            now = time.monotonic()
            if now - last_heartbeat >= HEARTBEAT_SECONDS:
                if not heartbeat_task(task_id, self.worker_id):
                    process.terminate()
                    process.join(timeout=5)
                    return
                last_heartbeat = now
            state = task_state(task_id, self.worker_id)
            if state in {"cancelled", "failed", "lost_lease", None}:
                process.terminate()
                process.join(timeout=5)
                return
            if now - started > timeout_seconds:
                process.terminate()
                process.join(timeout=5)
                fail_claimed_task(task_id, self.worker_id, f"任务执行超过 {timeout_seconds} 秒硬超时限制", "任务超时")
                return
            process.join(timeout=min(1.0, POLL_SECONDS))
        if process.is_alive():
            process.terminate(); process.join(timeout=5)
        elif process.exitcode not in {0, None}:
            fail_claimed_task(task_id, self.worker_id, f"任务子进程异常退出，exitcode={process.exitcode}")

    def run_forever(self) -> None:
        recovered = recover_expired_tasks()
        print(f"[EnerTri worker] id={self.worker_id} recovered_expired={recovered}", flush=True)
        signal.signal(signal.SIGTERM, self.stop)
        signal.signal(signal.SIGINT, self.stop)
        last_recovery = time.monotonic()
        while self.running:
            if time.monotonic() - last_recovery >= 30:
                recover_expired_tasks()
                last_recovery = time.monotonic()
            claim = claim_next_task(self.worker_id)
            if not claim:
                time.sleep(POLL_SECONDS)
                continue
            self.execute_claim(claim)


def main() -> None:
    DatabaseTaskWorker().run_forever()


if __name__ == "__main__":
    main()
