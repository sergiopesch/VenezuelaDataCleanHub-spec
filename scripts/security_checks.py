import json
import re
from pathlib import Path

SECRET_PATTERNS = (
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{20,}"),
    re.compile(r"\bghp_[A-Za-z0-9_]{20,}"),
)

SCAN_SUFFIXES = {".env", ".example", ".json", ".md", ".py", ".rego", ".toml", ".yml", ".yaml"}
SKIP_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache"}


def iter_scannable_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix in SCAN_SUFFIXES or path.name == ".env.example":
            yield path


def assert_no_obvious_secrets(root: Path) -> None:
    violations: list[str] = []
    for path in iter_scannable_files(root):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                violations.append(str(path))
                break
    if violations:
        raise AssertionError(f"Potential committed secret patterns found: {violations}")


def assert_keycloak_service_account_shape(root: Path) -> None:
    realm = json.loads((root / "infra/keycloak/vdch-local-realm.json").read_text())
    clients = {client["clientId"]: client for client in realm["clients"]}
    openclaw_client = clients["vdch-openclaw-agent"]
    if openclaw_client.get("publicClient") is not False:
        raise AssertionError("OpenClaw client must be confidential")
    if openclaw_client.get("serviceAccountsEnabled") is not True:
        raise AssertionError("OpenClaw client must use service accounts")
    if "secret" in openclaw_client:
        raise AssertionError("Local realm must not commit a static OpenClaw client secret")


def assert_env_example_local_dev_boundary(root: Path) -> None:
    env_example = (root / ".env.example").read_text()
    required = {
        "VDCH_ENVIRONMENT=local",
        "VDCH_AUTH_MODE=dev_headers",
        "VDCH_DEV_AUTH_ENABLED=true",
        "VDCH_ALLOW_POLICY_BYPASS_FOR_LOCAL_DEV=true",
    }
    missing = sorted(value for value in required if value not in env_example)
    if missing:
        raise AssertionError(f".env.example is missing local boundary markers: {missing}")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    assert_no_obvious_secrets(root)
    assert_keycloak_service_account_shape(root)
    assert_env_example_local_dev_boundary(root)


if __name__ == "__main__":
    main()
