def register():
    def handler(args: dict) -> dict:
        name = args.get("name", "world")
        return {"greeting": f"Hello, {name}!"}
    return {
        "name": "say_hello",
        "args_schema": {"name": "string"},
        "function": handler,
    }
