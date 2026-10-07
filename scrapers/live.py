import os, json, re
from services.apify import run_actor
from services.analytics import normalize, normalize_linkedin, _followers_from


def _url_or_username(ref):
    ref = ref.strip()
    return ref if ref.startswith("http") else ref.lstrip("@").strip("/")


def _template_env(name, default):
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} must contain valid JSON. Check .env.") from exc


def _render(obj, ref, limit):
    ref = ref.strip()
    username = ref.lstrip("@").strip("/").split("/")[-1]
    url = ref if ref.startswith("http") else ""
    if not url:
        url = f"https://www.instagram.com/{username}/"
    limit = int(limit)
    tokens = {"{reference}": ref, "{reference_url}": url, "{username}": username, "{limit}": str(limit)}
    if isinstance(obj, str):
        if obj.strip() == "{limit}":
            return limit
        out = obj
        for a, b in tokens.items():
            out = out.replace(a, b)
        try:
            parsed = json.loads(out)
        except Exception:
            return out
        # The top-level template is always JSON *text* (see _template_env), so it
        # always lands here first. Without this recursive call, a placeholder like
        # "resultsLimit": "{limit}" comes back as the STRING "10" and the dict-branch
        # below (which forces known limit/count keys back to int) never runs,
        # because we already returned. Recurse so that pass still applies.
        return _render(parsed, ref, limit) if isinstance(parsed, (dict, list)) else parsed
    if isinstance(obj, dict):
        rendered = {k: _render(v, ref, limit) for k, v in obj.items()}
        for key in ("resultsLimit", "maxItems", "limit", "limitPerSource", "maxResults", "itemsLimit", "postsLimit", "maxPosts", "totalPostsPerProfile"):
            if key in rendered:
                try:
                    rendered[key] = int(rendered[key])
                except (TypeError, ValueError):
                    pass
        return rendered
    if isinstance(obj, list):
        return [_render(v, ref, limit) for v in obj]
    return obj


def instagram(ref, limit=25):
    """Fetch Instagram posts plus the profile row that carries follower counts.

    `resultsType: posts` must be explicit, and `addParentData` is what makes the
    actor attach owner/profile fields (followersCount) to every post row. Without
    it, follower counts are absent and engagement rate collapses to 0.
    """
    default = {
        "directUrls": ["{reference_url}"],
        "resultsType": "posts",
        "resultsLimit": "{limit}",
        "addParentData": True,
    }
    actor = os.getenv("INSTAGRAM_ACTOR_ID", "apify/instagram-scraper")
    inp = _render(_template_env("INSTAGRAM_INPUT_TEMPLATE", json.dumps(default)), ref, limit)
    raw = run_actor(actor, inp)
    records = normalize("instagram", raw, ref)[1]

    # If follower data never arrived (actor ignored addParentData, or the profile
    # row was not emitted), fetch profile details once and backfill.
    if records and not any(r.get("followers") for r in records):
        try:
            details = run_actor(actor, _render(
                {"directUrls": ["{reference_url}"], "resultsType": "details", "resultsLimit": 1},
                ref, 1))
            followers = 0
            for row in details if isinstance(details, list) else []:
                followers = max(followers, _followers_from(row))
            if followers:
                for r in records:
                    r["followers"] = followers
                    if not r.get("views") and followers:
                        r["engagement_rate"] = round(r["interactions"] / followers * 100, 2)
        except Exception:
            pass
    return records


def x(ref, limit=25):
    u = _url_or_username(ref).split("?")[0].rstrip("/").split("/")[-1]
    default = {"twitterHandles": [u], "maxItems": limit, "sort": "Latest"}
    actor = os.getenv("X_ACTOR_ID", "apidojo/tweet-scraper")
    inp = _render(_template_env("X_INPUT_TEMPLATE", json.dumps(default)), ref, limit)
    raw = run_actor(actor, inp)
    return normalize("x", raw, ref)[1]


def _linkedin_url(ref):
    ref = ref.strip()
    if ref.startswith("http"):
        return ref
    username = ref.lstrip("@").strip("/")
    if "/in/" in username:
        username = username.split("/in/")[-1].strip("/")
    return f"https://www.linkedin.com/in/{username}/"


def linkedin(ref, limit=25):
    """Fetch LinkedIn profile + post data with sane defaults for current Apify Actors.

    The preferred configuration uses two public, no-cookie Actors:
    - harvestapi/linkedin-profile-scraper for profile/follower data
    - data-slayer/linkedin-profile-posts-scraper for post/engagement data

    A legacy LINKEDIN_ACTOR_ID and custom LINKEDIN_INPUT_TEMPLATE remain supported.
    """
    url = _linkedin_url(ref)
    custom = os.getenv("LINKEDIN_INPUT_TEMPLATE", "").strip()
    legacy_actor = os.getenv("LINKEDIN_ACTOR_ID", "").strip()

    if custom:
        actor = legacy_actor or "data-slayer/linkedin-profile-posts-scraper"
        inp = _render(_template_env("LINKEDIN_INPUT_TEMPLATE", json.dumps({"profileUrls": ["{reference_url}"], "maxPosts": "{limit}"})), ref, limit)
        raw = run_actor(actor, inp)
        return normalize("linkedin", raw, ref)[1]

    profile_actor_env = os.getenv("LINKEDIN_PROFILE_ACTOR_ID", "").strip()
    posts_actor_env = os.getenv("LINKEDIN_POSTS_ACTOR_ID", "").strip()
    profile_actor = profile_actor_env or "harvestapi/linkedin-profile-scraper"
    posts_actor = posts_actor_env or "harvestapi/linkedin-profile-posts"

    # If the user has only the legacy single-Actor setting, keep honoring it instead
    # of silently switching to a different scraper.
    if legacy_actor and not profile_actor_env and not posts_actor_env and "curious_coder/linkedin-profile-scraper" not in legacy_actor:
        custom_input = _render(_template_env("LINKEDIN_INPUT_TEMPLATE", json.dumps({"profileUrls": ["{reference_url}"], "maxPosts": "{limit}"})), ref, limit)
        raw = run_actor(legacy_actor, custom_input)
        return normalize("linkedin", raw, ref)[1]

    # Preserve support for the older Curious Coder actor, which requires a userAgent
    # and proxy object in its current input schema.
    if legacy_actor and "curious_coder/linkedin-profile-scraper" in legacy_actor:
        ua = os.getenv("LINKEDIN_USER_AGENT", "").strip()
        if not ua:
            raise RuntimeError("Your configured LinkedIn Actor is curious_coder/linkedin-profile-scraper, which currently requires LINKEDIN_USER_AGENT and proxy settings. Either add those values to .env or switch LINKEDIN_ACTOR_ID to a no-cookie Actor such as harvestapi/linkedin-profile-scraper.")
        proxy_raw = os.getenv("LINKEDIN_PROXY", '{"useApifyProxy":true,"apifyProxyCountry":"US"}').strip()
        try:
            proxy = json.loads(proxy_raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("LINKEDIN_PROXY must be valid JSON.") from exc
        inp = {
            "urls": [url],
            "userAgent": ua,
            "scrapeCompany": False,
            "minDelay": 5,
            "maxDelay": 30,
            "proxy": proxy,
            "findContacts": False,
        }
        raw = run_actor(legacy_actor, inp)
        return normalize_linkedin(raw, [], ref)

    # Preferred current setup: dedicated profile actor + dedicated post actor.
    if profile_actor == "harvestapi/linkedin-profile-scraper":
        profile_input = {
            "profileScraperMode": "Profile details no email ($4 per 1k)",
            "queries": [url],
        }
    else:
        # Common no-cookie profile actor shape; can still be overridden with
        # LINKEDIN_PROFILE_INPUT_TEMPLATE for a different Actor.
        profile_input = _render(_template_env("LINKEDIN_PROFILE_INPUT_TEMPLATE", json.dumps({"queries": ["{reference_url}"]})), ref, 1)

    posts_input = {"profileUrls": [url], "maxPosts": int(limit)}
    if os.getenv("LINKEDIN_POSTS_INPUT_TEMPLATE", "").strip():
        posts_input = _render(_template_env("LINKEDIN_POSTS_INPUT_TEMPLATE", json.dumps(posts_input)), ref, limit)

    # Run both actors independently. A failure in one must not discard the other's
    # data — previously a posts-actor error meant the whole LinkedIn run returned
    # nothing at all.
    profile_raw, posts_raw = [], []
    profile_err = posts_err = None
    try:
        profile_raw = run_actor(profile_actor, profile_input)
    except Exception as exc:
        profile_err = exc
    try:
        posts_raw = run_actor(posts_actor, posts_input)
    except Exception as exc:
        posts_err = exc

    if not profile_raw and not posts_raw:
        detail = posts_err or profile_err
        raise RuntimeError(
            f"LinkedIn fetch failed. Profile actor '{profile_actor}': "
            f"{profile_err or 'no data'}. Posts actor '{posts_actor}': {posts_err or 'no data'}. "
            "Confirm both Actor IDs exist in your Apify account and that the profile is public."
            if detail else
            "LinkedIn returned no data. The profile may be private or expose no public activity."
        )
    return normalize_linkedin(profile_raw, posts_raw, ref)


def youtube(ref, limit=10, comments_per_video=0):
    import requests
    key = os.getenv("YOUTUBE_API_KEY", "").strip()
    if not key:
        raise RuntimeError("YOUTUBE_API_KEY is missing. Add it to .env and restart the app.")
    base = "https://www.googleapis.com/youtube/v3"

    def get(endpoint, **params):
        params["key"] = key
        try:
            r = requests.get(f"{base}/{endpoint}", params=params, timeout=30)
        except requests.RequestException as exc:
            raise RuntimeError(f"YouTube request failed: {exc}") from exc
        if r.status_code >= 400:
            raise RuntimeError(f"YouTube API {r.status_code}: {r.text[:700]}")
        return r.json()

    ref = ref.strip()
    channel_params = {"part": "snippet,statistics,contentDetails"}
    m = re.search(r"/channel/(UC[\w-]{20,})", ref)
    if m:
        channel_params["id"] = m.group(1)
    elif re.fullmatch(r"UC[\w-]{20,}", ref):
        channel_params["id"] = ref
    else:
        channel_params["forHandle"] = ref.lstrip("@").split("?")[0].split("/")[-1]
    data = get("channels", **channel_params)
    items = data.get("items", [])
    if not items:
        raise RuntimeError("YouTube channel not found. Use @handle, a channel URL, or a channel ID.")
    ch = items[0]
    upload = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    pis = get("playlistItems", part="contentDetails,snippet", playlistId=upload, maxResults=min(limit, 50)).get("items", [])
    ids = [x["contentDetails"]["videoId"] for x in pis]
    if not ids:
        return [], ch
    vids = get("videos", part="snippet,statistics", id=','.join(ids), maxResults=50).get("items", [])
    comments_by = {}
    for v in vids:
        comments_by[v["id"]] = []
        if comments_per_video <= 0:
            continue
        try:
            cs = get("commentThreads", part="snippet", videoId=v["id"], maxResults=min(comments_per_video, 100), textFormat="plainText").get("items", [])
            comments_by[v["id"]] = [x.get("snippet", {}).get("topLevelComment", {}).get("snippet", {}).get("textDisplay", "") for x in cs]
        except RuntimeError as exc:
            if "403" not in str(exc):
                raise
    rows = []
    for v in vids:
        s = v.get("statistics", {})
        sn = v.get("snippet", {})
        rows.append({
            "id": v["id"], "video_id": v["id"], "title": sn.get("title", ""),
            "description": sn.get("description", "")[:500], "published_at": sn.get("publishedAt", ""),
            "views": int(s.get("viewCount", 0)), "likes": int(s.get("likeCount", 0)),
            "comments": int(s.get("commentCount", 0)),
            "url": f"https://www.youtube.com/watch?v={v['id']}",
            "comments_text": comments_by.get(v["id"], []),
        })
    return rows, ch
