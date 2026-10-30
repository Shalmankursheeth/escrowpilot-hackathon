# Demo video script (2:50, hard limit 3:00)

**Goal of the video:** in three minutes show that PayPal moves the money, AI only reads the paperwork, and fair rules (signed in advance, with a deposit, a returned-goods check, a cooling-off and an appeal) decide every outcome.

## Before you record
- **Window:** 1080p, light theme, browser zoom 110%, one clean tab. Mic close. Fake data only.
- **Servers:** open the API health link a minute before so the free server is awake. Sandbox PayPal keys set (`PAYPAL_MODE=sandbox`).
- **Accounts (all verified, connected by id):** buyer (Nordic Home Imports), seller (Kaveri Exports), admin, and a **second admin** (list both in `ADMIN_EMAIL`, comma separated). Every account has a PayPal sandbox email.
- **PayPal:** log into the US sandbox **buyer** account in this browser first, so each approval is one click on **Pay**. Seller deposit is also paid with the sandbox buyer account (it is only a stand-in).
- **Two orders, recorded in this order** (the duplicate-file check flags one file reused in two *open* orders, so finish or leave deals as described):
  - **Order A (happy path and the flag):** record live in the video.
  - **Order B (the dispute):** prepare it before recording, up to "buyer disputed, return receipt uploaded, seller confirmed the returned goods". Use documents with a different `Date:` line from Order A's, so nothing is flagged as a duplicate. You will show only the admin ruling, appeal and result.
- **Files ready:** `sample_docs/pdf/order_confirmation.pdf`, `bill_of_lading_wrong_quantity.pdf`, `bill_of_lading_ok.pdf`.
- Set `COOLING_OFF_HOURS=48` (default). You never wait: the appeal stops the timer and the second reviewer decides at once.

## The money rules (know these cold)
- Buyer pays each stage into escrow (or the full price). The seller pays a refundable **5% security deposit** first. Both are held by the platform's PayPal account in the demo; in production a licensed partner holds them.
- Good order: the seller is paid minus a **2% fee**, and the deposit comes back in full. The buyer pays no fee.
- **Seller at fault:** buyer gets a full refund plus 2% of the order, paid from the seller's deposit; the platform keeps 3%.
- **Buyer at fault, goods returned:** buyer is refunded minus 5% of that stage. The seller gets 2%, the platform 3%, and the deposit returns. If the buyer keeps the goods, the seller is paid in full.
- **No refund before the seller checks the returned goods.** After the return proof is accepted, the seller has 5 days (signed term) to confirm the goods match what was shipped or report a mismatch. No answer counts as confirmed. A reported mismatch goes to a reviewer and the refund waits; if it stands and the buyer is at fault, the seller is paid in full.
- A **reviewer** names who was at fault. The AI only summarizes facts and never recommends. A ruling waits **48 hours**; either side can **appeal once**; a **different reviewer** decides and that is final.

## Shot list

| Time | On screen | Say |
|---|---|---|
| 0:00 | Landing page: headline, live-looking order card, login card | "Thirty years of handshakes built this exporter's business. Then one big order went wrong and there was nothing to point to. Trust is great. Terms are better." |
| 0:12 | New order: the builder, plan bar, then the plain-language "What you are both agreeing to" list. Both sign. | "A buyer anywhere and a seller connect by id. They agree milestones and exactly what happens if it goes wrong, in plain words, and both sign the same version. Change a word and the signatures are voided." |
| 0:32 | Seller pays the 5% deposit: the bottom sheet, then PayPal's page, **Pay**, success animation | "The seller puts down a five percent deposit first. Until it is held, the buyer cannot fund. Both sides have something to lose." |
| 0:47 | Buyer funds stage 1 the same way: sheet, PayPal, **Pay**, "Stage 1 funded", the plan bar fills | "The buyer pays one stage at a time, just before it starts. PayPal's Orders API collects it. In this demo the platform's PayPal account holds it; in production a licensed partner does." |
| 1:02 | Seller uploads `order_confirmation.pdf`: "Verified against the signed terms" toast | "Gemini reads the paperwork and extracts fields. Plain code compares them to what both signed. It matches, so the stage is verified." |
| 1:14 | Seller uploads `bill_of_lading_wrong_quantity.pdf`: flagged with the exact reason. Linger. | "Eight hundred units, not a thousand. Nothing moves. It goes to review with the exact reason. The AI reads. It never decides who gets paid. Documents are also cross-checked against earlier stages, and a reused file is flagged." |
| 1:30 | Switch to **Order B**, admin queue: click **AI evidence summary** | "Here is a dispute. The buyer says the slabs arrived cracked and sent them back with a return receipt. The reviewer gets a summary of facts only. It never says who is at fault." |
| 1:45 | Show the seller's **returned goods check** (already confirmed), then admin clicks **Seller at fault**: the "takes effect in 48 hours, either side can appeal" banner | "The seller has already confirmed the returned goods are the same ones, because no refund moves before that check. The reviewer rules the seller at fault, but nothing moves for 48 hours, so either side can appeal." |
| 2:00 | Seller view: types an appeal reason, **Appeal once** | "The seller says the damage happened in transit and appeals, once." |
| 2:10 | Log in as the **second reviewer**: queue shows "Appealed", **Buyer at fault**. The deal screen updates: refunded, released, "Deposit returned". | "A different reviewer must decide, and that decision is final. They overturn it. The buyer is refunded minus five percent of that stage, the seller keeps two percent of it, the platform three, and the seller's deposit comes straight back. Every number was signed in advance." |
| 2:35 | Audit trail: **Show**, "Chain intact" | "Every step is in a tamper-evident log, and every payout has an idempotency key, so nothing is paid twice." |
| 2:44 | Closing card | "EscrowPilot: PayPal moves the money, Gemini reads the paperwork, fair rules decide. Sandbox today. Next, a licensed partner for live funds. Keep the relationship, protect the money." |

## If something goes wrong on camera
- **PayPal page slow:** cut the wait in editing. Never wait live.
- **A document is flagged unexpectedly:** it is a duplicate (the same file used in another open order). Use a copy with a different `Date:` line or set `DUPLICATE_DOC_CHECK=false` for the recording.
- **Gemini error:** the offline reader takes over for text files, so keep a text copy of each document handy.

## Say plainly (judges respect honesty)
- PayPal is **sandbox** and the documents are fake.
- In production a licensed partner holds the money; the platform never holds customer funds itself. Payment partners also charge their own fees on top of our 2%.
- AI never decides. It reads documents and writes a neutral summary; people name the fault and code applies the numbers.
- The video does not show the buyer-keeps-goods case (seller is paid in full), the seller's mismatch report, or the 48-hour wait; mention these in the Devpost text.
