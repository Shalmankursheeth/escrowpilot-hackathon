# EscrowPilot (sandbox demo)

AI-assisted milestone escrow for importers and exporters. **Test money only.** This public repo uses a mock payment provider by default and the PayPal sandbox if you add keys. A licensed partner holds real funds in the private production version.

## How it works
1. Everyone signs up and gets a unique id (like `EP-7K2M9Q`). An admin verifies accounts (simulated KYC).
2. A buyer and a seller find each other by id, send a connection request, and the other side accepts. Orders can only be made between connected traders.
3. Either side creates an order and proposes the payment terms: total, milestones, inspection window, and the **failure and return terms** (refund percent, who pays return shipping, whether proof of return is required). The AI can optionally draft terms from a pasted contract. Either side can counter-propose; every edit voids both signatures. Both sign a specific version.
4. The buyer pays each stage into escrow just before it starts (PayPal order, captured into the platform sandbox account), or the whole price up front if both agree. The seller cannot submit proof for a stage until it is funded.
5. The seller submits proof per milestone. The AI only *extracts fields*; plain code compares them to the signed terms. A match releases that milestone's payout (minus the fee). A mismatch goes to an admin queue.
6. After delivery there is an inspection window. The buyer can dispute. If the signed terms require it, the buyer uploads a return receipt. A refund then follows exactly the signed refund percent, and the seller keeps the rest. Otherwise a timer releases the last payment.
7. Every step is written to a hash-chained audit log. Payouts use idempotency keys so nothing is paid twice.

The AI never decides money. The rules engine does.

**Money rules.** The seller pays a refundable 5% security deposit (a signed term, 0 to 20%) before the buyer funds. A good order pays the seller minus a 2% fee and returns the deposit. In a dispute a reviewer names who was at fault. Seller at fault: the buyer is refunded in full plus 2% of the order from the deposit, and the platform keeps 3%. Buyer at fault with goods returned: refund minus 5% (2% to the seller, 3% to the platform). Buyer at fault but keeps the goods: the seller is paid in full minus the fee.

**Fairness checks.** A fault ruling waits 48 hours (`COOLING_OFF_HOURS`); either side can appeal once and a different admin decides (list several in `ADMIN_EMAIL`, comma separated). New documents are cross-checked against earlier stages (quantity, dates) and an identical file reused in another open order is flagged (`DUPLICATE_DOC_CHECK`). The reviewer gets a facts-only AI summary that never recommends a ruling. Past fault rulings show on trust profiles as counts.

## Run locally (no keys needed)
```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # set SECRET_KEY and ADMIN_EMAIL
set -a; source .env; set +a
uvicorn app.main:app --reload
```
API docs at http://localhost:8000/docs. Register with the ADMIN_EMAIL address to get the admin role.

Tests: `cd backend && python -m pytest -q`. Sample documents are in `sample_docs/`.

## Run the frontend
```bash
cd frontend
npm install
cp .env.example .env     # VITE_API_URL=http://localhost:8000
npm run dev              # http://localhost:5173
```
Demo walk-through: register an admin (the ADMIN_EMAIL address), a seller and a buyer; verify both in the Admin screen; connect them by id; create an order; both sign; the buyer pays; the seller loads the sample documents (try the wrong-quantity one); then dispute and return to see the signed refund.

## Documents, notifications, deploy
- Proof can be uploaded as PDF, PNG, JPEG or text (5 MB max). PDFs with text are read directly; scans and photos need Gemini. Sample PDFs are in `sample_docs/pdf/`.
- Notifications appear in the in-app bell; set `SMTP_*` to also send email.
- `scripts/live_smoke.py` checks your Gemini and PayPal sandbox keys. `DEPLOY.md` has the free-tier deploy steps. `docs/` has the demo script and Devpost story.

## Turn on Gemini (free tier)
Get a key at Google AI Studio, then set `AI_PROVIDER=gemini` and `GEMINI_API_KEY=...`. If Gemini fails, it falls back to the offline rules. *The Gemini client is not tested live in this repo yet.*

## Turn on PayPal sandbox
Create a sandbox app at developer.paypal.com, then set `PAYPAL_MODE=sandbox`, `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`, and a webhook id pointing at `/webhooks/paypal`. Payouts must be enabled for the sandbox app. Seller accounts need a `paypal_email` that is a sandbox account. *The PayPal client is not tested live yet; run one funding and one payout before relying on it.*

## Security notes
- Secrets only from environment variables; `.env` is git-ignored.
- Passwords hashed with bcrypt; JWT sessions; role checks on every route; users only see their own deals.
- Money is stored as integer cents. Uploads are size-limited. Documents are treated as untrusted text by the AI prompts.
- Demo shortcuts: tables auto-created, KYC is a button, no rate limiting. Production replaces these.

## Free hosting
API on Render, frontend on Vercel, Postgres on Neon or Supabase (set `DATABASE_URL`).

## Licence
MIT
