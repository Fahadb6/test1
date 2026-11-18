"""Wasmer Python entrypoint. Keep this small so startup errors reach Wasmer logs."""
import os
import runpy
import sys
import traceback

# Wasmer Edge expects an HTTP process on port 80. The server binds loopback,
# matching the official Wasmer Python HTTP-server template.
os.environ.setdefault("PORT", "80")
os.environ.setdefault("ZILL_HOST", "127.0.0.1")
os.environ.setdefault("ZILL_ENV", "demo")
os.environ.setdefault("ZILL_DEMO_CREDENTIALS", "shared")
os.environ.setdefault("ZILL_DB", "/data/zill.sqlite3")
os.environ.setdefault("ZILL_DEMO_CREDENTIAL_FILE", "/data/DEMO_ACCESS_LOCAL.txt")
os.environ.setdefault("ZILL_SINGLE_THREAD", "1")

try:
    runpy.run_path(os.environ.get("ZILL_SERVER_PATH", "/app/server.py"), run_name="__main__")
except BaseException:
    print("ZILL Wasmer entrypoint failed", file=sys.stderr, flush=True)
    traceback.print_exc()
    raise
