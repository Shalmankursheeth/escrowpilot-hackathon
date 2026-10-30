# Devpost story (paste into the sections)

## Inspiration
Small and mid-sized exporters trade on relationships that last decades. When an order is large, that trust is the only protection they have, and it fails more often than anyone admits: a buyer pays late, short, or not at all, or goods come back and nobody agreed who pays. Letters of credit solve it but are slow and expensive, so small traders skip them. We wanted the safety of escrow with the ease of a handshake.

## What it does
EscrowPilot is milestone escrow for importers and exporters.
- Buyers and sellers find each other by unique id, connect, and propose the payment terms inside the app: milestones, inspection window, and what happens if delivery fails (refund percent, return shipping, proof of return). Both sign the same version; any edit voids the signatures.
- The buyer pays each stage into escrow through PayPal just before it starts (or everything up front, if both agree), so nobody has to tie up the whole price. Money moves per stage only when the seller's documents (PDF, photo or text) match the signed terms.
- Gemini reads the documents and extracts fields. Plain code compares them to the contract. A mismatch goes to a review queue with the exact reason. The AI never decides who gets paid.
- After delivery the buyer has an inspection window. A dispute plus proof of return shipment unlocks a refund of exactly the signed percent.
- Every step is written to a hash-chained audit log, payouts use idempotency keys so nothing is paid twice, and a trust profile builds from real deal history.
The seller also pays a refundable 5% security deposit. If the seller is ruled at fault, the buyer gets a full refund plus 2% and we keep 3% of the deposit. If the buyer is at fault, they lose 5% (2% to the seller, 3% to us). Fairness by design: a fault ruling waits 48 hours, either side can appeal once to a different reviewer, documents are cross-checked against earlier stages, a reused file is flagged, and the reviewer sees a facts-only AI summary that never recommends a verdict. Revenue: a 2% fee on each released milestone.

## How we built it
FastAPI and SQLAlchemy backend, React frontend, PostgreSQL in production (SQLite locally). PayPal Orders and Payouts APIs in sandbox, behind a small funds-holder interface so a licensed partner can replace it. Gemini (free tier) extracts document fields as JSON; the document is treated as untrusted text and the model has no tools. A deterministic rules engine owns every payment decision. 20 automated tests cover the full flow, mismatches, disputes, refunds, idempotency, permissions and uploads.

## Challenges we ran into
Deciding where AI belongs. Letting a model approve payments is a security hole, so it only extracts facts and code decides. PayPal authorisation holds expire after 29 days, so we capture up front and pay out per milestone. Designing failure terms that are signed in advance without becoming a legal contract engine.

## Accomplishments that we're proud of
A complete flow from signed terms to settled or refunded, with the failure path as carefully built as the happy path, and a test suite that proves money cannot move twice or without a verified milestone.

## What we learned
In trade, the hard part is not moving money, it is agreeing in advance on what counts as done and what happens when it is not.

## What's next
Pilots with real exporters, first in shadow mode (their orders, documents and terms in EscrowPilot while money moves as today), then funded escrow through a licensed partner. After that, financing offered by partner lenders against verified, funded orders, and a trust score from deal history.

## Built with
python, fastapi, sqlalchemy, postgresql, react, vite, paypal, paypal-payouts, gemini, google-gemini, pypdf, jwt, vercel, render

## Try it out links
- Live demo: [Vercel URL]
- Code: [GitHub URL]
- Demo accounts and sample PDFs: see README

## Before you submit (checklist)
- [ ] `live_smoke.py` passes for Gemini and PayPal sandbox with your keys
- [ ] Render API and Vercel frontend deployed, health link works, CORS set
- [ ] Demo accounts created and verified; sample PDFs tested on the live site
- [ ] Repo is public with MIT licence and no secrets (check `.env` is not committed)
- [ ] Video under the Devpost length limit, uploaded to YouTube as public or unlisted
- [ ] Devpost tags: remove claude and anthropic, add gemini and google-gemini
- [ ] Say in the story that PayPal is sandbox and documents are fake
- [ ] Submit on Nov 11; the deadline is Nov 12, 12:00 pm Pacific (about 12:30 am IST on Nov 13)
