from .registry import registry
import json
import math

CALCULATOR_SCHEMA = {
    "type": "object",
    "properties": {
        "expression": {
            "type": "string",
            "description": "数学表达式，如 '2+3*4' 或 'sqrt(16)'"
        }
    },
    "required": ["expression"]
}

def calculator(expression: str) -> str:
    safe_dict = {
        "abs": abs, "round": round, "min": min, "max": max,
        "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos,
        "log": math.log, "pi": math.pi, "e": math.e,
        "pow": pow, "int": int, "float": float
    }
    try:
        result = eval(expression, {"__builtins__": {}}, safe_dict)
        return json.dumps({"expression": expression, "result": result})
    except Exception as e:
        return json.dumps({"error": str(e)})

registry.register(
    name="calculator",
    description="安全地计算数学表达式。支持 +, -, *, /, **, sqrt, sin, cos, log, pi 等",
    parameters=CALCULATOR_SCHEMA,
    handler=calculator
)