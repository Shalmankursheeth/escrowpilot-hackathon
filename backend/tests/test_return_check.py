"""The seller's check of returned goods: no refund moves until the seller confirms the goods match what was shipped,
the check window ends without objection, or a reviewer settles a reported mismatch."""
import datetime as dt

from app import clock, payments
from conftest import register
from test_deposit import DEPOSIT, TERMS_DEP, dispute, live_deal, rule, send_return, to_last_stage

CHECK_TERMS = dict(TERMS_DEP, return_check_days=5)


def returned_deal(client, w):
    deal = live_deal(client, w, CHECK_TERMS)
    ms = to_last_stage(client, w, deal)
    dispute(client, w, deal, ms)
    send_return(client, w, deal, ms)
    return deal, ms


def check(client, w, deal, ms, who, ok, note=""):
    return client.post(f"/deals/{deal['id']}/milestones/{ms['id']}/return-received", headers=w[who], json={"ok": ok, "note": note})


def stage(client, w, deal):
    return client.get(f"/deals/{deal['id']}", headers=w["buyer"]).json()["milestones"][2]


def test_no_refund_until_the_seller_confirms_the_returned_goods(client, world):
    deal, ms = returned_deal(client, world)
    assert stage(client, world, deal)["return_received"] is None and stage(client, world, deal)["return_check_due_at"]
    r = rule(client, world, deal, ms, "seller_fault")
    assert r.status_code == 409 and "check of the returned goods" in r.json()["detail"]
    h = payments.get_holder()
    assert not h.refunds and not h.payouts
    assert check(client, world, deal, ms, "seller", True).status_code == 200
    assert rule(client, world, deal, ms, "seller_fault").status_code == 200
    assert sum(r["amount_cents"] for r in h.refunds) == 5_000_000


def test_only_the_seller_can_confirm_and_only_once(client, world):
    deal, ms = returned_deal(client, world)
    assert check(client, world, deal, ms, "buyer", True).status_code == 403
    assert check(client, world, deal, ms, "seller", True).status_code == 200
    assert check(client, world, deal, ms, "seller", False, "now it looks wrong").status_code == 409


def test_a_mismatch_needs_a_reason_and_blocks_the_refund(client, world):
    deal, ms = returned_deal(client, world)
    assert check(client, world, deal, ms, "seller", False, "").status_code == 422
    assert check(client, world, deal, ms, "seller", False, "Slabs are a lower grade").status_code == 200
    assert stage(client, world, deal)["return_received"] == "mismatch"
    assert rule(client, world, deal, ms, "seller_fault").status_code == 409
    assert not payments.get_holder().refunds


def test_mismatch_then_buyer_ruled_at_fault_pays_the_seller_in_full(client, world):
    deal, ms = returned_deal(client, world)
    check(client, world, deal, ms, "seller", False, "Slabs are a lower grade")
    assert rule(client, world, deal, ms, "buyer_fault").status_code == 200
    d = client.get(f"/deals/{deal['id']}", headers=world["buyer"]).json()
    h = payments.get_holder()
    assert d["state"] == "completed" and d["fault"] == "buyer" and d["deposit"]["state"] == "returned"
    assert [r["amount_cents"] for r in h.refunds] == [DEPOSIT]  # the buyer gets nothing back for swapped goods
    assert sum(p["amount_cents"] for p in h.payouts) == 5_000_000 - 100_000


def test_reviewer_can_overrule_a_wrong_mismatch(client, world):
    deal, ms = returned_deal(client, world)
    check(client, world, deal, ms, "seller", False, "Slabs are a lower grade")
    r = client.post(f"/admin/deals/{deal['id']}/milestones/{ms['id']}/return-check", headers=world["admin"],
                    json={"ok": True, "note": "Photos and seal numbers match"})
    assert r.status_code == 200 and r.json()["return_received"] == "confirmed"
    assert rule(client, world, deal, ms, "seller_fault").status_code == 200


def test_a_buyer_ruling_waits_for_a_pending_check(client, world):
    deal, ms = returned_deal(client, world)
    r = rule(client, world, deal, ms, "buyer_fault")
    assert r.status_code == 409 and "still checking" in r.json()["detail"]


def test_silence_confirms_the_goods_when_the_window_ends(client, world, monkeypatch):
    deal, ms = returned_deal(client, world)
    assert client.post("/admin/run-timers", headers=world["admin"]).json()["released"] == 0
    real = clock.now()
    monkeypatch.setattr(clock, "now", lambda: real + dt.timedelta(days=6))
    assert client.post("/admin/run-timers", headers=world["admin"]).json()["released"] == 1
    assert stage(client, world, deal)["return_received"] == "confirmed"
    assert rule(client, world, deal, ms, "seller_fault").status_code == 200


def test_zero_check_days_keeps_the_old_behaviour(client, world):
    deal = live_deal(client, world, dict(TERMS_DEP, return_check_days=0))
    ms = to_last_stage(client, world, deal)
    dispute(client, world, deal, ms)
    send_return(client, world, deal, ms)
    assert rule(client, world, deal, ms, "seller_fault").status_code == 200


def test_admin_ledger_adds_up_and_the_audit_chain_survives_a_repeat_review(client, world):
    deal, ms = returned_deal(client, world)
    check(client, world, deal, ms, "seller", True)
    assert rule(client, world, deal, ms, "seller_fault").status_code == 200
    assert rule(client, world, deal, ms, "seller_fault").status_code == 409  # a second tap is refused, not re-run
    led = client.get("/admin/ledger", headers=world["admin"]).json()
    assert led["collected_cents"] > 0
    assert led["held_cents"] == led["collected_cents"] - led["paid_out_cents"] - led["refunded_cents"] - led["platform_cents"]
    assert led["platform_cents"] == led["stage_fees_cents"] + led["deposit_kept_cents"]
    assert led["deposit_kept_cents"] > 0 and any(e["kind"] == "refund" for e in led["events"])
    assert client.get(f"/deals/{deal['id']}/audit", headers=world["buyer"]).json()["chain_ok"] is True
    assert client.get("/admin/ledger", headers=world["buyer"]).status_code == 403
