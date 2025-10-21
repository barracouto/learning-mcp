import time
import openai
from openai.error import OpenAIError, RateLimitError
from runtime import load_openai_from_kv, configure_azure_openai, log_dependency

def register():
    def handler(args: dict) -> dict:
        # 1) Secrets & configure client
        try:
            endpoint, key = load_openai_from_kv()
        except Exception as e:
            return {"error": f"Key Vault access failed: {e.__class__.__name__}: {str(e)}"}
        configure_azure_openai(endpoint, key)

        # 2) Args
        prompt = args.get("prompt", "Hello!")
        deployment = args.get("deployment", "steph-learning-mcp-gpt-4.1")
        temperature = float(args.get("temperature", 0.7))
        max_tokens = int(args.get("max_tokens", 256))

        # 3) Call model + breadcrumb
        try:
            t0 = time.time()
            resp = openai.ChatCompletion.create(
                engine=deployment,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=30,
            )
            latency_ms = int((time.time() - t0) * 1000)
            log_dependency("dep_openai_chat", {
                "model_deployment": deployment,
                "latency_ms": latency_ms,
                "prompt_chars": len(prompt),
            })
            content = resp["choices"][0]["message"]["content"]
            return {"response": content, "latency_ms": latency_ms, "deployment": deployment}
        except RateLimitError:
            return {"error": "Throttled by Azure OpenAI. Try again shortly."}
        except OpenAIError as e:
            return {"error": f"OpenAI API error: {e}"}
        except Exception as e:
            return {"error": f"Unexpected error: {e.__class__.__name__}: {str(e)}"}

    return {
        "name": "complete_prompt",
        "args_schema": {"prompt": "string"},
        "function": handler,
    }
