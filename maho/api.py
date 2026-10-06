"""Direct AssemblyAI HTTP calls; only safe read requests retry automatically."""

import time

import requests

STT_URL = "https://api.assemblyai.com/v2"
LLM_URL = "https://llm-gateway.assemblyai.com/v1"


class AssemblyAI:
    provider_name = "AssemblyAI"

    def __init__(self, key: str):
        self.key = key
        self.session = requests.Session()
        self.session.headers.update({"authorization": key})

    def request(self, method: str, url: str, **kwargs) -> dict:
        retries = 4 if method == "GET" else 1
        timeout = kwargs.pop("timeout", (15, 300))
        for attempt in range(retries):
            try:
                response = self.session.request(method, url, timeout=timeout, **kwargs)
            except requests.RequestException:
                if attempt + 1 < retries:
                    time.sleep(2 ** attempt)
                    continue
                raise RuntimeError(f"{self.provider_name} connection failed. Rerun to resume saved work. "
                                   "POST requests are not retried automatically because they may incur charges.") from None
            if response.status_code == 429 or response.status_code >= 500:
                if attempt + 1 < retries:
                    time.sleep(min(30, 2 ** attempt))
                    continue
            if not response.ok:
                try:
                    body = response.json()
                    detail = str(body.get("error", body.get("message", "Request rejected")))
                    errors = body.get("metadata", {}).get("errors", [])
                    if errors:
                        detail += ": " + "; ".join(str(error) for error in errors)
                    if body.get("request_id"):
                        detail += f" (request_id: {body['request_id']})"
                except (ValueError, AttributeError):
                    detail = "Request rejected"
                detail = detail.replace(self.key, "[REDACTED]")[:400]
                raise RuntimeError(f"{self.provider_name} HTTP {response.status_code}: {detail}")
            try:
                result = response.json()
            except ValueError:
                raise RuntimeError(f"{self.provider_name} returned invalid JSON.") from None
            if not isinstance(result, dict):
                raise RuntimeError(f"{self.provider_name} returned an unexpected response shape.")
            if "request_id" not in result and response.headers.get("x-request-id"):
                result["request_id"] = response.headers["x-request-id"]
            return result
        raise RuntimeError("AssemblyAI request failed.")

    def upload(self, path):
        with path.open("rb") as audio:
            result = self.request("POST", f"{STT_URL}/upload", data=audio,
                                  headers={"content-type": "application/octet-stream"})
        return result["upload_url"]

    def submit(self, audio_url, speech_models, language):
        body = {"audio_url": audio_url, "speech_models": speech_models,
                "speaker_labels": True, "punctuate": True, "format_text": True}
        if language:
            body["language_code"] = language
        else:
            body["language_detection"] = True
        return self.request("POST", f"{STT_URL}/transcript", json=body)

    def transcript(self, transcript_id):
        return self.request("GET", f"{STT_URL}/transcript/{transcript_id}")

    def complete(self, body):
        body = {k: v for k, v in body.items() if k not in ("reasoning_effort", "output_budget")}
        return self.request("POST", f"{LLM_URL}/chat/completions", json=body)

    def models(self):
        return self.request("GET", f"{LLM_URL}/models")
