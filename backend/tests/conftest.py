import os
import pathlib
import tempfile

_tmp = tempfile.mkdtemp()
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp}/test.db"
os.environ["SECRET_KEY"] = "test-secret-key-that-is-long-enough-32b"
os.environ["PAYPAL_MODE"] = "mock"
os.environ["COOLING_OFF_HOURS"] = "0"  # rulings apply at once unless a test turns the cooling-off on
os.environ["ADMIN_EMAIL"] = "admin@example.com,reviewer2@example.com"
os.environ["AI_PROVIDER"] = "offline"
os.environ["TIMER_INTERVAL_SECONDS"] = "0"

import pytest
from fastapi.testclient import TestClient

from app import payments
from app.db import Base, engine
from app.main import app

DOCS = pathlib.Path(__file__).resolve().parents[2] / "sample_docs"


def doc(name: str) -> str:
    return (DOCS / name).read_text()


@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    payments.reset_holder()
    with TestClient(app) as c:
        yield c


def register(client, email, role, company):
    r = client.post("/auth/register", json={"email": email, "password": "password123", "role": role,
                                            "company_name": company, "paypal_email": f"{role}@sandbox.example.com"})
    assert r.status_code == 201, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}, r.json()["user"]["id"], r.json()["user"]["public_id"]


@pytest.fixture()
def world(client):
    admin, _, _ = register(client, "admin@example.com", "buyer", "Admin Co")
    seller, sid, spid = register(client, "seller@example.com", "seller", "Kaveri Exports")
    buyer, bid, bpid = register(client, "buyer@example.com", "buyer", "Nordic Home Imports")
    for uid in (sid, bid):
        assert client.post(f"/admin/users/{uid}/verify", headers=admin).status_code == 200
    return {"admin": admin, "seller": seller, "buyer": buyer, "seller_pid": spid, "buyer_pid": bpid}


def connect(client, w):
    r = client.post("/connections", headers=w["seller"], json={"public_id": w["buyer_pid"]})
    assert r.status_code == 201, r.text
    assert client.post(f"/connections/{r.json()['id']}/accept", headers=w["buyer"]).status_code == 200


TERMS = {
    "total_amount": "50000.00", "goods": "granite countertop slabs", "quantity": 1000, "inspection_days": 3,
    "milestones": [
        {"name": "Order confirmation", "share_pct": 30, "required_proof": "order_confirmation"},
        {"name": "Shipment", "share_pct": 40, "required_proof": "bill_of_lading"},
        {"name": "Delivery", "share_pct": 30, "required_proof": "delivery_receipt"},
    ],
    "return_refund_pct": 100, "return_shipping_by": "seller", "return_proof_required": True,
    "return_check_days": 0,  # most tests skip the seller's check of returned goods; test_return_check.py turns it on
    "release_rule": "per_stage", "failure_scope": "stage", "seller_deposit_pct": 0,
}


def fund_ms(client, w, deal, idx):
    """Buyer pays one milestone into escrow (the usual pay-as-you-go step). Returns the capture response."""
    ms = deal["milestones"][idx]
    r = client.post(f"/deals/{deal['id']}/milestones/{ms['id']}/fund", headers=w["buyer"])
    if r.status_code != 200:
        return r
    return client.post(f"/deals/{deal['id']}/milestones/{ms['id']}/fund/capture", headers=w["buyer"])


def fund_ms(client, w, deal, idx):
    """Buyer pays one milestone into escrow (the usual pay-as-you-go step). Returns the capture response."""
    ms = deal["milestones"][idx]
    r = client.post(f"/deals/{deal['id']}/milestones/{ms['id']}/fund", headers=w["buyer"])
    if r.status_code != 200:
        return r
    return client.post(f"/deals/{deal['id']}/milestones/{ms['id']}/fund/capture", headers=w["buyer"])


def make_funded_deal(client, w, terms=None):
    """A signed deal that is live. Default terms are pay-as-you-go, so only milestone 1 is funded here;
    `proof()` funds each later milestone just before the seller submits it. Pass funding_mode='upfront' to fund everything."""
    terms = terms or TERMS
    connect(client, w)
    r = client.post("/deals", headers=w["seller"], json={
        "title": "Granite slabs", "counterparty_id": w["buyer_pid"], "terms": terms})
    assert r.status_code == 201, r.text
    deal = r.json()
    for who in ("seller", "buyer"):
        assert client.post(f"/deals/{deal['id']}/confirm", headers=w[who], json={"version": 1}).status_code == 200
    if terms.get("funding_mode") == "upfront":
        assert client.post(f"/deals/{deal['id']}/fund", headers=w["buyer"]).status_code == 200
        r = client.post(f"/deals/{deal['id']}/fund/capture", headers=w["buyer"])
    else:
        r = fund_ms(client, w, deal, 0)
    assert r.status_code == 200 and r.json()["state"] == "funded", r.text
    return r.json()


def proof(client, w, deal, idx, name):
    fund_ms(client, w, deal, idx)  # no-op if already funded; refused if an earlier milestone is unsettled
    ms = deal["milestones"][idx]
    return client.post(f"/deals/{deal['id']}/milestones/{ms['id']}/proof", headers=w["seller"],
                       json={"filename": name, "text": doc(name)})
