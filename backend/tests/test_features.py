"""Cross-document checks, duplicate files, the cooling-off, one appeal to a second reviewer, the AI brief and strikes."""
import datetime as dt

from app import clock, payments
from app.config import get_settings
from conftest import TERMS, doc, proof, register
from test_deposit import TERMS_DEP, dispute, live_deal, pay_deposit, rule, send_return, signed_deal, to_last_stage

OPEN = TERMS_DEP


def with_date(name, date):
    return doc(name).replace("\n", f"\nDate: {date}\n", 1)


def submit(client, w, deal, idx, text):
    ms = deal["milestones"][idx]
    return client.post(f"/deals/{deal['id']}/milestones/{ms['id']}/proof", headers=w["seller"],
                       json={"filename": "doc.txt", "text": text})


def fund(client, w, deal, idx):
    ms = deal["milestones"][idx]
    client.post(f"/deals/{deal['id']}/milestones/{ms['id']}/fund", headers=w["buyer"])
    return client.post(f"/deals/{deal['id']}/milestones/{ms['id']}/fund/capture", headers=w["buyer"])


def another_deal(client, w, terms):
    """A second signed order between the same two traders (they are already connected)."""
    deal = client.post("/deals", headers=w["seller"], json={"title": "Second order", "counterparty_id": w["buyer_pid"], "terms": terms}).json()
    for who in ("seller", "buyer"):
        assert client.post(f"/deals/{deal['id']}/confirm", headers=w[who], json={"version": 1}).status_code == 200
    return deal


def reasons(r):
    return " | ".join(r.json()["verdict"]["reasons"])


# ---------------------------------------------------------------- cross-document and duplicate checks
def test_document_dated_before_an_earlier_stage_is_flagged(client, world):
    deal = live_deal(client, world, OPEN)
    assert submit(client, world, deal, 0, with_date("order_confirmation.txt", "2026-03-10")).json()["state"] == "accepted"
    fund(client, world, deal, 1)
    r = submit(client, world, deal, 1, with_date("bill_of_lading_ok.txt", "2026-03-01"))
    assert r.json()["state"] == "flagged" and "dated before" in reasons(r)


def test_document_dated_after_the_earlier_stage_passes(client, world):
    deal = live_deal(client, world, OPEN)
    submit(client, world, deal, 0, with_date("order_confirmation.txt", "2026-03-01"))
    fund(client, world, deal, 1)
    assert submit(client, world, deal, 1, with_date("bill_of_lading_ok.txt", "2026-03-10")).json()["state"] == "accepted"


def test_same_file_reused_in_another_open_order_is_flagged(client, world):
    first = live_deal(client, world, OPEN)
    assert submit(client, world, first, 0, doc("order_confirmation.txt")).json()["state"] == "accepted"
    second = another_deal(client, world, OPEN)
    pay_deposit(client, world, second)
    assert fund(client, world, second, 0).status_code == 200
    r = submit(client, world, second, 0, doc("order_confirmation.txt"))
    assert r.json()["state"] == "flagged" and "already uploaded" in reasons(r)


def test_duplicate_check_can_be_switched_off(client, world, monkeypatch):
    monkeypatch.setattr(get_settings(), "duplicate_doc_check", False)
    first = live_deal(client, world, OPEN)
    submit(client, world, first, 0, doc("order_confirmation.txt"))
    second = another_deal(client, world, OPEN)
    pay_deposit(client, world, second)
    fund(client, world, second, 0)
    assert submit(client, world, second, 0, doc("order_confirmation.txt")).json()["state"] == "accepted"


# ---------------------------------------------------------------- cooling-off, appeal, second reviewer
def disputed_with_return(client, w):
    deal = live_deal(client, w)
    ms = to_last_stage(client, w, deal)
    dispute(client, w, deal, ms)
    send_return(client, w, deal, ms)
    return deal, ms


def test_fault_ruling_waits_out_the_cooling_off(client, world, monkeypatch):
    monkeypatch.setattr(get_settings(), "cooling_off_hours", 48)
    deal, ms = disputed_with_return(client, world)
    r = rule(client, world, deal, ms, "seller_fault")
    assert r.status_code == 200
    h = payments.get_holder()
    assert not h.refunds and not h.payouts  # nothing moves yet
    m = client.get(f"/deals/{deal['id']}", headers=world["buyer"]).json()["milestones"][2]
    assert m["state"] == "flagged" and m["ruling"] == "seller" and m["ruling_due_at"]
    assert rule(client, world, deal, ms, "buyer_fault").status_code == 409  # cannot be swapped while it waits
    assert client.post("/admin/run-timers", headers=world["admin"]).json()["released"] == 0
    real = clock.now()
    monkeypatch.setattr(clock, "now", lambda: real + dt.timedelta(hours=49))
    assert client.post("/admin/run-timers", headers=world["admin"]).json()["released"] == 1
    d = client.get(f"/deals/{deal['id']}", headers=world["buyer"]).json()
    assert d["state"] == "completed" and d["deposit"]["state"] == "forfeited"
    assert sum(x["amount_cents"] for x in h.refunds) == 5_000_000


def test_appeal_goes_to_a_different_reviewer_whose_decision_is_final(client, world, monkeypatch):
    monkeypatch.setattr(get_settings(), "cooling_off_hours", 48)
    second, _, _ = register(client, "reviewer2@example.com", "buyer", "Reviewer Two")
    deal, ms = disputed_with_return(client, world)
    assert rule(client, world, deal, ms, "seller_fault").status_code == 200
    r = client.post(f"/deals/{deal['id']}/milestones/{ms['id']}/appeal", headers=world["seller"], json={"reason": "Goods were fine"})
    assert r.status_code == 200 and r.json()["appealed"] is True
    assert client.post(f"/deals/{deal['id']}/milestones/{ms['id']}/appeal", headers=world["seller"],
                       json={"reason": "again please"}).status_code == 409  # one appeal only
    real = clock.now()
    monkeypatch.setattr(clock, "now", lambda: real + dt.timedelta(hours=100))
    assert client.post("/admin/run-timers", headers=world["admin"]).json()["released"] == 0  # an appeal stops the timer
    assert rule(client, world, deal, ms, "seller_fault").status_code == 409  # same reviewer cannot decide the appeal
    r = client.post(f"/admin/deals/{deal['id']}/milestones/{ms['id']}/review", headers=second,
                    json={"decision": "buyer_fault", "note": "Seller photos show intact goods"})
    assert r.status_code == 200
    d = client.get(f"/deals/{deal['id']}", headers=world["buyer"]).json()
    assert d["state"] == "completed" and d["fault"] == "buyer" and d["deposit"]["state"] == "returned"


def test_appeal_needs_a_pending_ruling_inside_the_window(client, world, monkeypatch):
    monkeypatch.setattr(get_settings(), "cooling_off_hours", 48)
    deal, ms = disputed_with_return(client, world)
    url = f"/deals/{deal['id']}/milestones/{ms['id']}/appeal"
    assert client.post(url, headers=world["buyer"], json={"reason": "nothing ruled yet"}).status_code == 409
    rule(client, world, deal, ms, "buyer_fault")
    real = clock.now()
    monkeypatch.setattr(clock, "now", lambda: real + dt.timedelta(hours=60))
    assert client.post(url, headers=world["seller"], json={"reason": "too late now"}).status_code == 409


# ---------------------------------------------------------------- AI brief and strikes
def test_reviewer_brief_is_facts_only(client, world):
    deal, ms = disputed_with_return(client, world)
    r = client.get(f"/admin/deals/{deal['id']}/milestones/{ms['id']}/brief", headers=world["admin"])
    assert r.status_code == 200
    j = r.json()
    assert "Goods are wrong" in j["summary"] and "accepted and on file" in j["summary"] and "reviewer decides" in j["summary"]
    assert j["facts"]["return_proof"] == "accepted and on file" and len(j["facts"]["documents"]) == 3
    assert "delivery receipt DR-330041" in j["summary"] and "return receipt" not in j["summary"]  # each stage shows its own proof
    assert client.get(f"/admin/deals/{deal['id']}/milestones/{ms['id']}/brief", headers=world["buyer"]).status_code == 403


def test_fault_ruling_adds_a_strike_to_the_trust_profile(client, world):
    deal, ms = disputed_with_return(client, world)
    assert rule(client, world, deal, ms, "seller_fault").status_code == 200
    lookup = client.get(f"/users/lookup/{world['seller_pid']}", headers=world["buyer"]).json()
    assert lookup["trust"]["strikes"] == 1
    d = client.get(f"/deals/{deal['id']}", headers=world["buyer"]).json()
    assert d["seller_strikes"] == 1 and d["buyer_strikes"] == 0
