# TERI ROSHNI organic promotion agent

Human-in-the-loop discovery engine: discover → dedupe → score (0-100 rubric) → 5 comment drafts → spam check → **approval queue**.
Nothing publishes without `approve` then an explicit `publish` (typed confirmation, daily cap, YouTube official API only).

    python3 promoter promote --demo        # offline demo data (fake example.invalid URLs)
    python3 promoter promote               # live YouTube discovery (needs YOUTUBE_API_KEY)
    python3 promoter promote --file x.json # public posts you found manually (Instagram, Reddit, forums)
    python3 promoter queue | approve ID | reject ID | edit ID "text" | publish ID [--with-link] | outreach ID

`--file` format: list of {platform,url,creator,title,description,top_comments[],comment_count,age_days,creator_subs}.
Config: `data/config.json` or env (SONG_URL, YOUTUBE_API_KEY, YOUTUBE_OAUTH_TOKEN). Report: `data/report.html`.
Instagram/Reddit/forums: no automated posting; the tool emits MANUAL ACTION items.

## GitHub research (verdicts)
- googleapis/google-api-python-client (Apache-2.0, maintained, official): best base for YouTube if you outgrow stdlib calls. Use it.
- praw-dev/praw (BSD, maintained, official Reddit API): use for Reddit discovery, respecting subreddit self-promo rules.
- Meta Instagram Graph API (official): manages YOUR account's media/comments; it does not allow commenting on other people's posts.
- Rejected: instagrapi / clinstagram private-API mode, instaclient (Selenium), instabot-style repos: private APIs/automation that violate Instagram ToS and risk a ban.
- Generic GitHub searches returned mostly unrelated dashboards; no maintained open-source "approval-queue" tool fit, so this one is purpose-built. Licenses/activity not exhaustively audited.

## Limits
Scoring and comment drafting are keyword heuristics/templates. Hooks pulled from titles can read awkwardly: always edit.
