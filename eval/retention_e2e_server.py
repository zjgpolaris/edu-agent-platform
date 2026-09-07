"""Playwright-only loopback server with a private filesystem review clock.

Never imported by the production application; no clock endpoint or query input.
"""
import argparse
import os
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "backend")]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--graph", action="store_true")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    if os.getenv("DATABASE_URL") or os.getenv("DIRECT_URL") or os.getenv("EDU_AGENT_ENVIRONMENT") == "production":
        raise RuntimeError("isolated_e2e_environment_required")
    clock_file = Path(os.environ["E2E_REVIEW_CLOCK_FILE"]).resolve()
    if Path(tempfile.gettempdir()).resolve() not in clock_file.parents or not clock_file.is_file():
        raise RuntimeError("private_e2e_clock_required")
    if args.graph:
        from scripts.dev_autotutor_graph_demo import prepare_directory, demo_environment, deny_external_network
        directory = prepare_directory()
        env = demo_environment(directory)
        os.environ.clear(); os.environ.update(env)
        from agents.autotutor_demo_policy import validate_configuration
        validate_configuration(); deny_external_network()
        from db.engine import engine
        from db.schema import metadata
        metadata.create_all(engine)
        from scripts.seed_pilot_demo import seed
        seed(verbose=False)
    from api.main import app
    from services import review_service, review_mastery_service, autotutor_follow_up
    from student_profile import now_iso
    def review_clock():
        value = clock_file.read_text().strip()
        return review_mastery_service.parse_time(value).isoformat().replace("+00:00", "Z") if value else now_iso()
    for module in (review_service, review_mastery_service, autotutor_follow_up):
        module.now_iso = review_clock
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=args.port)

if __name__ == "__main__":
    main()
