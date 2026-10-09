from datetime import timedelta

from reelstudio.analytics import service as an
from reelstudio.db import Concept, IGAccount, MetricSnapshot, PublishJob, Reel, utcnow


def seed(s, n, cats, rates, reach=1000, followers=1000, age=48.0, start_days=60):
    acct = s.query(IGAccount).first() or IGAccount(ig_user_id="1", username="x"); s.add(acct); s.flush()
    jobs = []
    for i in range(n):
        c = Concept(cycle_id="c", category=cats[i % len(cats)], hook="me: x" if i % 2 else "plain hook", lines=[])
        s.add(c); s.flush()
        r = Reel(concept_id=c.id, render_status="rendered", render_spec={"duration": 9}, template="midnight_minimal"); s.add(r); s.flush()
        pub = utcnow() - timedelta(days=start_days - i)
        j = PublishJob(reel_id=r.id, account_id=acct.id, status="published", idempotency_key=f"k{s.query(PublishJob).count()}_{i}",
                       published_at=pub, ig_media_id=f"m{i}"); s.add(j); s.flush()
        eng = rates[i % len(rates)]
        s.add(MetricSnapshot(job_id=j.id, taken_at=pub + timedelta(hours=age), age_hours=age, followers=followers,
                             metrics={"reach": reach, "likes": eng * reach * 0.6, "comments": eng * reach * 0.1,
                                      "shares": eng * reach * 0.1, "saved": eng * reach * 0.2}))
        jobs.append(j)
    s.flush()
    return jobs


def test_derived_metrics_only_when_inputs_exist():
    assert an.derive({"reach": 100, "likes": 5}, None)["engagement_rate"] is None  # missing comments/shares/saves
    assert an.derive({"reach": 100, "likes": 5, "comments": 1, "shares": 2, "saved": 2}, 500)["engagement_rate"] == 0.1


def test_insufficient_baseline_never_declares_winner(session):
    seed(session, 3, ["a"], [0.05])
    rows = an.reel_rows(session)
    assert an.assess(rows, rows[-1])["verdict"] == "insufficient_baseline"


def test_above_and_below_baseline_use_matched_age(session):
    seed(session, 8, ["a"], [0.05, 0.052, 0.048, 0.051])
    seed(session, 1, ["a"], [0.15], start_days=1)           # strong
    seed(session, 1, ["a"], [0.01], start_days=0)           # weak
    rows = an.reel_rows(session)
    assert an.assess(rows, rows[-2])["verdict"] == "above_baseline"
    assert an.assess(rows, rows[-1])["verdict"] == "below_baseline"


def test_snapshot_at_wrong_age_is_not_compared(session):
    seed(session, 7, ["a"], [0.05], age=2.0)  # 2h old only; target 48h
    rows = an.reel_rows(session)
    assert an.assess(rows, rows[-1])["verdict"] == "no_data"


def test_group_winner_needs_sample_and_margin(session):
    seed(session, 12, ["a", "b"], [0.05])
    rows = an.reel_rows(session)
    assert an.declare_winners(rows, "category")["winner"] is None  # tie
    for r in rows:
        if r["category"] == "a":
            r["matched"]["engagement_rate"] *= 1.5
    assert an.declare_winners(rows, "category")["winner"] == "a"
    thin = rows[:4]
    assert an.declare_winners(thin, "category")["winner"] is None


def test_mix_keeps_exploration_and_caps_share(session):
    seed(session, 12, ["a", "b"], [0.05])
    rows = an.reel_rows(session)
    for r in rows:
        if r["category"] == "a":
            r["matched"]["engagement_rate"] *= 3
    mix = an.recommend_mix(rows, ["a", "b", "c"], total=6)
    assert mix["allocation"]["c"] >= 1 and mix["allocation"]["b"] >= 1  # unseen/weak categories keep a slot
    assert max(mix["allocation"].values()) <= 2  # 40% cap of 6
