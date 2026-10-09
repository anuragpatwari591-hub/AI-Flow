"""Stateful fake of the Instagram API for tests (documented request/response shapes)."""
from __future__ import annotations

import json
from urllib.parse import parse_qs, urlparse

import httpx


class FakeGraph:
    def __init__(self, account_type="BUSINESS", token_expires=5184000) -> None:
        self.account_type, self.token_expires = account_type, token_expires
        self.calls: list[tuple[str, str]] = []
        self.containers: dict[str, dict] = {}
        self.published: list[str] = []
        self.status_sequence = ["IN_PROGRESS", "FINISHED"]
        self.fail_publish_once: dict | None = None
        self.insight_values = {"reach": 1200, "views": 2500, "likes": 140, "comments": 9, "shares": 31, "saved": 55,
                               "total_interactions": 235, "ig_reels_avg_watch_time": 4100}
        self.unsupported = {"ig_reels_video_view_total_time"}
        self.token_valid = True

    def client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self.handle))

    def _err(self, code, msg, status=400):
        return httpx.Response(status, json={"error": {"message": msg, "code": code}})

    def handle(self, req: httpx.Request) -> httpx.Response:
        u = urlparse(str(req.url))
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if req.content:
            q.update({k: v[0] for k, v in parse_qs(req.content.decode()).items()})
        path = u.path
        self.calls.append((req.method, path))
        if not self.token_valid and q.get("access_token", "").startswith("LL"):
            return self._err(190, "Invalid OAuth access token")
        if path == "/oauth/access_token":
            return httpx.Response(200, json={"access_token": "SHORT123", "user_id": 111, "permissions": [
                "instagram_business_basic", "instagram_business_content_publish", "instagram_business_manage_insights"]})
        if path == "/access_token":
            return httpx.Response(200, json={"access_token": "LL_TOKEN_SECRET", "token_type": "bearer", "expires_in": self.token_expires})
        if path == "/refresh_access_token":
            return httpx.Response(200, json={"access_token": "LL_TOKEN_REFRESHED", "expires_in": 5184000})
        p = path.split("/", 2)[-1] if path.count("/") >= 2 else path
        if p == "me":
            return httpx.Response(200, json={"user_id": "111", "username": "ap_test", "account_type": self.account_type,
                                             "followers_count": 1000, "media_count": 12})
        if p.endswith("/media") and req.method == "POST":
            cid = f"c{len(self.containers) + 1}"
            self.containers[cid] = {"n": 0, **q}
            return httpx.Response(200, json={"id": cid})
        if p.endswith("/media_publish"):
            if self.fail_publish_once:
                e, self.fail_publish_once = self.fail_publish_once, None
                return self._err(e["code"], e["msg"], e.get("status", 400))
            mid = f"m{len(self.published) + 1}"
            self.published.append(q["creation_id"])
            return httpx.Response(200, json={"id": mid})
        if p.endswith("/insights"):
            m = q["metric"]
            if m in self.unsupported:
                return self._err(100, f"metric {m} not supported")
            return httpx.Response(200, json={"data": [{"name": m, "values": [{"value": self.insight_values[m]}]}]})
        if p.startswith("c") and p[1:].isdigit():
            c = self.containers[p]
            st = self.status_sequence[min(c["n"], len(self.status_sequence) - 1)]
            c["n"] += 1
            return httpx.Response(200, json={"id": p, "status_code": st, "status": st})
        if p.startswith("m"):
            return httpx.Response(200, json={"id": p, "permalink": f"https://www.instagram.com/reel/{p}/"})
        return self._err(100, f"unhandled {path}", 404)
