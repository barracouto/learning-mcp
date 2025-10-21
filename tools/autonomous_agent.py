# tools/autonomous_agent.py
from tools._agent_store import MEMORY
import time
from runtime import load_openai_from_kv, configure_azure_openai  # shared helpers
import openai


def register():
    def handler(args: dict) -> dict:
        # --- Configure Azure OpenAI from Key Vault ---
        endpoint, key = load_openai_from_kv()
        configure_azure_openai(endpoint, key)

        # --- Inputs ---
        goal = args.get("goal", "Gather three surprising facts about lavender cultivation.")
        max_steps = int(args.get("max_steps", 3))
        deployment = args.get("deployment", "steph-learning-mcp-gpt-4.1")

        steps_run = 0
        transcript = []
        done = False

        while steps_run < max_steps and not done:
            # 1) PLAN — use short, “one-step” instruction; consider recent memory
            context = "\n".join([f"- {m}" for m in MEMORY[-5:]]) or "(no prior memory)"
            plan_prompt = f"""
You are a planner in an agent loop.
Goal: {goal}
Recent memory:
{context}

Propose ONE next step (imperative). If goal appears satisfied, respond exactly 'DONE'.
""".strip()

            plan_resp = openai.ChatCompletion.create(
                engine=deployment,
                messages=[{"role": "user", "content": plan_prompt}],
                temperature=0.2,
                max_tokens=100,
                timeout=30,
            )
            step = plan_resp["choices"][0]["message"]["content"].strip()
            if step.upper().startswith("DONE"):
                done = True
                transcript.append({"plan_step": "DONE", "result": "(no further action)"})
                break

            # 2) EXECUTE — ask the model to perform the step; return only the result
            exec_prompt = f"Execute this instruction and return the result only:\n\n{step}"
            exec_resp = openai.ChatCompletion.create(
                engine=deployment,
                messages=[{"role": "user", "content": exec_prompt}],
                temperature=0.4,
                max_tokens=300,
                timeout=30,
            )
            result = exec_resp["choices"][0]["message"]["content"]

            # 3) MEMORY — keep a short rolling summary
            MEMORY.append(f"Step: {step} | Result: {result[:200]}")
            transcript.append({"plan_step": step, "result": result})
            steps_run += 1

        return {
            "goal": goal,
            "steps_run": steps_run,
            "done": done,
            "transcript": transcript,
            "memory_size": len(MEMORY),
        }

    return {
        "name": "autonomous_agent",
        "args_schema": {"goal": "string", "max_steps": "number", "deployment": "string"},
        "function": handler,
    }
