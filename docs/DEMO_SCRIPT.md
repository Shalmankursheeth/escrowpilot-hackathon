# Demo video script (about 2:30, hard limit 3:00)

**Goal:** show the project working end to end, with the fault split as the long scene. PayPal moves the money, AI only reads paperwork, and fair rules signed in advance decide every outcome. The rules score Presentation on "working end-to-end", so the video starts at a new order and ends at a settled one.

## Before you record
- **Window:** 1080p, light theme, browser zoom 110%, one clean tab. Fake data only. Record the screen with no sound, then add the narration (a human or an AI voice; say "narration is AI-generated" in the YouTube description if it is).
- **Servers:** open the API health link a minute before so the free server is awake. `PAYPAL_MODE=sandbox`.
- **Accounts (all verified, connected):** buyer (Nordic Home Imports), seller (Kaveri Exports), admin, and a second admin (`reviewer2@escrowpilot.demo`).
- **PayPal:** log into the US sandbox buyer account in this browser first, so each approval is one click on **Pay**.
- **Two orders** (the duplicate-file check flags the same file used in two open orders, so keep their documents different):
  - **Order A (live in the video, scenes 2 to 4):** a fresh 3-stage order with `sample_docs/pdf/order_confirmation.pdf` and the wrong-quantity bill of lading.
  - **Order B (pre-built, scenes 5 to 7):** three stages, `Standard 30 / 40 / 30`, 10,000 USD (3,000 / 4,000 / 3,000), 5% deposit, scope whole order, release on completion. Stages 1 and 2 are funded, delivered and verified (held in escrow), stage 3 is funded and disputed. Prepare it up to "buyer disputed stage 3, return receipt uploaded, seller confirmed the returned goods". Use, in order: `order_confirmation_B.pdf`, `bill_of_lading_B.pdf`, `delivery_receipt_B.pdf`, then `return_receipt_B.pdf` from `sample_docs/orderB/` (new document numbers, dates in order). Disputing the last stage completes the order, so the deposit returns right after the final ruling.
- **Do not reuse a deal whose audit shows "Chain broken".** Always start Order A and B fresh.

## The money rules (know these cold)
- The buyer pays each stage into escrow. The seller pays a refundable **5% security deposit** first. In the demo the platform's PayPal account holds both; in production a licensed partner does.
- Good order: the seller is paid minus a **2% fee**, the deposit comes back, the buyer pays no fee.
- **Seller at fault:** buyer fully refunded plus 2% of the order from the seller's deposit; the platform keeps 3%. With whole-order scope, every funded stage goes back to the buyer as one combined refund.
- **Buyer at fault, goods returned:** buyer refunded minus 5% of that stage; seller gets 2%, platform 3%, deposit returns. With whole-order scope, delivered stages are paid and funded, undelivered stages go back in full.
- **No refund before the seller checks the returned goods** (5 days, no answer counts as confirmed).
- The reviewer chooses **Refund this stage** or **Full return, whole order** (default: what both signed; a change is logged). The reviewer names the fault, the ruling waits **48 hours**, one **appeal** goes to a different reviewer and that decision is final.

## Shot list
Order B numbers: the two delivered stages are paid ($3,000 and $4,000 minus the 2% fee = $2,940 and $3,920). The disputed $3,000 stage: buyer $2,850 back, seller $60, platform $90. Platform earns $230 in total, and the $500 deposit returns to the seller. If the first ruling (seller at fault) were final instead, the buyer would get all $10,000 back as one combined refund.

| Time | On screen | Say |
|---|---|---|
| 0:00 | Landing page | "A big export order went wrong and there was nothing to point to. Trust is great. Terms are better." |
| 0:10 | New order (Order A): the plain-language "What you are both agreeing to" list, both sign | "Buyer and seller agree milestones and exactly what happens if it goes wrong, and both sign the same version. Change a word and the signatures are voided." |
| 0:25 | Seller deposit or the first stage payment: bottom sheet, PayPal page, **Pay**, success animation | "PayPal moves the money. The seller puts down a five percent deposit first, so both sides have something to lose." |
| 0:40 | Seller uploads `order_confirmation.pdf`, then the wrong-quantity bill of lading is flagged with the exact reason | "Gemini reads the paperwork. Plain code compares it to what both signed. Eight hundred, not a thousand: nothing moves. The AI reads. It never decides who gets paid." |
| 1:00 | Switch to Order B in the admin queue. **AI evidence summary** | "Here is a dispute. The goods came back. The reviewer gets facts only, never a verdict." |
| 1:10 | Show the scope switch (**Refund this stage** or **Full return, whole order**), tap **Seller at fault**, show the 48-hour banner | "The reviewer picks how far the ruling goes, and names the fault. Nothing moves for 48 hours." |
| 1:25 | Seller view: type a reason, **Appeal once** | "The seller appeals, once." |
| 1:35 | Second reviewer: **Buyer at fault** | "A different reviewer decides, and that is final. They overturn it." |
| 1:45 | Deal screen, then the **Money** tab (PayPal refund and payout in the log, platform earned, "Deposit returned") | "The two stages already delivered are paid. Only the disputed stage carries the penalty: the buyer is refunded minus five percent, the seller keeps two, the platform three. The deposit comes straight back. Every number was signed in advance." |
| 2:15 | Audit trail **Show**, "Chain intact" | "Every step is in a tamper-evident log, and every payout has an idempotency key, so nothing is paid twice." |
| 2:25 | Closing card | "EscrowPilot: PayPal moves the money, Gemini reads the paperwork, fair rules decide. Sandbox today. Next, a licensed partner for live funds." |

## If something goes wrong on camera
- **PayPal page slow:** cut the wait in editing.
- **A document is flagged unexpectedly:** it is a duplicate. Use a copy with a different `Date:` line or set `DUPLICATE_DOC_CHECK=false` for the recording.
- **Gemini error:** the offline reader takes over for text files; keep text copies handy.
- **A red error or a double ruling:** the buttons now lock while a ruling is sent; if it still happens, cut and retake from a fresh order.

## Say plainly (judges respect honesty)
- PayPal is **sandbox** and the documents are fake.
- In production a licensed partner holds the money; payment partners also charge their own fees on top of our 2%.
- AI never decides. It reads documents and writes a neutral summary; people name the fault and code applies the numbers.
- The video does not show the buyer-keeps-goods case, the seller's mismatch report, or the 48-hour wait; mention these in the Devpost text.
