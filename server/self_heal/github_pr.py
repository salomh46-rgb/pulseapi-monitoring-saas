import os
import httpx
from typing import Optional, Dict, Any

async def create_self_healing_pr(
    repo: str,
    incident_id: int,
    patch_diff: str,
    root_cause: str,
    target_file: str,
    token: Optional[str] = None
) -> Dict[str, Any]:
    github_token = token or os.getenv("GITHUB_TOKEN", "")
    branch_name = f"pulsefix/incident-{incident_id}"

    if not github_token or "/" not in repo:
        # Simulation / Local mode
        simulated_url = f"https://github.com/{repo if '/' in repo else 'salomh46-rgb/pulseapi-demo'}/pull/{incident_id + 100}"
        return {
            "status": "SIMULATED_PR",
            "pr_url": simulated_url,
            "branch": branch_name,
            "title": f"fix(pulsefix): auto-heal incident #{incident_id} in {target_file}",
            "body": f"### 🧠 PulseFix Autonomous Root Cause Analysis\n\n**Diagnosis:** {root_cause}\n\n**Target File:** `{target_file}`\n\n```diff\n{patch_diff}\n```\n\n*Generated automatically by PulseFix SRE Engine.*"
        }

    headers = {
        "Authorization": f"Bearer {github_token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28"
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # 1. Get default branch SHA
            repo_res = await client.get(f"https://api.github.com/repos/{repo}", headers=headers)
            if repo_res.status_code != 200:
                raise Exception(f"Failed to fetch repo: {repo_res.text}")
            default_branch = repo_res.json().get("default_branch", "main")

            ref_res = await client.get(f"https://api.github.com/repos/{repo}/git/ref/heads/{default_branch}", headers=headers)
            base_sha = ref_res.json()["object"]["sha"]

            # 2. Create branch
            create_branch_res = await client.post(
                f"https://api.github.com/repos/{repo}/git/refs",
                headers=headers,
                json={"ref": f"refs/heads/{branch_name}", "sha": base_sha}
            )

            # 3. Create Pull Request
            pr_title = f"fix(pulsefix): auto-resolve incident #{incident_id} in {target_file}"
            pr_body = f"""## 🚨 PulseFix Self-Healing Incident Report #{incident_id}

### 🧠 Root Cause Diagnosis
{root_cause}

### 🛠️ Proposed Fix Patch
```diff
{patch_diff}
```

*Diagnosed and opened autonomously by [PulseFix SaaS](https://github.com/salomh46-rgb/pulseapi-monitoring).*
"""
            pr_res = await client.post(
                f"https://api.github.com/repos/{repo}/pulls",
                headers=headers,
                json={
                    "title": pr_title,
                    "body": pr_body,
                    "head": branch_name,
                    "base": default_branch
                }
            )

            if pr_res.status_code in (201, 200):
                pr_data = pr_res.json()
                return {
                    "status": "PR_OPENED",
                    "pr_url": pr_data["html_url"],
                    "pr_number": pr_data["number"],
                    "branch": branch_name,
                    "title": pr_title
                }
            else:
                return {
                    "status": "BRANCH_CREATED_PR_PENDING",
                    "branch": branch_name,
                    "error": pr_res.text
                }
    except Exception as e:
        return {
            "status": "ERROR",
            "error": str(e),
            "branch": branch_name,
            "fallback_patch": patch_diff
        }
