from __future__ import annotations

import json
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 5:
        return 2
    job_id, software, workdir_text, template = sys.argv[1:]
    workdir = Path(workdir_text).resolve()
    manifest = json.loads((workdir / "manifest.json").read_text(encoding="utf-8"))
    input_file = workdir / manifest["input_file"]
    command = [part.replace("{input}", str(input_file)).replace("{workdir}", str(workdir)).replace("{job_id}", job_id) for part in shlex.split(template)]
    log_path = workdir / "simulation.log"
    result = {
        "job_id": int(job_id),
        "software": software,
        "command_executable": Path(command[0]).name if command else None,
        "argument_count": max(0, len(command) - 1),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "status": "running",
    }
    try:
        with log_path.open("wb") as log:
            completed = subprocess.run(command, cwd=workdir, stdout=log, stderr=subprocess.STDOUT, check=False)
        result["return_code"] = completed.returncode
        result["status"] = "completed" if completed.returncode == 0 else "failed"
        result["message"] = "外部求解器执行完成" if completed.returncode == 0 else "外部求解器返回非零状态，请查看 simulation.log"
    except Exception as exc:
        result["status"] = "failed"
        result["message"] = str(exc)
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    (workdir / "simulation_result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
