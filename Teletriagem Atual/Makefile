.PHONY: triage-smoke

triage-smoke:
	python - <<'PY'
from teletriagem.core.orchestrator import triage
import json
case = {
    "complaint": "Dor no peito há 30 minutos. Sudorese.",
    "age": 35,
    "vitals": {"hr": 120, "sbp": 160, "dbp": 100, "temp": 36.7, "spo2": 97},
}
output = triage(case)
print(json.dumps(output.model_dump(), indent=2, ensure_ascii=False))
PY
