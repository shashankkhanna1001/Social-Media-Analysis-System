# Social Media Analysis System — Live V6

A live, four-platform social-media analytics dashboard for Instagram, X/Twitter, LinkedIn and YouTube.

## What this version fixes

- **No demo data is bundled.** Platform pages fetch fresh data when you press **Fetch Live Data**.
- **No duplicated platform heading.** The global header is now the single page title for Instagram, X, LinkedIn and YouTube.
- **Instagram followers/views mapping is broader.** The normalizer now handles common fields such as `followersCount`, `followerCount`, `likesCount`, `commentsCount`, `viewCount`, `videoViewCount`, `playsCount`, `impressions`, and nested owner/author metrics.
- **Follower aggregation is correct.** Repeated profile counts on individual posts are deduplicated by creator/platform instead of letting the last row overwrite a real count.
- **LinkedIn is upgraded to a profile + posts workflow by default.** Profile data supplies follower/audience information while a no-cookie LinkedIn posts Actor supplies post text and engagement metrics.
- **Profile-only LinkedIn results remain usable.** If an Actor returns a profile but no post records, the dashboard still shows the profile audience without pretending the profile row is a content post.
- **Profile snapshots are excluded from post counts, content tables and content sentiment totals.**

## Recommended LinkedIn configuration

The default `.env.example` uses:

```text
LINKEDIN_PROFILE_ACTOR_ID=harvestapi/linkedin-profile-scraper
LINKEDIN_POSTS_ACTOR_ID=harvestapi/linkedin-profile-posts
```

The first Actor supplies profile fields including follower count; the second supplies recent posts and engagement counts. You can replace either Actor ID with another compatible Actor or configure an input template in `.env`.

The project still supports the older single `LINKEDIN_ACTOR_ID` setting, including the older `curious_coder/linkedin-profile-scraper` workflow when its required user-agent/proxy settings are supplied.

## What V6 fixes (on top of V5)

- **LinkedIn now actually returns posts.** The V5 default posts Actor ID
  (`data-slayer/linkedin-profile-posts-scraper`) does not exist on Apify, so the call always
  failed. The default is now the real no-cookie Actor `harvestapi/linkedin-profile-posts`.
- **LinkedIn is fault tolerant.** The profile Actor and posts Actor now run independently.
  If one fails, the other's data is still returned instead of the whole run being discarded.
- **Instagram likes / views / engagement rate are calculated again.** The Instagram Actor input
  now sends `resultsType: "posts"` and `addParentData: true`. `addParentData` is what attaches
  the owner profile (including `followersCount`) to each post row — without it, follower count is
  missing and engagement rate collapses to 0. A `resultsType: "details"` backfill runs if
  followers still don't arrive.
- **Engagement counts are read from nested objects.** LinkedIn Actors return engagement as
  `reactions` / `numLikes`, or nested under `engagement` / `socialCounts`, and sometimes as a
  *list* of reaction objects instead of a count. All of these shapes are now handled.
- **Number parsing is fixed.** Strings such as `"10K followers"`, `"345 reactions"` and `"1.5k+"`
  previously parsed to `0`. Instagram's `-1` sentinel (hidden like count) is now clamped to `0`
  instead of poisoning totals.
- **X/Twitter connector corrected** to `apidojo/tweet-scraper` with the `twitterHandles` input
  field, and profile URLs containing query strings (`?lang=en`) now resolve to the bare handle.
- **Per-platform state isolation.** Each platform page keeps its own reference input, item limit
  and results. Typing a name on one platform no longer overwrites another.
- **Engagement rate uses the standard formula.** Average interactions per post ÷ followers.
  The old `interactions / views` basis inflated the figure whenever a set mixed videos
  (which report views) with images (which do not).

### Known platform limitation

Instagram exposes no public **shares** metric, so that column is legitimately always `0` for
Instagram. This is a platform limitation, not a bug.

## New features in V6

- **Insights engine** — top hashtags ranked by average interactions, best posting hours and
  weekdays, top posts, and per-post averages. Included in every analysis response and shown as
  two new panels on each platform page.
- **CSV export** — an *Export CSV* button next to *Save this analysis*, backed by
  `POST /api/export-csv`.
- **`POST /api/insights`** — compute insights for any supplied record set.

## Setup

```powershell
python -m venv .venv
.venv\\Scripts\\activate
pip install -r requirements.txt
copy .env.example .env
python app.py
```

Open:

```text
http://127.0.0.1:5000
```

## Live workflow

1. Open a platform page.
2. Enter a username/handle/profile URL or YouTube channel handle/ID.
3. Press **Fetch Live Data**.
4. Review platform analytics.
5. Analyze other platforms to build the cross-platform workspace.
6. Use **Save this analysis** or **Save All** only when you want to persist the result.

## Credentials

Keep all tokens/keys in `.env`. Never put them in frontend JavaScript.

Required for Instagram/X/LinkedIn:

```env
APIFY_TOKEN=...
```

Required for YouTube:

```env
YOUTUBE_API_KEY=...
```

## Notes on Actors

Apify Actors have platform- and Actor-specific input/output schemas. The application therefore keeps Actor IDs configurable and includes optional JSON input templates. If you select a different Actor, copy its exact input schema into the corresponding template instead of changing usernames in Python.
