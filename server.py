# --- hygiene for certain hosted environments (keep) ---
import sys
sys.path = [p for p in sys.path if not p.endswith('/agents/python')]
if 'typing_extensions' in sys.modules:
    del sys.modules['typing_extensions']

# --- std imports ---
import os
import time
import importlib
import importlib.util
import pkgutil

# --- FastAPI & CORS ---
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

# --- shared runtime (App Insights logger etc.) ---
from runtime import logger

# -----------------------------------------------------------------------------
# FastAPI app & CORS
# -----------------------------------------------------------------------------
app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # tighten later
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------------------------------------------------------
# Paths & sys.path
# -----------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_DIR = os.path.join(BASE_DIR, "tools")

if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
if TOOLS_DIR not in sys.path:
    sys.path.insert(0, TOOLS_DIR)

# -----------------------------------------------------------------------------
# Dynamic tool discovery
# -----------------------------------------------------------------------------
registered_tools = {}   # name -> callable(args) -> dict
tools_meta = []         # [{"name":..., "args_schema": {...}}, ...]

def _import_tools_package() -> bool:
    """Try 'import tools'; if that fails, load package from TOOLS_DIR."""
    try:
        import tools  # noqa: F401
        return True
    except Exception as e:
        if os.path.isdir(TOOLS_DIR) and os.path.isfile(os.path.join(TOOLS_DIR, "__init__.py")):
            try:
                spec = importlib.util.spec_from_file_location(
                    "tools", os.path.join(TOOLS_DIR, "__init__.py")
                )
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)  # type: ignore[attr-defined]
                sys.modules["tools"] = mod
                print(f"tools_package_loaded_from_path dir={TOOLS_DIR}")
                logger.info("tools_package_loaded_from_path",
                            extra={"custom_dimensions": {"dir": TOOLS_DIR}})
                return True
            except Exception as ee:
                print(f"tools_package_load_failed_from_path dir={TOOLS_DIR} error={ee}")
                logger.exception("tools_package_load_failed_from_path",
                                 extra={"custom_dimensions": {"dir": TOOLS_DIR, "error": str(ee)}})
                return False
        else:
            print(f"tools_dir_missing dir={TOOLS_DIR}")
            logger.warning("tools_dir_missing",
                           extra={"custom_dimensions": {"dir": TOOLS_DIR}})
            return False

def load_tools():
    """Scan tools/ and register modules safely; never crash the app."""
    if not _import_tools_package():
        print("tools_package_import_failed: cannot import 'tools'")
        logger.exception("tools_package_import_failed",
                         extra={"custom_dimensions": {"error": "import failed"}})
        return

    print(f"tools_scan_start dir={TOOLS_DIR}")
    logger.info("tools_scan_start", extra={"custom_dimensions": {"dir": TOOLS_DIR}})

    if not os.path.isdir(TOOLS_DIR):
        print(f"tools_dir_not_found dir={TOOLS_DIR}")
        logger.warning("tools_dir_not_found", extra={"custom_dimensions": {"dir": TOOLS_DIR}})
        return

    for _finder, name, _ispkg in pkgutil.iter_modules([TOOLS_DIR]):
        mod_name = f"tools.{name}"
        try:
            mod = importlib.import_module(mod_name)
        except Exception as e:
            print(f"tools_import_failed module={mod_name} error={e}")
            logger.exception("tools_import_failed",
                             extra={"custom_dimensions": {"module": mod_name, "error": str(e)}})
            continue

        if not hasattr(mod, "register"):
            print(f"tools_register_missing module={mod_name}")
            logger.warning("tools_register_missing",
                           extra={"custom_dimensions": {"module": mod_name}})
            continue

        try:
            spec = mod.register()  # {"name","args_schema","function"}
            name = spec["name"]
            registered_tools[name] = spec["function"]
            tools_meta.append({"name": name, "args_schema": spec.get("args_schema", {})})
            print(f"tools_loaded module={mod_name} name={name}")
            logger.info("tools_loaded",
                        extra={"custom_dimensions": {"module": mod_name, "name": name}})
        except Exception as e:
            print(f"tools_register_failed module={mod_name} error={e}")
            logger.exception("tools_register_failed",
                             extra={"custom_dimensions": {"module": mod_name, "error": str(e)}})

# env escape hatch
if os.getenv("DISABLE_TOOL_SCAN") not in {"1", "true", "True"}:
    load_tools()
else:
    print("tools_scan_disabled=1")
    logger.warning("tools_scan_disabled", extra={"custom_dimensions": {}})

# -----------------------------------------------------------------------------
# JSON-RPC endpoint
# -----------------------------------------------------------------------------
@app.post("/mcp")
async def mcp_endpoint(request: Request):
    start = time.time()
    payload = await request.json()
    method = payload.get("method")
    req_id = str(payload.get("id"))
    params = payload.get("params", {}) or {}
    tool_name = params.get("tool")

    logger.info("mcp_request", extra={"custom_dimensions": {
        "method": method,
        "tool": tool_name or "",
        "id": req_id,
        "client_ip": request.client.host if request.client else "",
        "path": str(request.url.path),
    }})

    try:
        if method == "tool_invoke":
            args = params.get("args", {}) or {}
            if tool_name in registered_tools:
                result = registered_tools[tool_name](args)
            else:
                duration_ms = int((time.time() - start) * 1000)
                logger.warning("mcp_unknown_tool", extra={"custom_dimensions": {
                    "tool": tool_name or "", "id": req_id, "duration_ms": duration_ms
                }})
                return JSONResponse({
                    "jsonrpc": "2.0",
                    "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
                    "id": req_id
                })

            duration_ms = int((time.time() - start) * 1000)
            logger.info("mcp_success", extra={"custom_dimensions": {
                "method": method, "tool": tool_name, "id": req_id, "duration_ms": duration_ms
            }})
            return JSONResponse({"jsonrpc": "2.0", "result": result, "id": req_id})

        elif method == "tools/list":
            result = {"tools": tools_meta}
            duration_ms = int((time.time() - start) * 1000)
            logger.info("mcp_success", extra={"custom_dimensions": {
                "method": method, "tool": "", "id": req_id, "duration_ms": duration_ms
            }})
            return JSONResponse({"jsonrpc": "2.0", "result": result, "id": req_id})

        else:
            duration_ms = int((time.time() - start) * 1000)
            logger.warning("mcp_unknown_method", extra={"custom_dimensions": {
                "method": str(method), "id": req_id, "duration_ms": duration_ms
            }})
            return JSONResponse({"jsonrpc": "2.0",
                                 "error": {"code": -32601, "message": f"Unknown method: {method}"}, "id": req_id})
    except Exception as ex:
        duration_ms = int((time.time() - start) * 1000)
        logger.exception("mcp_exception", extra={"custom_dimensions": {
            "method": method, "tool": tool_name or "", "id": req_id, "duration_ms": duration_ms
        }})
        return JSONResponse({"jsonrpc": "2.0",
                             "error": {"code": -32000, "message": str(ex)}, "id": req_id}, status_code=500)

# -----------------------------------------------------------------------------
# Health & debug endpoints
# -----------------------------------------------------------------------------
@app.get("/healthz")
def healthz():
    return {"ok": True}

@app.get("/debug/tools")
def debug_tools():
    return {
        "registered_tool_names": sorted(list(registered_tools.keys())),
        "tools_meta": tools_meta,
        "count": len(registered_tools),
    }

@app.get("/debug/ls")
def debug_ls():
    base = BASE_DIR
    tools_dir = TOOLS_DIR
    def safe_list(p):
        try:
            return sorted(os.listdir(p))
        except Exception as e:
            return [f"<err: {e}>"]
    return {
        "BASE_DIR": base,
        "BASE_DIR_contents": safe_list(base),
        "TOOLS_DIR": tools_dir,
        "TOOLS_DIR_exists": os.path.isdir(tools_dir),
        "TOOLS_DIR_contents": safe_list(tools_dir),
        "sys.path": sys.path[:20],
    }
