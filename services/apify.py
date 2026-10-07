import os
import requests
from urllib.parse import quote

BASE = "https://api.apify.com/v2"

class ApifyError(RuntimeError):
    pass

def _actor_path(actor_id: str) -> str:
    actor = (actor_id or "").strip()
    if not actor:
        raise ApifyError("No Apify Actor ID is configured for this platform. Open Connection Setup and add the Actor ID.")
    return quote(actor, safe="~")

def run_actor(actor_id: str, run_input: dict, timeout: int = 300):
    token = os.getenv("APIFY_TOKEN", "").strip()
    if not token:
        raise ApifyError("APIFY_TOKEN is missing. Add your Apify API token to .env and restart the app.")

    actor = _actor_path(actor_id)
    url = f"{BASE}/actors/{actor}/run-sync-get-dataset-items"
    try:
        r = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            params={"clean": "true"},
            json=run_input,
            timeout=timeout,
        )
    except requests.Timeout as exc:
        raise ApifyError(f"Apify timed out after {timeout}s. The Actor may still be running; try a smaller item limit.") from exc
    except requests.RequestException as exc:
        raise ApifyError(f"Could not reach Apify: {exc}") from exc

    if r.status_code >= 400:
        try:
            body = r.json()
            detail = body.get("error", {}).get("message") or body.get("message") or str(body)
        except ValueError:
            detail = r.text[:1200].replace("\n", " ")
        raise ApifyError(f"Apify returned HTTP {r.status_code}: {detail}")

    try:
        data = r.json()
    except ValueError as exc:
        raise ApifyError("Apify returned invalid JSON. Open the Actor in Apify Console and confirm it writes results to the default Dataset.") from exc

    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if "items" in data and isinstance(data["items"], list):
            return data["items"]
        # Some Actors return a single object as the dataset item.
        return [data]
    raise ApifyError("Apify returned an unexpected result format.")
