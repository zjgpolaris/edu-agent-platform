#!/usr/bin/env python3
from __future__ import annotations

import json
import platform
import subprocess
from importlib.metadata import PackageNotFoundError, version


def _package(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _command_version(*command: str) -> str | None:
    try:
        return subprocess.check_output(command, text=True, timeout=10).strip()
    except (OSError, subprocess.SubprocessError):
        return None


def main() -> None:
    payload = {
        "python": platform.python_version(),
        "node": _command_version("node", "--version"),
        "npm": _command_version("npm", "--version"),
        "langchain_openai": _package("langchain-openai"),
        "langgraph": _package("langgraph"),
        "pydantic": _package("pydantic"),
        "fastapi": _package("fastapi"),
        "sqlalchemy": _package("sqlalchemy"),
    }
    failures = []
    langgraph = payload["langgraph"]
    if langgraph is None or tuple(int(part) for part in langgraph.split(".")[:2]) != (1, 2):
        failures.append("langgraph_must_be_1.2.x")
    langchain_openai = payload["langchain_openai"]
    if langchain_openai is None or int(langchain_openai.split(".")[0]) != 1:
        failures.append("langchain_openai_must_be_v1")
    pydantic = payload["pydantic"]
    if pydantic is None or int(pydantic.split(".")[0]) != 2:
        failures.append("pydantic_must_be_v2")
    if payload["node"] is None or payload["npm"] is None:
        failures.append("node_or_npm_missing")
    payload["status"] = "pass" if not failures else "fail"
    payload["reasons"] = failures
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
