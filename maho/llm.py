"""OpenAI Responses API with structured outputs and explicit refusal handling."""

import copy

from .api import AssemblyAI

OPENAI_URL = "https://api.openai.com/v1"


def supported_schema(schema):
    """Keep local minLength checks; omit unsupported string length keywords on the wire."""
    result = copy.deepcopy(schema)

    def visit(node):
        if isinstance(node, dict):
            node.pop("minLength", None)
            node.pop("maxLength", None)
            for child in node.values():
                visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(result)
    return result


class OpenAILLM(AssemblyAI):
    provider_name = "OpenAI"
    cache_identity = {"provider": "openai", "api": "responses", "adapter_version": 3}

    def __init__(self, key):
        super().__init__(key)
        self.session.headers["authorization"] = f"Bearer {key}"

    def complete(self, body):
        config = body["response_format"]["json_schema"]
        request = {"model": body["model"], "input": body["messages"], "store": False,
                   "max_output_tokens": max(body.get("output_budget", 32768), body["max_tokens"] + 4096),
                   "text": {"format": {"type": "json_schema", "name": config["name"],
                                        "strict": True, "schema": supported_schema(config["schema"])}}}
        if body["model"].startswith(("gpt-5", "gpt-6")):
            default_effort = "high" if body["model"].startswith("gpt-6") else "low"
            request["reasoning"] = {"effort": body.get("reasoning_effort", default_effort)}
        response = self.request("POST", f"{OPENAI_URL}/responses", json=request, timeout=(15, 900))
        content = []
        refusal = None
        for item in response.get("output", []):
            if item.get("type") == "message":
                for part in item.get("content", []):
                    if part.get("type") == "output_text":
                        content.append(part["text"])
                    elif part.get("type") == "refusal":
                        refusal = part.get("refusal", "Request refused.")
        if refusal:
            finish = "content_filter"
        elif response.get("status") != "completed":
            finish = "length" if response.get("status") == "incomplete" else "error"
        else:
            finish = "stop"
        return {"request_id": response.get("request_id"), "response_id": response.get("id"),
                "usage": response.get("usage"), "raw_response": response,
                "choices": [{"finish_reason": finish, "message": {"content": "".join(content),
                                                                        "refusal": refusal}}]}

    def check_model(self, model):
        return self.request("GET", f"{OPENAI_URL}/models/{model}")
