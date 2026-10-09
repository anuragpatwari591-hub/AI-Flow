"""Audio rights policy. Nothing with unresolved rights is rendered off-platform or published."""
from __future__ import annotations

from typing import Literal

from ..db import AudioAsset

RIGHTS_STATUSES = ("original", "licensed", "royalty_free", "unverified", "instagram_native")
Purpose = Literal["render", "publish", "ads"]


def clearance(asset: AudioAsset | None, purpose: Purpose) -> tuple[bool, list[str]]:
    """Return (ok, reasons). `asset=None` means a reel with no off-platform audio track (always renderable)."""
    if asset is None:
        return True, []
    why: list[str] = []
    st = asset.rights_status
    if st not in RIGHTS_STATUSES:
        return False, [f"unknown rights status '{st}'"]
    if st == "unverified":
        return False, ["rights unverified: cannot be rendered into a file, published, or used in ads"]
    if st == "instagram_native":
        if purpose == "render":
            return False, ["Instagram-native music cannot be extracted/rendered; create the reel without it and "
                           "attach the track manually in the Instagram app (manual step)"]
        return True, []
    # original / licensed / royalty_free
    if not asset.local_file:
        why.append("no local audio file registered")
    if st in ("licensed", "royalty_free") and not asset.license_ref:
        why.append("license reference missing")
    if st == "original" and not asset.notes:
        why.append("original: record ownership note (who owns master + publishing)")
    if purpose == "render" and not asset.allow_offplatform_render:
        why.append("license does not permit off-platform rendering")
    if purpose == "publish" and not (asset.allow_offplatform_render and asset.allow_automated_publish):
        why.append("license not confirmed for automated publishing")
    if purpose == "ads" and not asset.allow_commercial_ads:
        why.append("license not confirmed for commercial advertising")
    return (not why), why


def required_attribution(asset: AudioAsset | None) -> str:
    return asset.attribution if asset and asset.attribution else ""
