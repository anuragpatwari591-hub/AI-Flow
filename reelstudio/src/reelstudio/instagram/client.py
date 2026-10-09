"""Thin client for Meta's official Instagram API (Instagram Login flavour, graph.instagram.com).

Only documented endpoints are used. Anything unsupported is a manual step, never a private endpoint.
Rate-limit responses are surfaced as `rate_limited` errors for the queue to back off on; they are never evaded.
Endpoint/permission names follow Meta's public docs as of the project's writing; confirm against the current
docs for your app version before go-live (see docs/INSTAGRAM_SETUP.md).
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import httpx

SCOPES = ["instagram_business_basic", "instagram_business_content_publish", "instagram_business_manage_insights"]
RATE_LIMIT_CODES = {4, 17, 32, 613, 80002}
TOKEN_CODES = {102, 190}
TRANSIENT_CODES = {1, 2}


class IGApiError(Exception):
    def __init__(self, message: str, *, status: int = 0, code: int | None = None, subcode: int | None = None) -> None:
        super().__init__(message)
        self.status, self.code, self.subcode = status, code, subcode

    @property
    def kind(self) -> str:
        if self.code in TOKEN_CODES:
            return "token"
        if self.code in RATE_LIMIT_CODES:
            return "rate_limited"
        if self.code in TRANSIENT_CODES or self.status >= 500 or self.status == 0:
            return "transient"
        return "permanent"


class IGClient:
    def __init__(self, app_id: str = "", app_secret: str = "", redirect_uri: str = "", version: str = "v21.0",
                 http: httpx.Client | None = None, graph_base: str = "https://graph.instagram.com",
                 oauth_base: str = "https://api.instagram.com") -> None:
        self.app_id, self.app_secret, self.redirect_uri, self.version = app_id, app_secret, redirect_uri, version
        self.http = http or httpx.Client(timeout=60)
        self.graph, self.oauth = graph_base, oauth_base

    # -- plumbing
    def _call(self, method: str, url: str, **kw: Any) -> dict[str, Any]:
        try:
            r = self.http.request(method, url, **kw)
        except httpx.HTTPError as e:
            raise IGApiError(f"network error: {type(e).__name__}", status=0) from e
        try:
            data = r.json()
        except ValueError:
            data = {}
        if r.status_code >= 400 or "error" in data:
            err = data.get("error", data) if isinstance(data, dict) else {}
            if isinstance(err, str):
                err = {"message": err}
            raise IGApiError(str(err.get("message") or err.get("error_message") or f"HTTP {r.status_code}"),
                             status=r.status_code, code=err.get("code"), subcode=err.get("error_subcode"))
        return data

    def _g(self, path: str) -> str:
        return f"{self.graph}/{self.version}/{path.lstrip('/')}"

    # -- auth
    def authorize_url(self, state: str) -> str:
        q = {"client_id": self.app_id, "redirect_uri": self.redirect_uri, "response_type": "code",
             "scope": ",".join(SCOPES), "state": state}
        return f"https://www.instagram.com/oauth/authorize?{urlencode(q)}"

    def exchange_code(self, code: str) -> dict[str, Any]:
        return self._call("POST", f"{self.oauth}/oauth/access_token", data={
            "client_id": self.app_id, "client_secret": self.app_secret, "grant_type": "authorization_code",
            "redirect_uri": self.redirect_uri, "code": code})

    def long_lived(self, short_token: str) -> dict[str, Any]:
        return self._call("GET", f"{self.graph}/access_token", params={
            "grant_type": "ig_exchange_token", "client_secret": self.app_secret, "access_token": short_token})

    def refresh(self, token: str) -> dict[str, Any]:
        return self._call("GET", f"{self.graph}/refresh_access_token",
                          params={"grant_type": "ig_refresh_token", "access_token": token})

    # -- account
    def me(self, token: str) -> dict[str, Any]:
        return self._call("GET", self._g("me"), params={
            "fields": "user_id,username,account_type,followers_count,media_count", "access_token": token})

    def publishing_limit(self, ig_id: str, token: str) -> dict[str, Any]:
        return self._call("GET", self._g(f"{ig_id}/content_publishing_limit"),
                          params={"fields": "quota_usage,config", "access_token": token})

    # -- publishing (container flow)
    def create_reel_container(self, ig_id: str, token: str, *, video_url: str, caption: str,
                              cover_url: str | None = None, share_to_feed: bool = True) -> str:
        data = {"media_type": "REELS", "video_url": video_url, "caption": caption,
                "share_to_feed": str(share_to_feed).lower(), "access_token": token}
        if cover_url:
            data["cover_url"] = cover_url
        return self._call("POST", self._g(f"{ig_id}/media"), data=data)["id"]

    def container_status(self, container_id: str, token: str) -> dict[str, Any]:
        return self._call("GET", self._g(container_id), params={"fields": "status_code,status", "access_token": token})

    def publish_container(self, ig_id: str, token: str, container_id: str) -> str:
        return self._call("POST", self._g(f"{ig_id}/media_publish"),
                          data={"creation_id": container_id, "access_token": token})["id"]

    def media_info(self, media_id: str, token: str) -> dict[str, Any]:
        return self._call("GET", self._g(media_id), params={"fields": "id,permalink,timestamp,media_type",
                                                             "access_token": token})

    # -- insights (one metric per call so one unsupported metric can't hide the others)
    def media_insight(self, media_id: str, token: str, metric: str) -> float | None:
        data = self._call("GET", self._g(f"{media_id}/insights"), params={"metric": metric, "access_token": token})
        for item in data.get("data", []):
            if item.get("name") == metric:
                if "total_value" in item:
                    return float(item["total_value"]["value"])
                vals = item.get("values") or []
                if vals:
                    return float(vals[0]["value"])
        return None
