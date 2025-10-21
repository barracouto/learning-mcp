# tools/wholesome_agent.py
import json, time, hashlib
from typing import List
from runtime import load_openai_from_kv, configure_azure_openai, log_dependency
from tools._agent_store import MEMORY   # shared short-term store
import openai

SYSTEM_PLANNER = (
    "You are a planning module for a wholesome-facts agent.\n"
    "Given a user subject (may be blank), produce a JSON plan with:\n"
    '{"theme":"string","subtopics":["string","string","string"]}\n'
    "Rules:\n"
    "- Keep things wholesome, kind, suitable for all ages.\n"
    "- If subject is empty, pick a cheerful theme and three varied subtopics.\n"
    "- If subject is provided, keep theme aligned and subtopics specific.\n"
    "- No extra text—return strict JSON only."
)

SYSTEM_EXECUTOR = (
    "You are an execution module for a wholesome-facts agent.\n"
    "Given a theme and subtopics, generate exactly three uplifting, wholesome facts.\n"
    "Return strict JSON only: {\"facts\":[\"...\",\"...\",\"...\"]}\n"
    "Each fact must be concise (1–2 sentences), safe, and positive.\n"
)

def _hash_fact(s: str) -> str:
    return hashlib.sha1(s.strip().lower().encode("utf-8")).hexdigest()

def _recent_hashes(n: int = 50) -> set:
    # store recent fact hashes in MEMORY under a namespaced key
    key = "__wholesome_recent__"
    entry = next((x for x in MEMORY if isinstance(x, dict) and x.get("key")==key), None)
    if entry is None:
        entry = {"key": key, "hashes": []}
        MEMORY.append(entry)
    return set(entry["hashes"])

def _remember_hashes(new_hashes: List[str], max_keep: int = 200):
    key = "__wholesome_recent__"
    entry = next((x for x in MEMORY if isinstance(x, dict) and x.get("key")==key), None)
    if entry is None:
        entry = {"key": key, "hashes": []}
        MEMORY.append(entry)
    entry["hashes"] = (entry["hashes"] + list(new_hashes))[-max_keep:]

def register():
    def handler(args: dict) -> dict:
        subject = (args.get("subject") or "").strip()
        deployment = args.get("deployment", "steph-learning-mcp-gpt-4.1")
        t_plan = float(args.get("planner_temperature", 0.3))
        t_exec = float(args.get("executor_temperature", 0.4))

        # --- Configure AOAI ---
        endpoint, key = load_openai_from_kv()
        configure_azure_openai(endpoint, key)

        # ---------- PLAN ----------
        user_plan = {
            "subject": subject,
            "instruction": (
                'Return only JSON like {"theme":"...","subtopics":["...","...","..."]}'
            ),
        }
        t0 = time.time()
        plan_resp = openai.ChatCompletion.create(
            engine=deployment,
            messages=[
                {"role":"system","content": SYSTEM_PLANNER},
                {"role":"user","content": json.dumps(user_plan)}
            ],
            temperature=t_plan,
            max_tokens=160,
            timeout=30
        )
        plan_latency = int((time.time()-t0)*1000)
        log_dependency("dep_openai_chat", {
            "model_deployment": deployment, "latency_ms": plan_latency, "kind":"wholesome_plan"
        })

        # Parse plan JSON defensively
        try:
            plan_text = plan_resp["choices"][0]["message"]["content"].strip()
            plan = json.loads(plan_text)
            theme = str(plan.get("theme") or (subject or "Random Wholesome"))
            subs = plan.get("subtopics") or []
            subtopics = [str(s).strip() for s in subs][:3]
            # pad if needed
            while len(subtopics) < 3:
                subtopics.append("general kindness")
        except Exception:
            theme = subject or "Random Wholesome"
            subtopics = ["kind animals", "nature’s calm", "everyday acts of kindness"]

        # ---------- EXECUTE ----------
        exec_payload = {"theme": theme, "subtopics": subtopics}
        t1 = time.time()
        exec_resp = openai.ChatCompletion.create(
            engine=deployment,
            messages=[
                {"role":"system","content": SYSTEM_EXECUTOR},
                {"role":"user","content": json.dumps(exec_payload)}
            ],
            temperature=t_exec,
            max_tokens=320,
            timeout=30
        )
        exec_latency = int((time.time()-t1)*1000)
        log_dependency("dep_openai_chat", {
            "model_deployment": deployment, "latency_ms": exec_latency, "kind":"wholesome_execute"
        })

        # Parse facts JSON and de-duplicate against recent memory
        facts = []
        try:
            data = json.loads(exec_resp["choices"][0]["message"]["content"].strip())
            facts = [str(x).strip() for x in (data.get("facts") or []) if str(x).strip()]
        except Exception:
            facts = []

        # normalize to exactly 3 and avoid recent repeats
        recent = _recent_hashes()
        cleaned = []
        for f in facts:
            if _hash_fact(f) not in recent:
                cleaned.append(f)
            if len(cleaned) == 3:
                break
        # backfill if short
        while len(cleaned) < 3:
            cleaned.append("Smiling—even briefly—can lift your mood through a small burst of dopamine and endorphins.")

        _remember_hashes([_hash_fact(f) for f in cleaned])

        return {
            "subject": subject or "random",
            "plan": {"theme": theme, "subtopics": subtopics},
            "facts": cleaned,
            "timings_ms": {"plan": plan_latency, "execute": exec_latency},
            "deployment": deployment
        }

    return {
        "name": "wholesome_agent",
        "args_schema": {
            "subject":"string",
            "deployment":"string",
            "planner_temperature":"number",
            "executor_temperature":"number"
        },
        "function": handler,
    }
