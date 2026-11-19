#!/usr/bin/env python3
"""Помощник для локальной работы (Windows/macOS/Linux, только стандартная библиотека).

  python scripts/dev.py local-env        создать .env.local из .env (localhost вместо имён контейнеров)
  python scripts/dev.py proto            сгенерировать gRPC-заглушки в .gen/
  python scripts/dev.py <сервис>         запустить СВОЙ сервис на хосте (базы поднять: make db)
  python scripts/dev.py test             тесты Loader, общего кода, Scoring и API
Сервисы: gateway, enrichment, scoring, loader, client-info, group-companies, ml-model
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PORTS = {"gateway": 8000, "enrichment": 8001, "scoring": 8002, "loader": 8003,
         "client-info": 8004, "group-companies": 8005}
TESTS = [("libs/common/tests", "libs/common"), ("services/scoring/tests", "services/scoring"),
         ("services/loader/tests", "services/loader"),
         ("services/group-companies/tests", "services/group-companies")]


def read_env(path: Path) -> dict:
    env = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def local_env():
    src = ROOT / ".env"
    if not src.exists():
        sys.exit("Сначала: скопируй .env.example в .env и заполни ключи")
    text = src.read_text(encoding="utf-8")
    for old, new in [("@postgres:", "@localhost:"), ("redis://redis:", "redis://localhost:"),
                     ("ml-model:50051", "localhost:50051")]:
        text = text.replace(old, new)
    text = text.rstrip("\n") + "\n"
    text += "MODEL_PATH=" + str(ROOT / "models" / "company-scoring-v1.dill") + "\n"
    text += "CLIENT_INFO_URL=http://localhost:8004\nGROUP_COMPANIES_URL=http://localhost:8005\n"
    text += "SCORING_URL=http://localhost:8002\n"
    (ROOT / ".env.local").write_text(text, encoding="utf-8")
    print("создан .env.local")


def proto():
    out = ROOT / ".gen"
    out.mkdir(exist_ok=True)
    subprocess.check_call([sys.executable, "-m", "grpc_tools.protoc", "-I", "proto",
                           f"--python_out={out}", f"--grpc_python_out={out}", "proto/scoring.proto"], cwd=ROOT)
    print("заглушки в .gen/")


def pythonpath(*parts) -> str:
    return os.pathsep.join(str(ROOT / p) for p in parts)


def run_service(svc: str):
    if not (ROOT / ".env.local").exists():
        local_env()
    env = os.environ.copy()
    env.update(read_env(ROOT / ".env.local"))
    env["PYTHONPATH"] = pythonpath("libs/common", f"services/{svc}", ".gen")
    if svc == "ml-model":
        cmd = [sys.executable, "-m", "app.server"]
    else:
        cmd = [sys.executable, "-m", "uvicorn", "app.main:app", "--reload", "--port", str(PORTS[svc])]
    subprocess.run(cmd, cwd=ROOT / "services" / svc, env=env)


def tests():
    code = 0
    suites = list(TESTS)
    if (ROOT / "services/client-info/tests").is_dir():
        suites.append(("services/client-info/tests", "services/client-info"))
    for tdir, extra in suites:
        env = os.environ.copy()
        env["PYTHONPATH"] = pythonpath("libs/common", extra)
        code |= subprocess.call([sys.executable, "-m", "unittest", "discover", "-s", tdir, "-v"], cwd=ROOT, env=env)
    sys.exit(code)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "local-env":
        local_env()
    elif cmd == "proto":
        proto()
    elif cmd == "test":
        tests()
    elif cmd in PORTS or cmd == "ml-model":
        run_service(cmd)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
