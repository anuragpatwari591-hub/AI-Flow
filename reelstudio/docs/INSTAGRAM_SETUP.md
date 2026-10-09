# Instagram integration setup (official APIs only)

**Status: implemented and tested against a stateful fake of the documented endpoints. NOT yet tested against a live
Instagram account.** Do the live smoke test below before trusting it. Endpoint, permission and metric names follow
Meta's public documentation as I know it; Meta changes these, so confirm against the current docs for your API version
(`RS_GRAPH_VERSION`).

## 1. Prerequisites (manual)
1. Convert the Instagram account to a **Professional (Business or Creator)** account.
2. Create a Meta developer app → add the **Instagram API with Instagram Login** product.
3. Request permissions: `instagram_business_basic`, `instagram_business_content_publish`,
   `instagram_business_manage_insights`. While the app is in Development mode, only app roles/testers can authorise,
   which is enough to publish to *your own* account; public use needs App Review.
4. Add the OAuth redirect URI: `https://<your-host>/api/instagram/callback` (must be HTTPS).
5. Put `RS_META_APP_ID`, `RS_META_APP_SECRET`, `RS_META_REDIRECT_URI` in the environment (never in Git).

## 2. Media must be publicly fetchable
Instagram pulls `video_url` from a public URL. Set `RS_PUBLIC_BASE_URL=https://<your-host>`; the app serves
`/media/<reel>/<video|cover>/<signature>` where the signature is an HMAC of (reel, kind, file hash) — files are not
enumerable and a changed file invalidates old URLs. Put the app behind TLS (see DEPLOYMENT.md).

## 3. Connect, then enable
Dashboard → *Account & tokens* → **Connect Instagram**. After the OAuth round-trip the account is stored with its
token **encrypted** (`RS_SECRET_KEY`), publishing **OFF**. Eligibility (professional account type, publish scope) is
re-verified live when you press **Enable publishing**, and you must type the username to confirm the destination.

## 4. Token lifecycle
Long-lived tokens last ~60 days. The worker refreshes tokens within 10 days of expiry and alerts
(`RS_ALERT_WEBHOOK_URL` + logs) if refresh fails or the token expired; publishing is blocked at preflight for an
expired token. **Revoke** wipes the stored token locally and cancels queued posts; also remove the app under
Instagram → Settings → Apps and Websites to revoke on Meta's side.

## 5. Live smoke test checklist (not yet performed)
- [ ] Connect flow returns the right username and `account_type`.
- [ ] `GET /me` fields accepted by your API version.
- [ ] Publish one approved Reel from a test render; confirm container reaches `FINISHED`, post appears, permalink stored.
- [ ] Confirm cover image is applied (`cover_url`) — drop the parameter in `IGClient.create_reel_container` if rejected.
- [ ] Insight metrics at 24h: see which of the requested metrics your account returns; others are shown as unavailable.
- [ ] Rate-limit endpoint: `GET /{ig-id}/content_publishing_limit` via `IGClient.publishing_limit` (wired for use, not yet surfaced in UI).

## 6. What the API cannot do → manual steps
- **Instagram-native/trending audio** cannot be attached through the content-publishing API. Reels that want it are
  rendered without that track, flagged `needs_native_audio`, and require either: (a) approval with an explicit
  "publish without native track" acknowledgement, or (b) the **manual package** (video, cover, caption, steps) to post
  in the app and then *mark manually published*.
- Reference-account analysis from Instagram: no scraping. Supply videos you are entitled to use, or public notes.
