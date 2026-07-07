PYTHONPATH := backend
PYTHON := python3

.PHONY: verify verify-core verify-core-full eval eval-quick eval-rag eval-smoke eval-json index index-incremental

verify: verify-core

verify-core:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/verify_core.py --smoke

verify-core-full:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) scripts/verify_core.py --quick --frontend

eval:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) eval/run_core_evals.py

eval-quick:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) eval/run_core_evals.py --quick

eval-rag:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) eval/rag_retrieval_eval.py

eval-smoke:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) eval/run_core_evals.py --suite history_character_smoke --suite learning_assistant_smoke --suite material_rag_smoke --suite student_profile_smoke --suite homework_grading_smoke --suite pilot_path_smoke --suite tool_registry_smoke --suite guardrails_smoke

eval-json:
	PYTHONPATH=$(PYTHONPATH) $(PYTHON) eval/run_core_evals.py --json

index:
	$(PYTHON) build_index.py

index-incremental:
	$(PYTHON) build_index.py --incremental
