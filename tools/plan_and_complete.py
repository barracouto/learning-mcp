# tools/plan_and_complete.py
import time

# We will *reuse* your existing complete_prompt tool for both planning and execution
# so that secrets, OpenAI config, telemetry, and error handling are centralized.
from tools import complete_prompt  # this module already exists in your repo

def register():
    def handler(args: dict) -> dict:
        # Inputs
        goal = args.get("goal", "Explain a fun space fact.")
        deployment = args.get("deployment", "steph-learning-mcp-gpt-4.1")
        temperature = float(args.get("temperature", 0.4))
        max_tokens = int(args.get("max_tokens", 256))

        # 1) Ask the model to produce ONE next step (use complete_prompt under the hood)
        plan_prompt = (
            "You are a planner. Given the user's goal below, propose exactly one specific "
            "next step as a short imperative sentence (10–20 words). "
            "Do NOT execute it, only propose it.\n\n"
            f"Goal: {goal}"
        )
        t0 = time.time()
        plan_func = complete_prompt.register()["function"]
        plan_resp = plan_func({
            "prompt": plan_prompt,
            "deployment": deployment,
            "temperature": temperature,
            "max_tokens": 128
        })
        latency_plan_ms = int((time.time() - t0) * 1000)

        # Handle errors from complete_prompt
        if isinstance(plan_resp, dict) and plan_resp.get("error"):
            return {"error": f"Planning failed: {plan_resp['error']}"}

        plan_step = (plan_resp.get("response") or "").strip()

        # 2) Execute that step by asking the same model to "do it" (again via complete_prompt)
        exec_prompt = f"Execute this instruction and return the result only:\n\n{plan_step}"
        t1 = time.time()
        exec_resp = plan_func({
            "prompt": exec_prompt,
            "deployment": deployment,
            "temperature": temperature,
            "max_tokens": max_tokens
        })
        latency_exec_ms = int((time.time() - t1) * 1000)

        if isinstance(exec_resp, dict) and exec_resp.get("error"):
            return {"error": f"Execution failed: {exec_resp['error']}", "plan_step": plan_step}

        result = exec_resp.get("response", "")

        return {
            "goal": goal,
            "plan_step": plan_step,
            "result": result,
            "timings_ms": {"plan": latency_plan_ms, "exec": latency_exec_ms},
            "deployment": deployment
        }

    return {
        "name": "plan_and_complete",
        "args_schema": {
            "goal": "string",
            "deployment": "string",
            "temperature": "number",
            "max_tokens": "number"
        },
        "function": handler,
    }
