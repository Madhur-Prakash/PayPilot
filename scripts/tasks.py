#!/usr/bin/env python3
"""PayPilot developer task runner - one implementation for Make, PowerShell and bash.

Standard library only, so it runs on any Python >= 3.11 before anything is
installed. Every task is safe to repeat:

* ``env`` / ``init`` never overwrite an existing ``.env``;
* ``clean`` removes caches and build output only - never ``.env``, ``.venv``,
  ``node_modules``, databases or logs;
* ``reset-db`` is the only destructive task and refuses to run without explicit
  confirmation (``--yes``, ``CONFIRM=yes``, or typing ``reset`` at the prompt).

Usage:  python scripts/tasks.py <task> [options]      (python scripts/tasks.py help)
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
IS_WINDOWS = platform.system() == "Windows"
MIN_PYTHON = (3, 11)
MIN_NODE = 20
DB_PORT = 5433

COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if COLOR else text


def info(msg: str) -> None:
    print(_c("36", "==> ") + msg, flush=True)


def ok(msg: str) -> None:
    print(_c("32", "  ok  ") + msg, flush=True)


def warn(msg: str) -> None:
    print(_c("33", "  !!  ") + msg, flush=True)


def fail(msg: str, hint: str = "") -> None:
    print(_c("31", "  xx  ") + msg, flush=True)
    if hint:
        print("       " + hint, flush=True)


class TaskError(SystemExit):
    def __init__(self, message: str, hint: str = "") -> None:
        fail(message, hint)
        super().__init__(1)


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def which(name: str) -> str | None:
    return shutil.which(name)


def run(cmd: list[str], *, cwd: Path = ROOT, check: bool = True, env: dict[str, str] | None = None,
        capture: bool = False) -> subprocess.CompletedProcess[str]:
    exe = which(cmd[0]) or cmd[0]
    full = [exe, *cmd[1:]]
    printable = " ".join(cmd)
    if not capture:
        print(_c("90", f"  $ {printable}"), flush=True)
    try:
        result = subprocess.run(full, cwd=cwd, env={**os.environ, **(env or {})}, text=True,
                                capture_output=capture, check=False)
    except FileNotFoundError:
        raise TaskError(f"Command not found: {cmd[0]}", "Install it, or check that it is on your PATH.") from None
    if check and result.returncode != 0:
        raise TaskError(f"Command failed ({result.returncode}): {printable}")
    return result


def venv_python() -> Path | None:
    for candidate in (BACKEND / ".venv" / "Scripts" / "python.exe", BACKEND / ".venv" / "bin" / "python"):
        if candidate.exists():
            return candidate
    return None


def backend_python() -> str:
    py = venv_python()
    if py is None:
        raise TaskError("Backend virtualenv not found (backend/.venv).", "Run: make install   (or python scripts/tasks.py install)")
    return str(py)


def npm() -> str:
    exe = which("npm")
    if exe is None:
        raise TaskError("npm is not installed or not on PATH.", "Install Node.js 20+ from https://nodejs.org")
    return exe


def compose() -> list[str] | None:
    if which("docker"):
        probe = subprocess.run([which("docker") or "docker", "compose", "version"], capture_output=True, text=True)
        if probe.returncode == 0:
            return ["docker", "compose"]
    if which("docker-compose"):
        return ["docker-compose"]
    return None


def docker_running() -> bool:
    if not which("docker"):
        return False
    probe = subprocess.run([which("docker") or "docker", "info", "--format", "{{.ServerVersion}}"], capture_output=True, text=True)
    return probe.returncode == 0


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def read_env() -> dict[str, str]:
    path = ROOT / ".env"
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


# --------------------------------------------------------------------------- #
# checks
# --------------------------------------------------------------------------- #
def task_check(args: argparse.Namespace) -> None:
    """Check tools, versions and configuration. Exits non-zero if something required is missing."""
    info("Checking required tools")
    problems = 0
    if sys.version_info < MIN_PYTHON:
        fail(f"Python {platform.python_version()} - need {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+", "Install Python 3.11+ from https://python.org")
        problems += 1
    else:
        ok(f"Python {platform.python_version()}")

    node = which("node")
    if node is None:
        fail("Node.js not found", "Install Node.js 20+ from https://nodejs.org")
        problems += 1
    else:
        version = run(["node", "--version"], capture=True, check=False).stdout.strip().lstrip("v")
        major = int(version.split(".")[0]) if version else 0
        (ok if major >= MIN_NODE else fail)(f"Node.js {version}" + ("" if major >= MIN_NODE else f" - need {MIN_NODE}+"))
        problems += int(major < MIN_NODE)

    for tool, required, hint in (
        ("npm", True, "Ships with Node.js."),
        ("git", True, "https://git-scm.com"),
        ("docker", False, "Optional - needed for the local Postgres (or point DATABASE_URL at your own)."),
        ("uv", False, "Optional - faster installs: https://docs.astral.sh/uv/"),
    ):
        if which(tool):
            ok(tool)
        elif required:
            fail(f"{tool} not found", hint)
            problems += 1
        else:
            warn(f"{tool} not found - {hint}")

    if which("docker"):
        if compose() is None:
            warn("docker compose plugin not found - 'make docker-up' will not work.")
        elif docker_running():
            ok("Docker daemon running")
        else:
            warn("Docker is installed but the daemon is not running - start Docker Desktop for the local database.")

    info("Checking configuration")
    env = read_env()
    if not (ROOT / ".env").exists():
        warn(".env missing - run 'make env' to create it from .env.example.")
    else:
        ok(".env present")
        if not env.get("DATABASE_URL"):
            fail("DATABASE_URL is empty", "Set it in .env (the default points at the docker-compose Postgres on port 5433).")
            problems += 1
        if env.get("APP_ENV") == "production" and env.get("JWT_SECRET", "").startswith("insecure"):
            fail("JWT_SECRET is the development default in production")
            problems += 1
        mode = "SANDBOX/LIVE" if env.get("PAYPAL_CLIENT_ID") and env.get("PAYPAL_CLIENT_SECRET") else "SIMULATED (no PayPal credentials)"
        ok(f"PayPal mode: {mode}")
        ok("Groq LLM: " + ("configured" if env.get("GROQ_API_KEY") else "not set - agents run in deterministic mode"))
        if env.get("CHANNEL3_API_KEY"):
            ok("Channel3: configured - Product Discovery and Supply Intelligence use the live catalog")
        else:
            warn("Channel3: CHANNEL3_API_KEY not set - Product Discovery and Supply Intelligence stay off "
                 "(no simulated products). Free key: https://trychannel3.com/developers")
    for label, path in (("backend venv", venv_python()), ("frontend node_modules", FRONTEND / "node_modules")):
        if path and Path(path).exists():
            ok(f"{label} installed")
        else:
            warn(f"{label} not installed - run 'make install'")
    if problems:
        raise TaskError(f"{problems} required check(s) failed.")
    info("All required checks passed.")


# --------------------------------------------------------------------------- #
# setup
# --------------------------------------------------------------------------- #
def task_env(args: argparse.Namespace) -> None:
    """Create .env from .env.example if (and only if) it does not exist."""
    target, example = ROOT / ".env", ROOT / ".env.example"
    if target.exists():
        ok(".env already exists - left untouched")
        return
    if not example.exists():
        raise TaskError(".env.example is missing - cannot create .env")
    shutil.copyfile(example, target)
    ok("created .env from .env.example (secrets are blank; the app runs in deterministic/simulated mode)")


def task_install_backend(args: argparse.Namespace) -> None:
    info("Installing backend dependencies")
    if which("uv") and (BACKEND / "pyproject.toml").exists():
        run(["uv", "sync"], cwd=BACKEND)
    else:
        if venv_python() is None:
            run([sys.executable, "-m", "venv", ".venv"], cwd=BACKEND)
        py = backend_python()
        run([py, "-m", "pip", "install", "--upgrade", "pip"], cwd=BACKEND)
        run([py, "-m", "pip", "install", "-r", "requirements.txt"], cwd=BACKEND)
        optional = BACKEND / "requirements-optional.txt"
        if optional.exists():
            result = run([py, "-m", "pip", "install", "-r", optional.name], cwd=BACKEND, check=False)
            if result.returncode != 0:
                warn("Optional extras failed to install (local embedding model) - the app falls back to hash embeddings.")
    ok("backend dependencies installed")


def task_install_frontend(args: argparse.Namespace) -> None:
    info("Installing frontend dependencies")
    lock = FRONTEND / "package-lock.json"
    run([npm(), "ci" if lock.exists() else "install"], cwd=FRONTEND)
    ok("frontend dependencies installed")


def task_install(args: argparse.Namespace) -> None:
    task_install_backend(args)
    task_install_frontend(args)


def ensure_dirs() -> None:
    for path in (BACKEND / "logs",):
        path.mkdir(parents=True, exist_ok=True)


def task_docker_up(args: argparse.Namespace) -> None:
    cmd = compose()
    if cmd is None or not docker_running():
        raise TaskError("Docker is not available or not running.", "Start Docker Desktop, or set DATABASE_URL to an existing Postgres 16 with pgvector.")
    services = ["postgres"] if not getattr(args, "full", False) else []
    profile = ["--profile", "full"] if getattr(args, "full", False) else []
    run([*cmd, *profile, "up", "-d", *services])
    task_wait_db(args)


def task_wait_db(args: argparse.Namespace, timeout: float = 90.0) -> None:
    info("Waiting for Postgres on port %d" % DB_PORT)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if port_open(DB_PORT):
            cmd = compose()
            if cmd:
                probe = subprocess.run([which(cmd[0]) or cmd[0], *cmd[1:], "exec", "-T", "postgres", "pg_isready",
                                        "-U", "autopilot", "-d", "autopilot"], cwd=ROOT, capture_output=True, text=True)
                if probe.returncode == 0:
                    ok("Postgres is ready")
                    return
            else:
                ok("Postgres port is open")
                return
        time.sleep(1.5)
    raise TaskError("Postgres did not become ready in time.", "Check 'make docker-logs'.")


def task_docker_down(args: argparse.Namespace) -> None:
    cmd = compose()
    if cmd is None:
        raise TaskError("docker compose not available.")
    run([*cmd, "--profile", "full", "--profile", "worker", "stop"])
    ok("containers stopped - data volume kept")


def task_docker_logs(args: argparse.Namespace) -> None:
    cmd = compose()
    if cmd is None:
        raise TaskError("docker compose not available.")
    run([*cmd, "logs", "-f", "--tail=150"], check=False)


def task_migrate(args: argparse.Namespace) -> None:
    run([backend_python(), "-m", "alembic", "upgrade", "head"], cwd=BACKEND)


def task_migration(args: argparse.Namespace) -> None:
    message = getattr(args, "message", None) or os.environ.get("MSG")
    if not message:
        raise TaskError("A migration message is required.", 'make migration MSG="add supplier ratings"')
    run([backend_python(), "-m", "alembic", "revision", "--autogenerate", "-m", message], cwd=BACKEND)


def task_seed(args: argparse.Namespace) -> None:
    extra = ["--reset"] if getattr(args, "reset", False) else []
    run([backend_python(), "-m", "app.seed.seed", *extra], cwd=BACKEND)


def database_reachable() -> bool:
    env = read_env()
    url = env.get("DATABASE_URL", "")
    if "localhost:5433" in url or "127.0.0.1:5433" in url or not url:
        return port_open(DB_PORT)
    return True  # a remote URL - assume the operator knows it is up


def task_init(args: argparse.Namespace) -> None:
    """Prepare a clean checkout for development. Never destroys data."""
    info("PayPilot - initialising the development environment")
    task_check_tools_only()
    task_env(args)
    ensure_dirs()
    task_install(args)
    if getattr(args, "skip_db", False):
        warn("Skipping database setup (--skip-db).")
    elif docker_running() and compose():
        task_docker_up(argparse.Namespace(full=False))
        task_migrate(args)
        task_seed(argparse.Namespace(reset=False))
    elif database_reachable() and read_env().get("DATABASE_URL"):
        info("Using the database in DATABASE_URL")
        task_migrate(args)
        task_seed(argparse.Namespace(reset=False))
    else:
        warn("No database available (Docker not running). Start Docker Desktop and run: make docker-up migrate seed")
    print()
    info("Done. Next steps:")
    print("   make dev                 start backend (http://localhost:8000) + frontend (http://localhost:3000)")
    print("   make test                run the backend + frontend test suites")
    print("   login                    owner@juniperoak.com / Autopilot@2024   (also admin@, analyst@, staff@, viewer@)")


def task_check_tools_only() -> None:
    missing = [t for t in ("node", "npm", "git") if which(t) is None]
    if sys.version_info < MIN_PYTHON:
        raise TaskError(f"Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required (found {platform.python_version()}).")
    if missing:
        raise TaskError(f"Missing required tools: {', '.join(missing)}", "Run 'make check' for details.")
    ok("required tools present")


# --------------------------------------------------------------------------- #
# run
# --------------------------------------------------------------------------- #
def backend_cmd(port: int) -> list[str]:
    return [backend_python(), "-m", "uvicorn", "app.main:app", "--reload", "--host", "0.0.0.0", "--port", str(port)]


def frontend_cmd(port: int) -> list[str]:
    return [npm(), "run", "dev", "--", "-p", str(port)]


def task_dev_backend(args: argparse.Namespace) -> None:
    run(backend_cmd(args.port), cwd=BACKEND, check=False)


def task_dev_frontend(args: argparse.Namespace) -> None:
    run(frontend_cmd(args.web_port), cwd=FRONTEND, check=False)


def task_dev(args: argparse.Namespace) -> None:
    """Database (if Docker is available) + backend + frontend, stopped together with Ctrl-C."""
    if docker_running() and compose() and not port_open(DB_PORT):
        task_docker_up(argparse.Namespace(full=False))
    elif not database_reachable():
        warn("Postgres is not reachable on port 5433 - the API will start but report the database as unavailable.")
    procs: list[subprocess.Popen[bytes]] = []
    flags = subprocess.CREATE_NEW_PROCESS_GROUP if IS_WINDOWS else 0  # type: ignore[attr-defined]
    try:
        info(f"backend  -> http://localhost:{args.port}  (API docs /docs)")
        procs.append(subprocess.Popen(backend_cmd(args.port), cwd=BACKEND, creationflags=flags))
        info(f"frontend -> http://localhost:{args.web_port}")
        procs.append(subprocess.Popen(frontend_cmd(args.web_port), cwd=FRONTEND, creationflags=flags))
        while all(p.poll() is None for p in procs):
            time.sleep(0.5)
        warn("A process exited - stopping the other one.")
    except KeyboardInterrupt:
        print()
        info("Stopping…")
    finally:
        for p in procs:
            if p.poll() is None:
                try:
                    if IS_WINDOWS:
                        p.send_signal(signal.CTRL_BREAK_EVENT)  # type: ignore[attr-defined]
                    else:
                        p.terminate()
                    p.wait(timeout=8)
                except Exception:
                    p.kill()


# --------------------------------------------------------------------------- #
# quality
# --------------------------------------------------------------------------- #
def task_test_backend(args: argparse.Namespace) -> None:
    run([backend_python(), "-m", "pytest", "-q"], cwd=BACKEND)


def task_test_frontend(args: argparse.Namespace) -> None:
    run([npm(), "run", "test"], cwd=FRONTEND)


def task_test(args: argparse.Namespace) -> None:
    task_test_backend(args)
    task_test_frontend(args)


def task_lint(args: argparse.Namespace) -> None:
    run([backend_python(), "-m", "ruff", "check", "app", "tests"], cwd=BACKEND)
    run([npm(), "run", "lint"], cwd=FRONTEND)


def task_format(args: argparse.Namespace) -> None:
    py = backend_python()
    run([py, "-m", "ruff", "format", "app", "tests"], cwd=BACKEND)
    run([py, "-m", "ruff", "check", "--fix", "app", "tests"], cwd=BACKEND, check=False)
    run([npm(), "run", "format"], cwd=FRONTEND)


def task_typecheck(args: argparse.Namespace) -> None:
    run([npm(), "run", "typecheck"], cwd=FRONTEND)
    py = backend_python()
    result = run([py, "-m", "mypy", "app", "--ignore-missing-imports"], cwd=BACKEND, check=False)
    if result.returncode != 0:
        warn("mypy reported issues (advisory - the backend gate is ruff + pytest).")


def task_build(args: argparse.Namespace) -> None:
    py = backend_python()
    run([py, "-m", "compileall", "-q", "app"], cwd=BACKEND)
    run([py, "-c", "import app.main; print('backend imports OK')"], cwd=BACKEND,
        env={"DATABASE_URL": "sqlite+aiosqlite:///./.build-check.sqlite3", "LOG_LEVEL": "ERROR"})
    run([npm(), "run", "build"], cwd=FRONTEND)
    ok("production builds complete")


# --------------------------------------------------------------------------- #
# maintenance
# --------------------------------------------------------------------------- #
PROTECTED = {".env", ".venv", "node_modules", ".git", "logs"}


def _remove(path: Path) -> None:
    resolved = path.resolve()
    if ROOT not in resolved.parents or any(part in PROTECTED for part in resolved.relative_to(ROOT).parts):
        warn(f"refusing to remove {path}")
        return
    if resolved.is_dir():
        shutil.rmtree(resolved, ignore_errors=True)
    elif resolved.exists():
        resolved.unlink(missing_ok=True)


def task_clean(args: argparse.Namespace) -> None:
    """Remove caches and build output. Never .env, venvs, node_modules, databases or logs."""
    targets = [FRONTEND / ".next", FRONTEND / "out", FRONTEND / ".turbo", FRONTEND / "tsconfig.tsbuildinfo",
               BACKEND / ".pytest_cache", BACKEND / ".ruff_cache", BACKEND / ".mypy_cache", BACKEND / "htmlcov",
               BACKEND / ".coverage", BACKEND / ".build-check.sqlite3"]
    for target in targets:
        if target.exists():
            _remove(target)
            ok(f"removed {target.relative_to(ROOT)}")
    for base in (BACKEND / "app", BACKEND / "tests", BACKEND / "alembic", ROOT / "scripts", ROOT / "n8n"):
        for cache in base.rglob("__pycache__"):
            _remove(cache)
    ok("caches cleaned (source, .env, dependencies, databases and logs untouched)")


def task_reset_db(args: argparse.Namespace) -> None:
    """Destroy and rebuild the local database. Requires explicit confirmation."""
    confirmed = getattr(args, "yes", False) or os.environ.get("CONFIRM", "").lower() in ("yes", "y", "true", "1")
    if not confirmed:
        if sys.stdin.isatty():
            try:
                answer = input("This DELETES the local Postgres volume and every row in it. Type 'reset' to continue: ")
            except (EOFError, KeyboardInterrupt):
                answer = ""
            confirmed = answer.strip().lower() == "reset"
        if not confirmed:
            raise TaskError("Refusing to reset the database without confirmation.", "Run: make reset-db CONFIRM=yes")
    cmd = compose()
    if cmd is None or not docker_running():
        raise TaskError("Docker is required to reset the local database.")
    run([*cmd, "rm", "-s", "-f", "-v", "postgres"])
    volumes = run(["docker", "volume", "ls", "-q"], capture=True).stdout.split()
    for volume in volumes:
        if volume.endswith("pga_pgdata"):
            run(["docker", "volume", "rm", volume], check=False)
    task_docker_up(argparse.Namespace(full=False))
    task_migrate(args)
    task_seed(argparse.Namespace(reset=True))
    ok("database rebuilt and re-seeded")


def task_integrations(args: argparse.Namespace) -> None:
    """Verify Channel3 and PayPal credentials against the live APIs (one lightweight call each)."""
    info("Verifying live integrations (no secrets are printed)")
    result = run([backend_python(), "-m", "app.integrations.verify"], cwd=BACKEND, check=False)
    if result.returncode != 0:
        raise TaskError("An integration check failed - see above.")
    ok("Integrations verified")


TASKS = {
    "check": (task_check, "Check tools, versions and .env configuration"),
    "integrations": (task_integrations, "Verify Channel3 + PayPal credentials against the live APIs"),
    "env": (task_env, "Create .env from .env.example (never overwrites)"),
    "init": (task_init, "Full first-time setup: check, env, deps, database, migrations, seed"),
    "install": (task_install, "Install backend + frontend dependencies"),
    "install-backend": (task_install_backend, "Install backend dependencies (uv or pip)"),
    "install-frontend": (task_install_frontend, "Install frontend dependencies (npm)"),
    "dev": (task_dev, "Run database + backend + frontend together"),
    "dev-backend": (task_dev_backend, "Run the FastAPI backend"),
    "dev-frontend": (task_dev_frontend, "Run the Next.js frontend"),
    "docker-up": (task_docker_up, "Start Postgres (or the full stack with --full)"),
    "docker-down": (task_docker_down, "Stop containers (keeps data)"),
    "docker-logs": (task_docker_logs, "Tail container logs"),
    "wait-db": (task_wait_db, "Wait until Postgres is ready"),
    "migrate": (task_migrate, "Apply Alembic migrations"),
    "migration": (task_migration, "Autogenerate a migration (--message or MSG=)"),
    "seed": (task_seed, "Load the deterministic demo dataset (--reset to rebuild)"),
    "test": (task_test, "Backend pytest + frontend vitest"),
    "test-backend": (task_test_backend, "Backend tests (SQLite, no Docker)"),
    "test-frontend": (task_test_frontend, "Frontend unit tests (vitest)"),
    "lint": (task_lint, "ruff + next lint"),
    "format": (task_format, "ruff format + prettier"),
    "typecheck": (task_typecheck, "tsc --noEmit (+ advisory mypy)"),
    "build": (task_build, "Backend compile/import check + Next.js production build"),
    "clean": (task_clean, "Remove caches and build artifacts only"),
    "reset-db": (task_reset_db, "DESTRUCTIVE: rebuild the local database (needs confirmation)"),
}


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tasks.py", description="PayPilot developer tasks")
    sub = parser.add_subparsers(dest="task")
    sub.add_parser("help")
    for name, (_, description) in TASKS.items():
        p = sub.add_parser(name, help=description)
        if name in ("dev", "dev-backend"):
            p.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
        if name in ("dev", "dev-frontend"):
            p.add_argument("--web-port", type=int, default=int(os.environ.get("WEB_PORT", 3000)))
        if name == "docker-up":
            p.add_argument("--full", action="store_true")
        if name == "seed":
            p.add_argument("--reset", action="store_true")
        if name == "migration":
            p.add_argument("--message", "-m")
        if name == "reset-db":
            p.add_argument("--yes", action="store_true")
        if name == "init":
            p.add_argument("--skip-db", action="store_true")
    args = parser.parse_args(argv)
    if args.task in (None, "help"):
        print("\n  PayPilot developer tasks\n")
        for name, (_, description) in TASKS.items():
            print(f"  {name:<18} {description}")
        print()
        return
    TASKS[args.task][0](args)


if __name__ == "__main__":
    main()
