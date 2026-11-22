"""Single-use Git credential helper for Developer Studio sharing.

Git runs this for one push/fetch only (it is passed with ``-c credential.helper=...`` on that one
command and never written to any config). It asks the engine's short-lived broker on 127.0.0.1
for the credential, presenting the one-time code the engine put in this process's environment.
The broker answers once, only within 60 seconds, and only for the exact host and repository it
was opened for. This file deliberately imports nothing from AutoMoto so it starts fast.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request


def main(argv: list[str]) -> int:
    op = argv[-1] if len(argv) > 1 else ""
    data = sys.stdin.read(65536)
    if op != "get":  # store / erase: nothing is ever saved, so nothing to do
        return 0
    broker = os.environ.get("AUTOMOTO_CRED_BROKER", "")
    code = os.environ.get("AUTOMOTO_CRED_NONCE", "")
    if not code or not broker.startswith("http://127.0.0.1:"):
        return 0
    fields = {}
    for line in data.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            fields[k.strip()] = v.strip()
    body = json.dumps({"nonce": code, "protocol": fields.get("protocol", ""), "host": fields.get("host", ""),
                       "path": fields.get("path", "")}).encode()
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(broker, data=body, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with opener.open(req, timeout=10) as resp:
            answer = json.loads(resp.read(65536).decode("utf-8"))
    except Exception:
        return 0
    user, password = answer.get("username"), answer.get("password")
    if not (isinstance(user, str) and isinstance(password, str)) or "\n" in user + password:
        return 0
    sys.stdout.write(f"username={user}\npassword={password}\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
