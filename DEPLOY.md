# Deploy the demo (free tiers)

You need: a GitHub account, and free accounts on Neon, Render and Vercel. Total time about 40 minutes.
Everything here uses **sandbox / test money only**. Never put live payment keys in the demo.

## 0. Check your keys first (5 min, on your PC)
```bash
cd backend
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                   # fill in GEMINI_API_KEY and the PAYPAL_* sandbox values
python ../scripts/live_smoke.py --receiver <a-sandbox-personal-account-email>
```
Fix anything that says FAIL before you deploy. The script asks you to approve one $2.00 sandbox payment.
Sandbox accounts: developer.paypal.com > Testing Tools > Sandbox Accounts. Make one Personal (buyer) and one Personal (seller).

## 1. Database (Neon)
Create a free project at neon.tech, copy the connection string, and change the start to `postgresql+psycopg://`.

## 2. API (Render)
Push this repo to GitHub. On render.com choose New > Blueprint, pick the repo (it reads `render.yaml`), then set:
`ADMIN_EMAIL` (your email, this account becomes the admin), `DATABASE_URL` (from step 1), and leave `CORS_ORIGINS`
and `PUBLIC_APP_URL` empty for now. Deploy. Open `https://<your-api>.onrender.com/health`: it should say ok.
The free plan sleeps after inactivity; open the health link a minute before you record or present.

## 3. Frontend (Vercel)
On vercel.com import the repo, set the root directory to `frontend`, and add the variable
`VITE_API_URL=https://<your-api>.onrender.com`. Deploy. Copy the Vercel URL.

## 4. Connect them
Back on Render set `CORS_ORIGINS` and `PUBLIC_APP_URL` to the Vercel URL and redeploy.

## 5. Turn on the real services
Only after the smoke test passed: set `PAYPAL_MODE=sandbox`, `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET`,
`AI_PROVIDER=gemini`, `GEMINI_API_KEY`. For PayPal webhooks, create a webhook in the sandbox app pointing to
`https://<your-api>.onrender.com/webhooks/paypal` for `PAYMENT.CAPTURE.COMPLETED` and put its id in `PAYPAL_WEBHOOK_ID`.

## 6. Create the demo accounts
Register with your ADMIN_EMAIL (becomes admin), then a seller and a buyer. Verify them in the Admin screen.
The seller registers with a PayPal sandbox personal email so payouts have a destination.

## Email (optional)
Set `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` (a Gmail app password works for a demo).
Without them, notifications still show in the bell inside the app.

## Notes
- Gemini free tier may use your inputs to improve Google's products. Use only fake documents.
- The demo creates database tables automatically. A production version should use migrations.
