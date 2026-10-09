"""Paid-advertising workflow, deliberately separate from organic publishing.

This module PREPARES creatives and export bundles only. It has no code path that talks to Meta's
Marketing API, spends money, or changes budgets. Launch is a manual step in Ads Manager that is only
unlocked on paper once all five approvals exist.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import AdCampaign, AdVariant, Concept, Reel, audit, utcnow
from ..render.service import render_reel
from ..writing.engine import assign_timing
from ..config import load_yaml

APPROVAL_ITEMS = ("account", "creative", "destination", "audience", "budget")
# editing a field invalidates the matching approval
FIELD_TO_ITEM = {"ad_account": "account", "destination_url": "destination", "audience_notes": "audience", "budget": "budget"}
DEFAULT_CTAS = ["listen now", "learn more", "watch the full thing"]


class AdsError(Exception):
    pass


def create_campaign(s: Session, *, name: str, objective: str, destination_url: str = "", audience_notes: str = "",
                    budget: dict[str, Any] | None = None, ad_account: str = "", actor: str = "owner") -> AdCampaign:
    c = AdCampaign(name=name, objective=objective, destination_url=destination_url, audience_notes=audience_notes,
                   budget=budget or {}, ad_account=ad_account)
    s.add(c)
    s.flush()
    audit(s, "ad.campaign_created", "ad_campaign", c.id, actor)
    return c


def update_campaign(s: Session, c: AdCampaign, actor: str = "owner", **fields: Any) -> AdCampaign:
    if c.status in ("approved_to_launch", "exported"):
        c.status = "ready_for_review"
        audit(s, "ad.reapproval_required", "ad_campaign", c.id, actor)
    for k, v in fields.items():
        if k not in FIELD_TO_ITEM:
            raise AdsError(f"cannot edit '{k}'")
        if getattr(c, k) != v:
            setattr(c, k, v)
            ap = dict(c.approvals)
            ap.pop(FIELD_TO_ITEM[k], None)  # budget/destination/audience/account change voids that approval
            c.approvals = ap
            audit(s, "ad.field_changed", "ad_campaign", c.id, actor, field=k)
    return c


def add_variants(s: Session, c: AdCampaign, concept_id: int, *, hooks: list[str], ctas: list[str] | None = None,
                 template: str | None = None, audio_id: int | None = None, out_root: Path | None = None,
                 overrides: dict[str, Any] | None = None) -> list[AdVariant]:
    """One variant per (hook x CTA) up to 6; hooks are supplied/approved copy that replaces the opening line.
    Single-dimension tests: vary hooks with CTA fixed, or CTAs with hook fixed."""
    concept = s.get(Concept, concept_id)
    voice = load_yaml("voice_guide.yaml")
    ctas = ctas or DEFAULT_CTAS[:1]
    combos = [(h, ctas[0]) for h in hooks] if len(ctas) == 1 else [(hooks[0], cta) for cta in ctas]
    if len(combos) > 6:
        raise AdsError("limit 6 variants per batch")
    out = []
    for i, (hook, cta) in enumerate(combos):
        rest = [{"text": l["text"]} for l in concept.lines[1:]]
        lines = assign_timing([{"text": hook}, *rest, {"text": cta}], voice["timing"])
        reel = render_reel(s, concept_id, template=template, audio_id=audio_id, lines=lines, purpose="ad",
                           out_root=out_root or (get_settings().renders_dir / "ads"), overrides=overrides)
        if reel.render_status != "rendered":
            raise AdsError(f"variant render failed: {reel.render_error}")
        v = AdVariant(campaign_id=c.id, reel_id=reel.id, label=chr(65 + i), hook=hook, cta=cta,
                      test_dimension="hook" if len(ctas) == 1 else "cta",
                      audio_cleared_for_ads=True)  # render_reel(purpose='ad') refuses uncleared audio
        s.add(v)
        out.append(v)
    ap = dict(c.approvals)
    if ap.pop("creative", None):
        c.approvals = ap
        if c.status in ("approved_to_launch", "exported"):
            c.status = "ready_for_review"
    s.flush()
    audit(s, "ad.variants_added", "ad_campaign", c.id, count=len(out))
    return out


def submit_for_review(s: Session, c: AdCampaign) -> AdCampaign:
    if not c.variants:
        raise AdsError("no creative variants")
    c.status = "approved_to_launch" if all(i in c.approvals for i in APPROVAL_ITEMS) else "ready_for_review"
    audit(s, "ad.submitted_for_review", "ad_campaign", c.id)
    return c


def approve_item(s: Session, c: AdCampaign, item: str, actor: str) -> AdCampaign:
    if item not in APPROVAL_ITEMS:
        raise AdsError(f"item must be one of {APPROVAL_ITEMS}")
    if not actor or actor == "system":
        raise AdsError("a named human must approve")
    required = {"account": c.ad_account, "destination": c.destination_url, "audience": c.audience_notes,
                "budget": c.budget.get("amount") if c.budget else None, "creative": c.variants}
    if not required[item]:
        raise AdsError(f"nothing to approve for '{item}': field is empty")
    if item == "destination" and not c.destination_url.startswith("https://"):
        raise AdsError("destination must be an https URL")
    if item == "budget" and (c.budget.get("amount", 0) <= 0 or not c.budget.get("currency") or not c.budget.get("period")):
        raise AdsError("budget needs amount > 0, currency and period (e.g. daily/lifetime)")
    ap = dict(c.approvals)
    ap[item] = {"by": actor, "at": utcnow().isoformat(), "snapshot": _snapshot(c, item)}
    c.approvals = ap
    audit(s, "ad.item_approved", "ad_campaign", c.id, actor, item=item)
    if all(i in c.approvals for i in APPROVAL_ITEMS) and c.status == "ready_for_review":
        c.status = "approved_to_launch"
        audit(s, "ad.approved_to_launch", "ad_campaign", c.id, actor)
    return c


def _snapshot(c: AdCampaign, item: str) -> Any:
    return {"account": c.ad_account, "destination": c.destination_url, "audience": c.audience_notes,
            "budget": c.budget, "creative": [(v.label, v.hook, v.cta) for v in c.variants]}[item]


def export_bundle(s: Session, c: AdCampaign, dest: Path) -> Path:
    """Write export-ready assets + manifest. Draft bundles are allowed for review; they say what is unapproved."""
    if c.status not in ("ready_for_review", "approved_to_launch", "exported"):
        raise AdsError("submit the campaign for review before exporting")
    dest.mkdir(parents=True, exist_ok=True)
    manifest = {"campaign": c.name, "objective": c.objective, "destination": c.destination_url,
                "audience_notes": c.audience_notes, "budget": c.budget, "ad_account": c.ad_account,
                "approvals": c.approvals, "missing_approvals": [i for i in APPROVAL_ITEMS if i not in c.approvals],
                "launch_performed": False, "variants": []}
    for v in c.variants:
        reel = s.get(Reel, v.reel_id)
        d = dest / f"variant_{v.label}"
        d.mkdir(exist_ok=True)
        shutil.copy(reel.video_path, d / "ad.mp4")
        shutil.copy(reel.cover_path, d / "cover.jpg")
        v.export_path = str(d)
        manifest["variants"].append({"label": v.label, "hook": v.hook, "cta": v.cta, "test_dimension": v.test_dimension,
                                     "audio": reel.audio_id, "sha256": reel.video_sha256, "caption_suggestion": v.hook})
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    ok = not manifest["missing_approvals"]
    (dest / "LAUNCH_STEPS.txt").write_text(
        ("ALL FIVE APPROVALS RECORDED. " if ok else f"NOT APPROVED YET: {manifest['missing_approvals']}. DO NOT LAUNCH.\n")
        + "\nThis tool never launches ads or spends money. To launch: create the campaign manually in Meta Ads Manager "
          "using the approved account, destination, audience and budget in manifest.json, and upload each variant. "
          "Run one test dimension at a time.\n", encoding="utf-8")
    if ok:
        c.status = "exported"
    audit(s, "ad.exported", "ad_campaign", c.id, approved=ok)
    return dest
