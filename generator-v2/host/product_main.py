"""Entry point for the hosted controller WITH the product layer (accounts, analytics, replay, branded email).

Imports host/server.py unchanged (as a module, so its own __main__ block does not run), lets product.install() add
routes/middleware, then serves on :8080 exactly like `python host/server.py` would. If the product layer fails to load
for any reason, the plain controller still starts - builds and demos never depend on it.
"""
import os, sys, traceback
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
env = os.path.join(os.environ.get("GEN_HOME", "/vercel/gen"), ".product.env")   # GOOGLE_CLIENT_ID, RESEND_API_KEY, ...
if os.path.exists(env):
    for line in open(env):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
import server  # noqa: E402
from aiohttp import web  # noqa: E402
try:
    import product
    product.install(server.app, server)
except Exception:  # noqa: BLE001
    print("product layer NOT loaded (controller runs without it):\n" + traceback.format_exc(), flush=True)
web.run_app(server.app, host="0.0.0.0", port=server.PORT, print=None)
