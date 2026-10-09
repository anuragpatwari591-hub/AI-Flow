"""Command-line entry point: reelstudio <command>."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import PROJECT_ROOT, get_settings, load_yaml
from .logging_setup import setup_logging


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="reelstudio")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate", help="apply database migrations (alembic upgrade head)")
    sub.add_parser("gen-keys", help="print a fresh RS_SECRET_KEY and RS_DASHBOARD_TOKEN")
    sub.add_parser("fonts", help="print the font licence table")
    dr = sub.add_parser("doctor", help="read-only readiness report (no secrets printed, nothing published)")
    dr.add_argument("--live", action="store_true", help="also check the public host and call read-only Instagram endpoints")
    sv = sub.add_parser("serve", help="run API + dashboard")
    sv.add_argument("--host", default="127.0.0.1"); sv.add_argument("--port", type=int, default=8000)
    wk = sub.add_parser("worker", help="run scheduler/worker loop"); wk.add_argument("--interval", type=float, default=30)
    rs = sub.add_parser("research", help="run trend research once (seasonal + configured feeds + data/trend_imports)")
    gn = sub.add_parser("generate", help="generate concepts"); gn.add_argument("--category", action="append"); gn.add_argument("--per-category", type=int, default=2); gn.add_argument("--adaptive", action="store_true")
    rn = sub.add_parser("render", help="render a concept"); rn.add_argument("concept_id", type=int); rn.add_argument("--template"); rn.add_argument("--audio-id", type=int); rn.add_argument("--preview-only", action="store_true")
    a = p.parse_args(argv)
    setup_logging()

    if a.cmd == "gen-keys":
        import secrets
        from cryptography.fernet import Fernet
        print(f"RS_SECRET_KEY={Fernet.generate_key().decode()}\nRS_DASHBOARD_TOKEN={secrets.token_urlsafe(32)}")
        return 0
    if a.cmd == "fonts":
        from .render.fonts import license_table
        for r in license_table():
            print(json.dumps(r))
        return 0
    if a.cmd == "migrate":
        from alembic import command
        from alembic.config import Config
        cfg = Config(str(PROJECT_ROOT / "alembic.ini"))
        cfg.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
        command.upgrade(cfg, "head")
        return 0

    from . import db
    st = get_settings()
    if a.cmd == "doctor":
        from .doctor import build_report, render
        st.data_dir.mkdir(parents=True, exist_ok=True)
        db.init_db(create_all=st.database_url.startswith("sqlite"))
        with db.session_scope() as s:
            rep = build_report(st, s, live=a.live)
        print(render(rep))
        return 1 if rep.blocked else 0
    st.data_dir.mkdir(parents=True, exist_ok=True)
    db.init_db(create_all=st.database_url.startswith("sqlite"))  # Postgres: use `reelstudio migrate`
    if a.cmd == "serve":
        import uvicorn
        from .api.app import create_app
        uvicorn.run(create_app(), host=a.host, port=a.port)
    elif a.cmd == "worker":
        from .worker import run_forever
        run_forever(a.interval)
    elif a.cmd == "research":
        from .api.app import create_app  # noqa: F401
        from .trends.service import run_research
        from .trends.sources import ManualFileSource, RssSource, SeasonalCalendarSource
        cfg = load_yaml("trends.yaml")
        srcs = [SeasonalCalendarSource(cfg.get("seasonal", []))] + [RssSource(f["name"], f["url"]) for f in cfg.get("rss_feeds", [])]
        imp = st.data_dir / "trend_imports"
        if imp.exists():
            srcs += [ManualFileSource(x, x.stem) for x in sorted(list(imp.glob("*.json")) + list(imp.glob("*.csv")))]
        with db.session_scope() as s:
            print(json.dumps(run_research(s, srcs, cfg), indent=2))
    elif a.cmd == "generate":
        from .analytics import service as an
        from .writing.engine import run_cycle
        from .writing.providers import get_provider
        with db.session_scope() as s:
            kw: dict = {"per_category": a.per_category}
            if a.category:
                kw["categories"] = a.category
            if a.adaptive:
                plan = an.adaptive_plan(s, list(load_yaml("voice_guide.yaml")["categories"]))
                kw.update(allocation=plan["allocation"], account_insights=plan["account_insights"], own_history_n=plan["own_history_n"])
            for c in run_cycle(s, get_provider(st), **kw):
                print(f"[{c.id}] {c.category} score={c.score} conf={c.confidence} :: {' / '.join(l['text'] for l in c.lines)}")
    elif a.cmd == "render":
        from .render.service import render_reel
        with db.session_scope() as s:
            r = render_reel(s, a.concept_id, template=a.template, audio_id=a.audio_id, preview_only=a.preview_only)
            print(json.dumps({"reel_id": r.id, "status": r.render_status, "error": r.render_error, "video": r.video_path,
                              "cover": r.cover_path, "preview": r.preview_path}, indent=2))
            return 0 if r.render_status in ("rendered", "pending") else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
