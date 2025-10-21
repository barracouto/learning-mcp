from tools._agent_store import MEMORY
def register():
    def handler(args: dict) -> dict:
        limit = int(args.get("limit", 20))
        return {"count": len(MEMORY), "items": MEMORY[-limit:]}
    return {"name":"agent_memory_dump","args_schema":{"limit":"number"},"function":handler}
