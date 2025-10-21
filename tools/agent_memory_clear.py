from tools._agent_store import MEMORY
def register():
    def handler(args: dict) -> dict:
        MEMORY.clear()
        return {"cleared": True, "count": 0}
    return {"name":"agent_memory_clear","args_schema":{},"function":handler}
