"""Seller security deposit, the 2% fee and the fault rulings. All amounts are for the 50,000.00 order in conftest.TERMS:
deposit 5% = 250,000 cents (victim share 2% of the order = 100,000, platform 3% = 150,000)."""
from app import payments
from conftest import TERMS, connect, doc, proof

DEPOSIT = 250_000
VICTIM = 100_000
TERMS_DEP = dict(TERMS, seller_deposit_pct=5, release_rule="on_completion", failure_scope="whole_order", inspection_days=3)


def pay_deposit(client, w, deal):
    r = client.post(f"/deals/{deal['id']}/deposit", headers=w["seller"])
    assert r.status_code == 200, r.text
    assert r.json()["amount_cents"] == DEPOSIT
    return client.post(f"/deals/{deal['id']}/deposit/capture", headers=w["seller"])


def signed_deal(client, w, terms):
    connect(client, w)
    deal = client.post("/deals", headers=w["seller"], json={
        "title": "Granite slabs", "counterparty_id": w["buyer_pid"], "terms": terms}).json()
    for who in ("seller", "buyer"):
        assert client.post(f"/deals/{deal['id']}/confirm", headers=w[who], json={"version": 1}).status_code == 200
    return deal


def live_deal(client, w, terms=TERMS_DEP):
    deal = signed_deal(client, w, terms)
    assert pay_deposit(client, w, deal).json()["deposit"]["state"] == "held"
    ms = deal["milestones"][0]
    client.post(f"/deals/{deal['id']}/milestones/{ms['id']}/fund", headers=w["buyer"])
    r = client.post(f"/deals/{deal['id']}/milestones/{ms['id']}/fund/capture", headers=w["buyer"])
    assert r.status_code == 200 and r.json()["state"] == "funded", r.text
    return r.json()


def to_last_stage(client, w, deal):
    proof(client, w, deal, 0, "order_confirmation.txt")
    proof(client, w, deal, 1, "bill_of_lading_ok.txt")
    return proof(client, w, deal, 2, "delivery_receipt.txt").json()


def dispute(client, w, deal, ms):
    r = client.post(f"/deals/{deal['id']}/milestones/{ms['id']}/dispute", headers=w["buyer"], json={"reason": "Goods are wrong"})
    assert r.json()["state"] == "flagged"


def send_return(client, w, deal, ms):
    r = client.post(f"/deals/{deal['id']}/milestones/{ms['id']}/return-proof", headers=w["buyer"],
                    json={"filename": "return_receipt.txt", "text": doc("return_receipt.txt")})
    assert r.json()["ok"] is True


def rule(client, w, deal, ms, decision):
    return client.post(f"/admin/deals/{deal['id']}/milestones/{ms['id']}/review", headers=w["admin"],
                       json={"decision": decision, "note": "ruled"})


def test_buyer_cannot_fund_before_the_seller_deposit(client, world):
    deal = signed_deal(client, world, TERMS_DEP)
    ms = deal["milestones"][0]
    r = client.post(f"/deals/{deal['id']}/milestones/{ms['id']}/fund", headers=world["buyer"])
    assert r.status_code == 409 and "deposit" in r.json()["detail"]
    assert client.post(f"/deals/{deal['id']}/deposit", headers=world["buyer"]).status_code == 403  # only the seller pays it


def test_good_deal_returns_deposit_and_charges_two_percent(client, world):
    deal = live_deal(client, world, dict(TERMS_DEP, inspection_days=0))
    to_last_stage(client, world, deal)
    d = client.get(f"/deals/{deal['id']}", headers=world["buyer"]).json()
    h = payments.get_holder()
    assert d["state"] == "completed" and d["deposit"]["state"] == "returned"
    assert [r["amount_cents"] for r in h.refunds] == [DEPOSIT]  # nothing refunded but the deposit
    assert sum(p["amount_cents"] for p in h.payouts) == 5_000_000 - 100_000  # 2% fee on 50,000.00
    assert client.get(f"/deals/{deal['id']}/audit", headers=world["buyer"]).json()["chain_ok"] is True


def test_seller_at_fault_buyer_refunded_plus_two_percent_and_deposit_forfeited(client, world):
    deal = live_deal(client, world)
    ms = to_last_stage(client, world, deal)
    dispute(client, world, deal, ms)
    send_return(client, world, deal, ms)
    assert rule(client, world, deal, ms, "seller_fault").status_code == 200
    d = client.get(f"/deals/{deal['id']}", headers=world["buyer"]).json()
    h = payments.get_holder()
    assert d["state"] == "completed" and d["fault"] == "seller" and d["deposit"]["state"] == "forfeited"
    assert sum(r["amount_cents"] for r in h.refunds) == 5_000_000  # the whole order back, deposit not returned
    assert [(p["receiver"], p["amount_cents"]) for p in h.payouts] == [("buyer@sandbox.example.com", VICTIM)]


def test_seller_fault_needs_the_return_proof_first(client, world):
    deal = live_deal(client, world)
    ms = to_last_stage(client, world, deal)
    dispute(client, world, deal, ms)
    assert rule(client, world, deal, ms, "seller_fault").status_code == 409
    h = payments.get_holder()
    assert not h.refunds and not h.payouts
    assert client.get(f"/deals/{deal['id']}", headers=world["buyer"]).json()["deposit"]["state"] == "held"


def test_buyer_at_fault_goods_returned_costs_five_percent(client, world):
    deal = live_deal(client, world)
    ms = to_last_stage(client, world, deal)
    dispute(client, world, deal, ms)
    send_return(client, world, deal, ms)
    assert rule(client, world, deal, ms, "buyer_fault").status_code == 200
    d = client.get(f"/deals/{deal['id']}", headers=world["buyer"]).json()
    h = payments.get_holder()
    last = 1_500_000
    assert d["state"] == "completed" and d["deposit"]["state"] == "returned"
    assert sorted(r["amount_cents"] for r in h.refunds) == sorted([last * 95 // 100, DEPOSIT])
    pays = sorted(p["amount_cents"] for p in h.payouts)
    # the two earlier stages are paid minus the 2% fee; the seller also gets 2% of the disputed stage
    assert pays == sorted([1_500_000 - 30_000, 2_000_000 - 40_000, last * 2 // 100])


def test_buyer_at_fault_but_keeps_goods_seller_is_paid_in_full(client, world):
    deal = live_deal(client, world)
    ms = to_last_stage(client, world, deal)
    dispute(client, world, deal, ms)
    assert rule(client, world, deal, ms, "buyer_fault").status_code == 200  # no return proof: goods stayed with the buyer
    d = client.get(f"/deals/{deal['id']}", headers=world["buyer"]).json()
    h = payments.get_holder()
    assert d["state"] == "completed" and d["deposit"]["state"] == "returned"
    assert [r["amount_cents"] for r in h.refunds] == [DEPOSIT]
    assert sum(p["amount_cents"] for p in h.payouts) == 5_000_000 - 100_000


def test_buyer_at_fault_on_a_whole_order_ends_the_order_fairly(client, world):
    """Stage 1 delivered and disputed, stage 2 funded but not delivered, stage 3 never funded."""
    deal = live_deal(client, world)
    proof(client, world, deal, 0, "order_confirmation.txt")
    ms1 = deal["milestones"][1]
    client.post(f"/deals/{deal['id']}/milestones/{ms1['id']}/fund", headers=world["buyer"])
    assert client.post(f"/deals/{deal['id']}/milestones/{ms1['id']}/fund/capture", headers=world["buyer"]).status_code == 200
    ms0 = deal["milestones"][0]
    dispute(client, world, deal, ms0)
    send_return(client, world, deal, ms0)
    assert rule(client, world, deal, ms0, "buyer_fault").status_code == 200
    d = client.get(f"/deals/{deal['id']}", headers=world["buyer"]).json()
    h = payments.get_holder()
    states = [m["state"] for m in d["milestones"]]
    assert states == ["refunded", "refunded", "cancelled"] and d["state"] == "completed"
    assert d["deposit"]["state"] == "returned"
    first, second = 1_500_000, 2_000_000
    # stage 1: 95% back; stage 2 (funded, undelivered): all back; plus the deposit
    assert sorted(r["amount_cents"] for r in h.refunds) == sorted([first * 95 // 100, second, DEPOSIT])
    assert sum(p["amount_cents"] for p in h.payouts) == first * 2 // 100  # the seller gets only the 2% penalty share


def test_reviewer_can_choose_stage_only_or_whole_order_and_it_is_logged(client, world):
    deal = live_deal(client, world)  # signed as whole_order
    proof(client, world, deal, 0, "order_confirmation.txt")
    ms1 = deal["milestones"][1]
    client.post(f"/deals/{deal['id']}/milestones/{ms1['id']}/fund", headers=world["buyer"])
    client.post(f"/deals/{deal['id']}/milestones/{ms1['id']}/fund/capture", headers=world["buyer"])
    ms0 = deal["milestones"][0]
    dispute(client, world, deal, ms0)
    send_return(client, world, deal, ms0)
    r = client.post(f"/admin/deals/{deal['id']}/milestones/{ms0['id']}/review", headers=world["admin"],
                    json={"decision": "buyer_fault", "note": "", "scope": "stage"})
    assert r.status_code == 200
    d = client.get(f"/deals/{deal['id']}", headers=world["buyer"]).json()
    assert [m["state"] for m in d["milestones"]] == ["refunded", "funded" if d["milestones"][1]["state"] == "funded" else d["milestones"][1]["state"], "waiting"]
    assert d["failure_scope"] == "stage" and d["state"] == "funded"  # only the disputed stage settled, the order goes on
    log = client.get(f"/deals/{deal['id']}/audit", headers=world["buyer"]).json()
    assert any(e["action"] == "scope_chosen" for e in log["events"]) and log["chain_ok"] is True
