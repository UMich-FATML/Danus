"""Generate a credential-free provider patch from explicit deployment settings."""
from __future__ import annotations

import json
import os
from pathlib import Path

from danus.dsh import validate_provider_patch


def required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"{name} is required in config/dsh.env or config/danus.env")
    return value


def provider_rows() -> list[dict]:
    provider = required("DANUS_DSH_PROVIDER")
    api = required("DANUS_DSH_API")
    base = required("DANUS_DSH_API_BASE_URL")
    required("DANUS_DSH_API_KEY")  # Validate presence; never write the secret.
    model = required("DANUS_MAIN_MODEL")
    effort = required("DANUS_MAIN_EFFORT")
    models: dict[str, set[str]] = {}
    for service in ("MAIN", "WORKER", "VERIFY", "WRITE_PAPER", "HUMAN_SUMMARY"):
        name = os.environ.get(f"DANUS_{service}_MODEL") or model
        level = os.environ.get(f"DANUS_{service}_EFFORT") or effort
        models.setdefault(name, set()).add(level)
    # Worker rosters carry their own high/xhigh levels; declare only explicit
    # gateway-supported values rather than inventing an effort mapping.
    supported = os.environ.get("DANUS_DSH_REASONING_EFFORTS", effort).split(",")
    for levels in models.values():
        levels.update(x.strip() for x in supported if x.strip())
    rows = [{"id": "llm-pi-ai", "config": {"providers": {provider: {
        "api": api, "baseURL": base, "apiKeyEnv": "DANUS_DSH_API_KEY",
        "models": [{"id": name, "reasoningEfforts": {level: level for level in sorted(levels)}}
                   for name, levels in sorted(models.items())],
    }}}}, {"id": "llm-deepseek", "disabled": True},
        {"id": "llm-deepseek-account", "disabled": True}]
    validate_provider_patch(rows, provider)
    return rows


def main() -> None:
    path = Path(required("DANUS_DSH_PROVIDER_PATCH")).expanduser()
    if not path.is_absolute():
        raise ValueError("DANUS_DSH_PROVIDER_PATCH must be absolute")
    rows = provider_rows()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)
    print(f"Wrote credential-reference-only provider patch: {path}")
    print("No model request was made; run scripts/check-dsh.sh for offline checks.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as error:
        raise SystemExit(str(error)) from error
