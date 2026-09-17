import os
import json
import re
import httpx
from typing import Optional, Dict, Any

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

HEURISTIC_PATTERNS = [
    {
        "pattern": r"KeyError:\s*['\"](\w+)['\"]",
        "cause": "Dictionary key lookup failed: key '{match}' does not exist in request payload or state dict.",
        "fix_template": "    # PulseFix: Safely get key with fallback\n-   val = data['{match}']\n+   val = data.get('{match}', None)"
    },
    {
        "pattern": r"TypeError:\s*'NoneType'\s*object\s*is\s*not\s*subscriptable",
        "cause": "Attempted to access property on a None object. Database query returned null or external service failed.",
        "fix_template": "    # PulseFix: Check for null before subscripting\n-   item = record['id']\n+   item = record['id'] if record is not None else None"
    },
    {
        "pattern": r"ZeroDivisionError:\s*division\s*by\s*zero",
        "cause": "Mathematical division by zero in latency/percentage calculation.",
        "fix_template": "    # PulseFix: Guard against division by zero\n-   rate = total / count\n+   rate = total / count if count > 0 else 0.0"
    },
    {
        "pattern": r"(?:HTTP\s*500|Internal\s*Server\s*Error)",
        "cause": "Unhandled exception in endpoint controller. Service returned HTTP 500.",
        "fix_template": "    # PulseFix: Wrap critical path in exception handler\n+   try:\n        res = await process_request()\n+   except Exception as e:\n+       logger.error(f'Handled incident: {e}')\n+       return Response(status_code=503, content='Service Temporarily Degraded')"
    }
]

def heuristic_analysis(error_payload: str, recent_diff: Optional[str] = None) -> Dict[str, Any]:
    file_match = re.search(r'File "([^"]+)", line (\d+), in (\w+)', error_payload)
    target_file = file_match.group(1) if file_match else "server/api_handler.py"
    faulty_line = int(file_match.group(2)) if file_match else 42
    func_name = file_match.group(3) if file_match else "handle_request"

    # Match common error signatures
    matched_cause = "Unknown runtime exception encountered during execution."
    patch_snippet = "    # PulseFix: General guard patch\n+   if not payload: return None"

    for entry in HEURISTIC_PATTERNS:
        m = re.search(entry["pattern"], error_payload, re.IGNORECASE)
        if m:
            match_str = m.group(1) if m.groups() else ""
            matched_cause = entry["cause"].replace("{match}", match_str)
            patch_snippet = entry["fix_template"].replace("{match}", match_str)
            break

    unified_diff = f"""--- a/{target_file}
+++ b/{target_file}
@@ -{faulty_line},5 +{faulty_line},6 @@ def {func_name}():
{patch_snippet}
"""

    return {
        "root_cause": matched_cause,
        "target_file": target_file,
        "faulty_line": faulty_line,
        "suggested_patch": unified_diff.strip(),
        "confidence": 0.88,
        "model_used": "heuristic-engine"
    }

async def analyze_incident(error_payload: str, recent_diff: Optional[str] = None, service_name: str = "API Service") -> Dict[str, Any]:
    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        return heuristic_analysis(error_payload, recent_diff)

    prompt = f"""You are an elite autonomous Site Reliability Engineer (SRE) and AI DevOps expert.
An incident occurred in service '{service_name}'.
Analyze the following error stack trace and recent Git commit diff to find the exact root cause and generate a production-ready unified diff fix patch.

--- ERROR TRACEBACK / PAYLOAD ---
{error_payload}

--- RECENT GIT COMMIT DIFF ---
{recent_diff or "No git diff available; diagnose from traceback alone."}

Return a valid JSON object ONLY with this exact schema:
{{
  "root_cause": "Clear 1-2 sentence explanation of why this broke",
  "target_file": "path/to/broken_file.py",
  "faulty_line": 123,
  "suggested_patch": "--- a/path/to/file\\n+++ b/path/to/file\\n@@ ... @@\\n...",
  "confidence": 0.95
}}
Do NOT wrap in markdown quotes. Return raw JSON.
"""

    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"}
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            res = await client.post(url, headers=headers, json=body)
            if res.status_code == 200:
                data = res.json()
                text = data["candidates"][0]["content"]["parts"][0]["text"]
                parsed = json.loads(text)
                parsed["model_used"] = "gemini-2.5-flash"
                return parsed
    except Exception as e:
        print(f"Gemini analysis fallback to heuristic: {e}")

    return heuristic_analysis(error_payload, recent_diff)
