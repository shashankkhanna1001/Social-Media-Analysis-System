import re
from datetime import datetime, timezone

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
    _vader = SentimentIntensityAnalyzer()
except Exception:
    _vader = None

PLATFORMS = ("instagram", "x", "linkedin", "youtube")
POS = {"love","great","amazing","excellent","awesome","good","best","helpful","useful","happy","win","winning","success","beautiful","nice","thanks","thank","congrats","congratulations","excited","inspiring","inspiration"}
NEG = {"bad","worst","hate","terrible","awful","poor","broken","fail","failed","failure","sad","angry","scam","fake","boring","useless","disappointed","disappointing","issue","problem"}


def num(v):
    """Convert common social-media count formats to integers.

    Handles plain numbers, K/M/B and Indian K/L/Cr forms such as 1.7Cr and 1.6L.
    """
    if v in (None, "", False):
        return 0
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        # Instagram sends -1 when a post hides its like count.
        return max(int(v), 0)
    if isinstance(v, (list, dict)):
        return 0
    s = str(v).strip().replace(",", "")
    s_low = s.lower().replace(" ", "")
    # Strip trailing descriptive words LinkedIn/Instagram actors often append,
    # e.g. "10K followers", "1.2M views", "345 reactions".
    s_low = re.sub(
        r"(followers?|following|subscribers?|views?|plays?|likes?|reactions?|comments?|reposts?|shares?|connections?|members?|posts?)$",
        "",
        s_low,
    ).rstrip("+·|-_ ")
    m = re.fullmatch(r"(-?[\d.]+)(k|m|b|l|cr|crore|lakhs?|million|billion)?", s_low)
    if m:
        n = float(m.group(1))
        u = (m.group(2) or "").lower()
        mult = {
            "k": 1_000,
            "m": 1_000_000,
            "million": 1_000_000,
            "b": 1_000_000_000,
            "billion": 1_000_000_000,
            "l": 100_000,
            "lakh": 100_000,
            "lakhs": 100_000,
            "cr": 10_000_000,
            "crore": 10_000_000,
        }.get(u, 1)
        value = int(n * mult)
        # Instagram returns -1 when a post has its like count hidden.
        return max(value, 0)
    m2 = re.search(r"(-?[\d.]+)", s_low)
    if m2:
        try:
            return max(int(float(m2.group(1))), 0)
        except Exception:
            return 0
    return 0


def first(d, *keys, default=None):
    if not isinstance(d, dict):
        return default
    for k in keys:
        if d.get(k) not in (None, ""):
            return d[k]
    return default


def text_value(v):
    return v if isinstance(v, str) else ""


def sentiment(text):
    text = text or ""
    if _vader:
        c = _vader.polarity_scores(text)["compound"]
        label = "Positive" if c >= 0.05 else "Negative" if c <= -0.05 else "Neutral"
        return label, round(c, 4)
    words = set(re.findall(r"[A-Za-z]+", text.lower()))
    score = len(words & POS) - len(words & NEG)
    c = max(-1, min(1, score / 5))
    return ("Positive" if c > 0 else "Negative" if c < 0 else "Neutral"), round(c, 4)


def hashtags(text):
    return sorted(set(re.findall(r"#[\w]+", text or "")))


def mentions(text):
    return sorted(set(re.findall(r"@[A-Za-z0-9_.-]+", text or "")))


def _rows(source):
    if isinstance(source, list):
        return source
    if isinstance(source, dict):
        if isinstance(source.get("items"), list):
            return source["items"]
        return [source]
    return []


def _profile_from_row(row):
    if not isinstance(row, dict):
        return {}
    for key in ("profile", "profileData", "account", "user", "author", "owner"):
        val = row.get(key)
        if isinstance(val, dict):
            return val
    return row


FOLLOWER_KEYS = (
    "followersCount", "followerCount", "followers", "followers_count",
    "authorFollowerCount", "authorFollowers", "ownerFollowerCount",
    "follower_count", "numFollowers", "subscriberCount", "subscribers",
    "connectionsCount", "connections",
)


def _followers_from(*dicts):
    value = 0
    for d in dicts:
        if not isinstance(d, dict):
            continue
        value = max(value, num(first(d, *FOLLOWER_KEYS, default=0)))
        for container in _METRIC_CONTAINERS + ("author", "owner", "profile", "user", "account"):
            sub = d.get(container)
            if isinstance(sub, dict):
                value = max(value, num(first(sub, *FOLLOWER_KEYS, default=0)))
    return value


LIKE_KEYS = ("likes", "likeCount", "likesCount", "likes_count", "numLikes", "favoriteCount",
             "favorite_count", "stats_likes", "reactions", "reactionsCount", "numReactions",
             "reactionCount", "totalReactions", "reaction_count", "appreciationCount")
COMMENT_KEYS = ("comments", "commentCount", "commentsCount", "comments_count", "numComments",
                "stats_comments", "replyCount", "reply_count", "commentaryCount")
SHARE_KEYS = ("shares", "shareCount", "sharesCount", "reposts", "repostCount", "repostsCount",
              "reshares", "retweetCount", "retweets", "retweet_count", "quoteCount",
              "stats_reposts", "numShares", "shares_count")
VIEW_KEYS = ("views", "viewCount", "videoViewCount", "video_view_count", "videoViews",
             "videoPlayCount", "playsCount", "playCount", "playCountTotal", "impressions",
             "impressionCount", "numViews", "views_count", "videoPlayCountTotal")

# Actors frequently nest counts in a sub-object instead of the top level.
_METRIC_CONTAINERS = ("engagement", "socialCounts", "socialCount", "stats", "statistics",
                      "metrics", "counts", "insights", "socialActivity", "engagementStats")


def _scalar_first(d, keys):
    """Return the first scalar (non list/dict) value among keys."""
    if not isinstance(d, dict):
        return 0
    for k in keys:
        v = d.get(k)
        if v in (None, "") or isinstance(v, (list, dict)):
            continue
        n = num(v)
        if n:
            return n
    return 0


def _metric(p, keys):
    """Read a count from the post root, falling back to nested metric containers."""
    value = _scalar_first(p, keys)
    if value:
        return value
    for container in _METRIC_CONTAINERS:
        sub = p.get(container)
        if isinstance(sub, dict):
            value = _scalar_first(sub, keys)
            if value:
                return value
    return 0


def _count_of(value):
    """Some actors return reactions/comments as a list of objects rather than a count."""
    return len(value) if isinstance(value, list) else 0


def _post_metrics(p):
    p = p if isinstance(p, dict) else {}
    nested = []
    for key in ("owner", "author", "profile", "account", "user"):
        if isinstance(p.get(key), dict):
            nested.append(p[key])
    likes = _metric(p, LIKE_KEYS) or _count_of(p.get("reactions"))
    comments = _metric(p, COMMENT_KEYS) or _count_of(p.get("comments"))
    shares = _metric(p, SHARE_KEYS)
    views = _metric(p, VIEW_KEYS)
    return likes, comments, shares, views, nested


def _identity(p, fallback_username, fallback_name):
    p = p if isinstance(p, dict) else {}
    nested = []
    for key in ("owner", "author", "profile", "account", "user"):
        if isinstance(p.get(key), dict):
            nested.append(p[key])
    username = text_value(first(p, "username", "handle", "screenName", "ownerUsername", "authorHandle", "profileUsername", "publicIdentifier", "identifier", default=fallback_username)) or fallback_username
    name = text_value(first(p, "name", "fullName", "full_name", "displayName", "ownerFullName", "authorName", default=fallback_name)) or fallback_name
    followers = _followers_from(p, *nested)
    if not username or username == fallback_username:
        for n in nested:
            username = text_value(first(n, "username", "handle", "screenName", "userName", "publicIdentifier", "identifier", default=username)) or username
    if not name or name == fallback_name:
        for n in nested:
            name = text_value(first(n, "name", "fullName", "full_name", "displayName", default=name)) or name
    return username, name, followers


def base(platform, username, name, followers, raw, i, text, likes, comments, shares, views, interactions, label, compound, date, url, post_id, media_type, is_profile_snapshot=False):
    er = round(interactions / views * 100, 2) if views else round(interactions / followers * 100, 2) if followers else 0
    return {
        "platform": platform,
        "username": username,
        "name": name,
        "followers": followers,
        "post_id": post_id or f"{platform}-{username}-{i}",
        "url": url or "",
        "text": text,
        "date": date or "",
        "likes": likes,
        "comments": comments,
        "shares": shares,
        "views": views,
        "interactions": interactions,
        "engagement_rate": er,
        "sentiment": label,
        "compound": compound,
        "media_type": media_type or "Post",
        "hashtags": hashtags(text),
        "mentions": mentions(text),
        "raw": raw,
        "is_profile_snapshot": bool(is_profile_snapshot),
    }


def _date(p):
    return first(p, "date", "timestamp", "takenAtIso", "takenAt", "postedAtISO", "postedAt", "published_at", "publishedAt", "createdAt", "created_at", "posted_date", default="")


def _url(p):
    return first(p, "post_url", "postUrl", "url", "permalink", "webUrl", "profileUrl", "linkedinUrl", default="")


def _text(p):
    return text_value(first(p, "text", "caption", "description", "postText", "post_text", "content", "body", "articleBody", "title", "headline", default=""))


def _id(p, i, platform, username):
    return first(p, "post_id", "postId", "shortCode", "tweetId", "video_id", "videoId", "id", "urn", "post_urn", default=f"{platform}-{username}-{i}")


def normalize_linkedin(profile_items, post_items, requested_ref=""):
    """Normalize LinkedIn profile + post actor outputs into the common dashboard schema."""
    profiles = _rows(profile_items)
    posts = _rows(post_items)
    profile = {}
    for r in profiles:
        if not isinstance(r, dict):
            continue
        cand = _profile_from_row(r)
        if cand:
            profile = cand
            if not first(profile, "followerCount", "followersCount", "followers", default=None):
                # Keep looking; another profile row may carry richer data.
                continue
            break
    if not profile and profiles:
        profile = _profile_from_row(profiles[0])

    fallback_username = requested_ref.strip().rstrip("/").split("/in/")[-1].split("?")[0].lstrip("@") or "linkedin"
    username = text_value(first(profile, "username", "publicIdentifier", "identifier", "profileUsername", default=fallback_username)) or fallback_username
    name = text_value(first(profile, "fullName", "name", "full_name", "displayName", default=username)) or username
    profile_followers = _followers_from(profile)
    profile_url = first(profile, "profileUrl", "profile_url", "linkedinUrl", "url", default=requested_ref)

    # Some actors return posts nested on the profile record. Flatten them too.
    nested_posts = []
    for r in profiles:
        if not isinstance(r, dict):
            continue
        for key in ("activity", "recentPosts", "recentArticles", "posts", "latestPosts", "recentPosts", "companyUpdates"):
            value = r.get(key)
            if isinstance(value, list):
                nested_posts.extend(value)
    posts = posts + nested_posts

    out = []
    for i, p in enumerate(posts):
        if not isinstance(p, dict):
            continue
        u, n, pf = _identity(p, username, name)
        followers = max(profile_followers, pf)
        likes, comments, shares, views, _ = _post_metrics(p)
        txt = _text(p)
        label, comp = sentiment(txt)
        media_type = first(p, "post_type", "postType", "mediaType", "media_type", "type", default="Post")
        out.append(base(
            "linkedin", u, n, followers, p, i, txt, likes, comments, shares, views,
            likes + comments + shares, label, comp, _date(p), _url(p), _id(p, i, "linkedin", u), media_type
        ))

    # If the selected profile actor returned only the profile and no posts, retain a
    # clearly-labelled profile snapshot so follower data is still visible without
    # pretending it is a content post.
    if not out and profile:
        about = text_value(first(profile, "headline", "about", "summary", "title", default=""))
        label, comp = sentiment(about)
        out.append(base(
            "linkedin", username, name, profile_followers, profile, 0, about,
            0, 0, 0, 0, 0, label, comp, first(profile, "scraped_at", "scrapedAt", default=""),
            profile_url, first(profile, "id", "profileId", default=""), "Profile Snapshot", is_profile_snapshot=True
        ))
    return out


def normalize(platform, source, requested_ref=""):
    rows = _rows(source)
    out = []
    if platform == "youtube":
        profile = source.get("channel", {}) if isinstance(source, dict) else {}
        username = profile.get("title") or requested_ref
        followers = num(first(profile, "subscribers", "subscriberCount", "followerCount", default=0))
        for i, p in enumerate(rows):
            title = text_value(first(p, "title", "name", default=""))
            desc = text_value(first(p, "description", "text", default=""))
            likes, comments, shares, views, _ = _post_metrics(p)
            inter = likes + comments + shares
            label, c = sentiment(title + " " + desc)
            out.append(base(
                platform, username, username, followers, p, i, title or desc, likes, comments, shares,
                views, inter, label, c, _date(p), first(p, "url", default=""),
                first(p, "video_id", "videoId", "id", default=""), first(p, "media_type", "type", default="Video")
            ))
        return profile, out

    # Flexible support for common Apify result shapes. Profile-level metrics can be
    # carried on every post row, nested under owner/author/profile, or emitted as a
    # dedicated profile record.
    profile = {}
    for r in rows[:8]:
        if not isinstance(r, dict):
            continue
        if str(r.get("section", "")).lower() in {"accounting", "summary", "error"}:
            continue
        cand = _profile_from_row(r)
        if any(k in cand for k in ("followersCount", "followerCount", "followers", "fullName", "profileUrl", "profile_url")):
            profile = cand
            break

    fallback_username = requested_ref.strip().lstrip("@").rstrip("/").split("/")[-1]
    username, name, followers = _identity(profile or {}, fallback_username, fallback_username)

    for i, p in enumerate(rows):
        if not isinstance(p, dict):
            continue
        section = str(p.get("section", "")).lower()
        status = str(p.get("status", "")).lower()
        if section in {"accounting", "summary", "error"} or status in {"error", "failed", "not_found", "unavailable"}:
            continue

        u, n, pf = _identity(p, username, name)
        followers_here = max(followers, pf)
        txt = _text(p)
        likes, comments, shares, views, nested = _post_metrics(p)
        # A few actors expose video plays/views under alternative names on nested
        # media objects. Use the largest available nested value as a safe fallback.
        if not views:
            for nobj in nested:
                views = max(views, num(first(nobj, "views", "viewCount", "videoViewCount", "videoViews", "playsCount", "playCount", default=0)))
        label, c = sentiment(txt)
        media_type = first(p, "media_type", "mediaType", "product_type", "productType", "type", default="Post")
        out.append(base(
            platform, u, n, followers_here, p, i, txt, likes, comments, shares, views,
            likes + comments + shares, label, c, _date(p), _url(p), _id(p, i, platform, u), media_type
        ))

    return profile, out


def summary(records):
    # Followers are profile-level metrics repeated on post rows. Keep the maximum
    # per platform/creator rather than letting the last row overwrite it with zero.
    uniq = {}
    for r in records:
        key = (r.get("platform"), r.get("username"))
        uniq[key] = max(uniq.get(key, 0), num(r.get("followers")))
    followers = sum(uniq.values())
    views = sum(num(r.get("views")) for r in records)
    inter = sum(num(r.get("interactions")) for r in records)
    content_count = sum(1 for r in records if not r.get("is_profile_snapshot"))
    # Standard engagement rate = average interactions per post / followers.
    # Dividing total interactions by total views inflates the figure whenever the
    # set mixes videos (which report views) with images (which do not).
    if followers and content_count:
        er = round((inter / content_count) / followers * 100, 2)
    elif views:
        er = round(inter / views * 100, 2)
    else:
        er = 0
    return {
        "posts": content_count,
        "items": len(records),
        "profile_snapshots": sum(1 for r in records if r.get("is_profile_snapshot")),
        "creators": len(uniq),
        "followers": followers,
        "views": views,
        "interactions": inter,
        "likes": sum(num(r.get("likes")) for r in records),
        "comments": sum(num(r.get("comments")) for r in records),
        "shares": sum(num(r.get("shares")) for r in records),
        "engagement_rate": er,
    }


def sentiment_summary(records):
    content = [r for r in records if not r.get("is_profile_snapshot")]
    c = {"Positive": 0, "Neutral": 0, "Negative": 0}
    for r in content:
        c[r.get("sentiment", "Neutral")] = c.get(r.get("sentiment", "Neutral"), 0) + 1
    t = sum(c.values()) or 1
    return {"counts": c, "percentages": {k: round(v / t * 100, 1) for k, v in c.items()}}


def insights(records, top_n=10):
    """Derive actionable insights: best hashtags, posting times and top content."""
    content = [r for r in records if not r.get("is_profile_snapshot")]
    tag_stats, hour_stats, day_stats = {}, {}, {}
    days = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

    for r in content:
        inter = num(r.get("interactions"))
        for t in r.get("hashtags") or []:
            s = tag_stats.setdefault(t.lower(), {"tag": t.lower(), "posts": 0, "interactions": 0})
            s["posts"] += 1
            s["interactions"] += inter
        dt = _parse_date(r.get("date"))
        if dt:
            h = hour_stats.setdefault(dt.hour, {"hour": dt.hour, "posts": 0, "interactions": 0})
            h["posts"] += 1
            h["interactions"] += inter
            d = day_stats.setdefault(dt.weekday(), {"day": days[dt.weekday()], "posts": 0, "interactions": 0})
            d["posts"] += 1
            d["interactions"] += inter

    def rank(stats):
        rows = []
        for s in stats.values():
            s = dict(s)
            s["avg_interactions"] = round(s["interactions"] / s["posts"], 1) if s["posts"] else 0
            rows.append(s)
        return sorted(rows, key=lambda x: x["avg_interactions"], reverse=True)

    top_posts = sorted(content, key=lambda r: num(r.get("interactions")), reverse=True)[:top_n]
    return {
        "top_hashtags": rank(tag_stats)[:top_n],
        "best_hours": rank(hour_stats)[:8],
        "best_days": rank(day_stats)[:7],
        "top_posts": [{
            "platform": r.get("platform"), "url": r.get("url"),
            "text": (r.get("text") or "")[:180], "likes": num(r.get("likes")),
            "comments": num(r.get("comments")), "shares": num(r.get("shares")),
            "views": num(r.get("views")), "interactions": num(r.get("interactions")),
            "engagement_rate": r.get("engagement_rate"), "sentiment": r.get("sentiment"),
            "date": r.get("date"),
        } for r in top_posts],
        "averages": {
            "likes": round(sum(num(r.get("likes")) for r in content) / len(content), 1) if content else 0,
            "comments": round(sum(num(r.get("comments")) for r in content) / len(content), 1) if content else 0,
            "interactions": round(sum(num(r.get("interactions")) for r in content) / len(content), 1) if content else 0,
        },
    }


def _parse_date(value):
    if not value:
        return None
    s = str(value).strip()
    if s.isdigit():
        try:
            ts = int(s)
            return datetime.fromtimestamp(ts / 1000 if ts > 10**11 else ts, tz=timezone.utc)
        except Exception:
            return None
    s = s.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y"):
            try:
                return datetime.strptime(s[:19], fmt)
            except ValueError:
                continue
    return None


def cross(records):
    aliases = {"hiteshdotcom": "hiteshchoudhary"}
    buckets = {}
    for r in records:
        key = aliases.get(str(r.get("username", "")).lower(), str(r.get("username", "")).lower())
        b = buckets.setdefault(key, {"creator": key, "name": r.get("name", key), "platforms": {}})
        p = b["platforms"].setdefault(r["platform"], {"followers": 0, "posts": 0, "views": 0, "interactions": 0, "engagement_rate": 0})
        p["followers"] = max(p["followers"], num(r.get("followers")))
        if not r.get("is_profile_snapshot"):
            p["posts"] += 1
        p["views"] += num(r.get("views"))
        p["interactions"] += num(r.get("interactions"))

    for b in buckets.values():
        b["followers"] = sum(p["followers"] for p in b["platforms"].values())
        b["posts"] = sum(p["posts"] for p in b["platforms"].values())
        b["views"] = sum(p["views"] for p in b["platforms"].values())
        b["interactions"] = sum(p["interactions"] for p in b["platforms"].values())
        if b["followers"] and b["posts"]:
            b["engagement_rate"] = round((b["interactions"] / b["posts"]) / b["followers"] * 100, 2)
        elif b["views"]:
            b["engagement_rate"] = round(b["interactions"] / b["views"] * 100, 2)
        else:
            b["engagement_rate"] = 0
        for p in b["platforms"].values():
            if p["followers"] and p["posts"]:
                p["engagement_rate"] = round((p["interactions"] / p["posts"]) / p["followers"] * 100, 2)
            elif p["views"]:
                p["engagement_rate"] = round(p["interactions"] / p["views"] * 100, 2)
            else:
                p["engagement_rate"] = 0
    return list(buckets.values())
