"""A tiny fake Debug Adapter used by the V42 tests. It crashes on 'continue'."""
import json
import os
import time
import sys

source = sys.argv[1] if len(sys.argv) > 1 else "prog.py"
out = sys.stdout.buffer
inp = sys.stdin.buffer
seq = 0


def send(message):
    global seq
    seq += 1
    message["seq"] = seq
    body = json.dumps(message).encode()
    out.write(b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)
    out.flush()


def read():
    length = None
    while True:
        line = inp.readline()
        if not line:
            sys.exit(0)
        if line in (b"\r\n", b"\n"):
            break
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":")[1])
    return json.loads(inp.read(length))


def respond(req, body=None, success=True):
    send({"type": "response", "request_seq": req["seq"], "command": req["command"],
          "success": success, "body": body or {}})


launch = None
while True:
    req = read()
    cmd = req["command"]
    if cmd == "initialize":
        respond(req, {"supportsConfigurationDoneRequest": True})
    elif cmd == "launch":
        launch = req
        send({"type": "event", "event": "initialized", "body": {}})
    elif cmd == "setBreakpoints":
        lines = [b["line"] for b in req["arguments"]["breakpoints"]]
        respond(req, {"breakpoints": [{"verified": True, "line": n} for n in lines]})
    elif cmd == "configurationDone":
        respond(req)
        respond(launch)
        send({"type": "event", "event": "output", "body": {"category": "stdout", "output": "fake started\n"}})
        send({"type": "event", "event": "stopped", "body": {"reason": "breakpoint", "threadId": 1}})
    elif cmd == "stackTrace":
        respond(req, {"stackFrames": [{"id": 7, "name": "add", "line": 3, "column": 1,
                                       "source": {"path": source}}]})
    elif cmd == "scopes":
        respond(req, {"scopes": [{"name": "Locals", "variablesReference": 9, "expensive": False}]})
    elif cmd == "variables":
        respond(req, {"variables": [{"name": "total", "value": "3", "type": "int"},
                                    {"name": "secret_blob", "value": "x" * 1000}]})
    elif cmd == "evaluate":
        respond(req, {"result": "1", "type": "int"})
    elif cmd == "threads":
        respond(req, {"threads": [{"id": 1, "name": "main"}]})
    elif cmd == "continue":
        linger = float(sys.argv[sys.argv.index("--linger") + 1]) if "--linger" in sys.argv else 0.0
        if linger:
            # Close the pipe but stay alive a while, like an adapter that isn't reaped yet.
            sys.stdout.flush()
            os.close(1)
            time.sleep(linger)
        os._exit(3)  # simulate the debugger crashing
    elif cmd == "disconnect":
        respond(req)
        sys.exit(0)
    else:
        respond(req)
