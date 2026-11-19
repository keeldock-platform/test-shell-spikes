"""Validate the coordinator's source-controlled, one-wave discovery scope."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUTHORIZATION = "ci/discovery-authorization.json"


def discovery_authorization_errors(policy, env, *, require_ci=False):
    if policy.get("mode") != "first-ci-run-discovery":
        return []
    if policy.get("discoveryAuthorization") != AUTHORIZATION:
        return [f"discovery requires coordinator authorization at {AUTHORIZATION}"]
    try:
        authorization = json.loads((ROOT / AUTHORIZATION).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        return [f"cannot read coordinator discovery authorization: {error}"]
    if not isinstance(authorization, dict):
        return ["coordinator discovery authorization must be an object"]
    numbers = authorization.get("runNumbers")
    ref = authorization.get("ref")
    if (authorization.get("schemaVersion") != 1
            or not isinstance(numbers, list) or not numbers
            or any(type(number) is not int or number < 1 for number in numbers)
            or not isinstance(ref, str) or not ref.startswith("refs/heads/")
            or type(authorization.get("runAttempt")) is not int
            or authorization["runAttempt"] != 1):
        return ["invalid coordinator discovery scope: positive run numbers, branch ref, and attempt 1 required"]
    if require_ci or env.get("GITHUB_ACTIONS") == "true":
        number = env.get("GITHUB_RUN_NUMBER", "")
        if (not re.fullmatch(r"[1-9][0-9]*", number)
                or int(number) not in numbers
                or env.get("GITHUB_RUN_ATTEMPT") != "1"
                or env.get("GITHUB_REF") != ref
                or env.get("GITHUB_REF_TYPE") != "branch"):
            return ["discovery is outside the coordinator-authorized run numbers, branch, or first attempt; coordinator freeze is required"]
    return []
