"""Isolated, loopback-only, offline Graph demo. No cloud credentials or data."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
MARKER = {"schema_version": 1, "profile": "local_demo_graph", "production_evidence": False}
NETWORK_COUNTS = {"external_attempts": 0}


def prepare_directory(reuse: str | None = None) -> Path:
    if reuse:
        directory = Path(reuse).resolve(strict=True)
        if json.loads((directory / "demo.json").read_text()) != MARKER or not (directory / "jwt-secret").is_file() or not (directory / "demo.sqlite3").is_file():
            raise ValueError("demo_directory_invalid")
        return directory
    directory = Path(tempfile.mkdtemp(prefix="edu-agent-graph-demo-"))
    (directory / "demo.json").write_text(json.dumps(MARKER))
    secret = directory / "jwt-secret"
    secret.write_text(secrets.token_urlsafe(48))
    secret.chmod(0o600)
    return directory


def demo_environment(directory: Path, parent=None) -> dict[str, str]:
    parent = dict(os.environ if parent is None else parent)
    if parent.get("DATABASE_URL") or parent.get("DIRECT_URL"):
        raise ValueError("Unset DATABASE_URL and DIRECT_URL before running the isolated demo")
    env = {k: v for k, v in parent.items() if not k.startswith(("EDU_AGENT_", "LANGCHAIN_", "LANGSMITH_", "LANGFUSE_", "EMBED_", "BAILIAN_", "OPENAI_", "OTEL_"))}
    env.update({
        "PYTHONPATH": str(ROOT / "backend"), "EDU_AGENT_ENVIRONMENT": "local",
        "EDU_AGENT_DEMO_DIR": str(directory), "EDU_AGENT_DB_PATH": str(directory / "demo.sqlite3"),
        "JWT_SECRET": (directory / "jwt-secret").read_text(), "EDU_AGENT_AUTH_REQUIRED": "true",
        "EDU_AGENT_DATA_SCOPE": "demo", "EDU_AGENT_LLM_DISABLED": "1",
        "EDU_AGENT_AUTH_DB_AUTHORITY": "true",
        "EDU_AGENT_AUTOTUTOR_DEMO_GRAPH_ENABLED": "true",
        "EDU_AGENT_AUTOTUTOR_EXECUTOR_MODE": "legacy", "EDU_AGENT_AUTOTUTOR_GRAPH_ACTIVE_BPS": "0",
        "EDU_AGENT_AUTOTUTOR_GRAPH_CONFIG_VERSION": "v1.50-local-graph-demo",
        "EDU_AGENT_AUTOTUTOR_GRAPH_COMPARATOR_ENABLED": "true", "EDU_AGENT_AUTOTUTOR_GRAPH_FALLBACK_ENABLED": "true",
        "EDU_AGENT_AUTOTUTOR_CONTENT_GATE_MODE": "enforce", "EDU_AGENT_AUTOTUTOR_CONTENT_GATE_BPS": "10000",
        "LANGCHAIN_TRACING_V2": "false", "LANGSMITH_TRACING": "false", "LANGFUSE_ENABLED": "false",
    })
    env["EDU_AGENT_DEPLOYED_COMMIT"] = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    return env


def deny_external_network() -> None:
    """Defense in depth in the dedicated demo process, not normal application code."""
    import ipaddress
    original = socket.socket.connect
    original_ex = socket.socket.connect_ex
    original_resolve = socket.getaddrinfo
    def check(address):
        if isinstance(address, tuple):
            try:
                allowed = address[0] == "localhost" or ipaddress.ip_address(address[0]).is_loopback
            except ValueError:
                allowed = False
            if not allowed:
                NETWORK_COUNTS["external_attempts"] += 1
                raise OSError("demo_external_network_forbidden")
    def connect(sock, address):
        check(address)
        return original(sock, address)
    def connect_ex(sock, address):
        check(address)
        return original_ex(sock, address)
    def getaddrinfo(host, port, *args, **kwargs):
        if host is not None:
            check((host.decode() if isinstance(host, bytes) else host, port))
        return original_resolve(host, port, *args, **kwargs)
    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.getaddrinfo = getaddrinfo


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reuse-dir")
    parser.add_argument("--port", type=int, default=18080)
    parser.add_argument("--frontend-port", type=int, default=13000)
    parser.add_argument("--backend-only", action="store_true")
    parser.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        sys.path.insert(0, str(ROOT))
        sys.path.insert(0, str(ROOT / "backend"))
        from agents.autotutor_demo_policy import validate_configuration
        validate_configuration()
        deny_external_network()
        from db.engine import engine
        from db.schema import metadata
        metadata.create_all(engine)
        from scripts.seed_pilot_demo import seed
        # Reuse never reseeds or resets existing progress.
        if not (Path(os.environ["EDU_AGENT_DEMO_DIR"]) / "seeded").exists():
            seed(verbose=False)
            (Path(os.environ["EDU_AGENT_DEMO_DIR"]) / "seeded").touch()
        import uvicorn
        uvicorn.run("api.main:app", host="127.0.0.1", port=args.port)
        return 0
    if os.getenv("DATABASE_URL") or os.getenv("DIRECT_URL"):
        parser.error("Unset DATABASE_URL and DIRECT_URL; this command never uses an existing database")
    directory = prepare_directory(args.reuse_dir)
    env = demo_environment(directory)
    env["FRONTEND_ORIGIN"] = f"http://127.0.0.1:{args.frontend_port}"
    print(f"Local demo directory: {directory}\nProduction evidence: false", flush=True)
    commands = [[sys.executable, __file__, "--child", "--port", str(args.port)]]
    env["NEXT_PUBLIC_API_BASE_URL"] = f"http://127.0.0.1:{args.port}"
    env["NEXT_DIST_DIR"] = ".next-graph-demo"
    if not args.backend_only:
        commands.append(["npm", "run", "dev", "--prefix", "frontend", "--", "--hostname", "127.0.0.1", "--port", str(args.frontend_port)])
        print(f"Open http://127.0.0.1:{args.frontend_port}", flush=True)
    children = []
    try:
        for command in commands:
            children.append(subprocess.Popen(command, cwd=ROOT, env=env))
        while True:
            for child in children:
                if child.poll() is not None:
                    return child.returncode
            time.sleep(0.2)
    except KeyboardInterrupt:
        return 0
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
