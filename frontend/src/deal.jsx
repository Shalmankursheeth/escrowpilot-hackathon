import { useEffect, useState } from "react";
import { api, money } from "./api.js";
import { Icon, Money, Sheet, Upload, celebrate, label, toast, useAction } from "./common.jsx";
import { PlanBar, TermsForm } from "./plan.jsx";
import { sampleDoc } from "./samples.js";

const SETTLED = ["released", "refunded", "cancelled"];
const STAGE_DONE = [...SETTLED, "accepted", "cancelled"]; // finished, though the money may still be locked
const status = (m) => (m.state === "released" ? "done" : m.state === "refunded" ? "refunded" : m.state === "flagged" ? "flagged"
  : m.state === "approved_hold" || m.state === "accepted" ? "hold" : m.funded ? "funded" : "idle");

function nextStep(d) {
  const role = d.my_role;
  if (d.state === "draft") return ["Both sides must sign the terms", "Read the plan below. Either side can counter-propose; any change voids both signatures."];
  if (d.state === "cancelled") return ["Order closed", "The buyer did not fund before the signed deadline. Nothing was locked, so nothing moved."];
  if (d.state === "completed") return ["All done", "Every stage is settled. The audit trail below shows each step."];
  if (d.state === "terms_confirmed" && d.deposit.pct > 0 && d.deposit.state === "none")
    return role === "seller" ? [`Pay your ${money(d.deposit.cents, d.currency)} security deposit`, "It is held in escrow and returned in full if the order goes well. The buyer funds after it is held."]
      : ["Waiting for the seller's security deposit", "Once it is held in escrow you can fund the order."];
  if (d.state === "terms_confirmed" && d.funding_mode === "upfront")
    return role === "buyer" ? ["Pay the full price into escrow", "The money stays locked until each stage is proven."] : ["Waiting for the buyer to fund the escrow", "You will be notified as soon as it is locked."];
  const m = d.milestones.find((x) => !STAGE_DONE.includes(x.state));
  if (!m) return ["All done", ""];
  const amt = money(m.amount_cents, d.currency);
  const due = d.fund_due_at ? ` Deadline: ${new Date(d.fund_due_at + "Z").toLocaleString()}.` : "";
  if (!m.funded) return role === "buyer" ? [`Fund stage ${m.seq}: ${amt}`, due + " It is locked in escrow before the seller starts this stage, and released only when the paperwork matches."]
    : [`Waiting for the buyer to fund stage ${m.seq}`, `${amt} will be locked in escrow before you start.${due}`];
  if (m.state === "waiting") return role === "seller" ? [`Submit the ${label(m.required_proof)} for stage ${m.seq}`, d.release_rule === "per_stage" ? `A match releases ${amt} (minus our fee) straight away.` : `A match verifies this stage. The ${amt} stays locked until the whole order is accepted.`]
    : [`Waiting for the seller's ${label(m.required_proof)}`, "It is checked against the signed terms as soon as it is uploaded."];
  if (m.state === "approved_hold") return role === "buyer" ? ["Inspect the goods", `Dispute before ${new Date(m.release_after + "Z").toLocaleString()}, or all held payments are released automatically.`]
    : ["The buyer is inspecting the goods", `Payment is released after ${new Date(m.release_after + "Z").toLocaleString()} unless they dispute.`];
  return ["A reviewer is checking this stage", "A mismatch or dispute is held until it is resolved under the signed terms."];
}

function Summary({ d }) {
  const sum = (f) => d.milestones.reduce((a, m) => a + f(m), 0);
  const locked = sum((m) => (m.funded && !SETTLED.includes(m.state) ? m.amount_cents : 0));
  const paid = sum((m) => (SETTLED.includes(m.state) ? m.paid_cents : 0));
  const fees = sum((m) => m.fee_cents);
  const back = sum((m) => (m.state === "refunded" ? m.amount_cents - m.paid_cents - m.fee_cents : 0));
  const todo = sum((m) => (!m.funded ? m.amount_cents : 0));
  return (
    <div className="stats">
      <div><small>Still to fund</small><b><Money cents={todo} currency={d.currency} /></b></div>
      <div className="blue"><small>Locked in escrow</small><b><Money cents={locked} currency={d.currency} /></b></div>
      <div className="green"><small>Paid to seller</small><b><Money cents={paid} currency={d.currency} /></b></div>
      <div><small>Refunded to buyer</small><b><Money cents={back} currency={d.currency} /></b></div>
      <div><small>Platform fee</small><b><Money cents={fees} currency={d.currency} /></b></div>
    </div>
  );
}

// One payment, start to finish: create the PayPal order, send the payer to PayPal's own page to approve, then capture.
// With the offline mock holder there is nothing to approve, so it completes instantly.
// PayPal sends the payer back to /paypal/return in the new tab; that page reads the pending payment saved here,
// captures it, and tells this tab (through localStorage) to close the sheet.
function usePayment({ start, capture, done, path, dealId }) {
  const [pay, setPay] = useState(null);
  const { busy, err, run } = useAction();
  const begin = () => run(async () => {
    const r = await start();
    if (r.approve_url.startsWith("mock://")) { await capture(); done(); return; }
    try {
      const token = new URL(r.approve_url).searchParams.get("token");
      if (token && path) localStorage.setItem("ep_pending", JSON.stringify({ token, path, dealId }));
    } catch { /* the manual button still works */ }
    setPay(r);
  });
  useEffect(() => {
    if (!pay) return;
    const onStorage = (e) => { if (e.key === "ep_done") { setPay(null); done(); } };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, [pay]);
  const finish = () => run(async () => { await capture(); setPay(null); done(); });
  const sheet = (title, amount) => pay && (
    <Sheet title={title} onClose={() => setPay(null)}>
      <div className="big" style={{ margin: "2px 0 6px" }}>{amount}</div>
      <p className="muted">You approve this payment on PayPal's own secure page. We never see your PayPal password or card.</p>
      <a href={pay.approve_url} target="_blank" rel="noreferrer" style={{ textDecoration: "none" }}><button className="pp" type="button">Continue to PayPal</button></a>
      <button className="ghost" style={{ width: "100%", marginTop: 10 }} disabled={busy} onClick={finish}>{busy && <span className="spin" />}I approved it, finish payment</button>
      {err && <div className="err">{err}</div>}
      <p className="muted" style={{ textAlign: "center", marginTop: 12 }}><Icon name="lock" size={13} /> Sandbox: test money only</p>
    </Sheet>);
  return { begin, busy, err, sheet };
}

function Stage({ d, m, reload, current }) {
  const [text, setText] = useState("");
  const [reason, setReason] = useState("");
  const [rp, setRp] = useState("");
  const [info, setInfo] = useState("");
  const { busy, err, run } = useAction();
  const isSeller = d.my_role === "seller", isBuyer = d.my_role === "buyer";
  const base = `/deals/${d.id}/milestones/${m.id}`;
  const amt = money(m.amount_cents, d.currency);
  const pay = usePayment({
    start: () => api(base + "/fund", "POST"), capture: () => api(base + "/fund/capture", "POST"), path: base + "/fund/capture", dealId: d.id,
    done: () => { celebrate(`Stage ${m.seq} funded`, `${amt} is locked in escrow`); reload(); },
  });
  const verdictToast = (r) => (r.state === "flagged" ? toast("Flagged for review: a check did not match", "bad") : toast("Verified against the signed terms"));
  const submit = () => run(async () => { verdictToast(await api(base + "/proof", "POST", { filename: label(m.required_proof) + ".txt", text })); setText(""); reload(); });
  const upload = (f) => run(async () => { verdictToast(await api(base + "/proof", "POST", f)); reload(); });
  const dispute = () => run(async () => { await api(base + "/dispute", "POST", { reason }); toast("Dispute opened. A reviewer will look at it."); reload(); });
  const [appealReason, setAppealReason] = useState("");
  const appeal = () => run(async () => { await api(base + "/appeal", "POST", { reason: appealReason }); setAppealReason(""); toast("Appeal sent to a second reviewer"); reload(); });
  const [rcNote, setRcNote] = useState("");
  const checkReturn = (ok) => run(async () => {
    await api(base + "/return-received", "POST", { ok, note: rcNote.trim() });
    setRcNote(""); toast(ok ? "Returned goods confirmed" : "Mismatch reported. A reviewer will decide.", ok ? "ok" : "bad"); reload();
  });
  const retProof = (body) => run(async () => {
    const r = await api(base + "/return-proof", "POST", body);
    setInfo(r.ok ? "Return proof accepted." : "Not accepted: " + r.reasons.join("; ")); toast(r.ok ? "Return proof accepted" : "Return proof not accepted", r.ok ? "ok" : "bad"); reload();
  });
  const st = status(m);
  return (
    <div className={"stage " + st + (current ? " current" : "")}>
      <div className="rail"><span className="node">{st === "done" ? "✓" : st === "refunded" ? "↩" : m.seq}</span></div>
      <div className="body">
        <div className="row"><b className="grow">{m.name}</b><b>{amt}</b><span className="muted">{m.share_pct}%</span><span className={"pill " + m.state}>{label(m.state)}</span></div>
        <div className="muted">
          {m.funded ? <span className="lock"><Icon name="lock" size={13} /> locked in escrow</span> : <span>not funded yet</span>} · proof needed: {label(m.required_proof)}
          {m.state === "accepted" && " · verified, held until the order is accepted"}
          {m.state === "released" && ` · paid ${money(m.paid_cents, d.currency)}, fee ${money(m.fee_cents, d.currency)}`}
          {m.state === "refunded" && ` · seller kept ${money(m.paid_cents, d.currency)} after fee`}
        </div>
        {m.verdict && <div style={{ marginTop: 8 }}><span className={"pill " + (m.verdict.outcome === "approve" ? "released" : "flagged")}>{m.verdict.outcome === "approve" ? "✓ verified" : "flagged for review"}</span>
          {m.verdict.reasons.map((r, i) => <div className="reason" key={i}>{r}</div>)}</div>}

        {isBuyer && !m.funded && d.funding_mode === "per_milestone" && ["terms_confirmed", "funded"].includes(d.state) && current && <div className="act">
          <button className="big-cta" disabled={pay.busy || !(d.deposit.pct === 0 || d.deposit.state === "held")} onClick={pay.begin}>{pay.busy && <span className="spin" />}Fund this stage · {amt}</button>
          {!(d.deposit.pct === 0 || d.deposit.state === "held") && <div className="muted" style={{ marginTop: 6 }}>Available once the seller's security deposit is held.</div>}
          {pay.err && <div className="err">{pay.err}</div>}
          {pay.sheet(`Fund stage ${m.seq}`, amt)}</div>}
        {isSeller && !m.funded && current && d.state !== "draft" && <div className="muted act">Waiting for the buyer to fund this stage. You will be notified.</div>}

        {d.state === "funded" && isSeller && m.funded && m.state === "waiting" && <div className="act">
          <label>Upload the document</label><Upload onFile={upload} busy={busy} />
          <label>…or paste its text</label><textarea value={text} onChange={(e) => setText(e.target.value)} />
          <div className="row" style={{ marginTop: 8 }}>
            <button className="ghost" onClick={() => setText(sampleDoc(d, m.required_proof))}>Load matching sample</button>
            <button className="ghost" onClick={() => setText(sampleDoc(d, m.required_proof, { wrongQty: true }))}>Sample with wrong quantity</button>
            <button disabled={busy || text.length < 10} onClick={submit}>{busy && <span className="spin" />}Submit proof</button></div></div>}
        {isBuyer && (m.state === "approved_hold" || m.state === "accepted") && <div className="act">
          <label>Something wrong? Dispute before the window ends</label>
          <div className="row"><input className="grow" placeholder="What is wrong?" value={reason} onChange={(e) => setReason(e.target.value)} />
            <button className="bad" disabled={busy || reason.length < 5} onClick={dispute}>Dispute</button></div></div>}
        {isBuyer && m.state === "flagged" && d.returns.proof_required && !m.return_proof_ok && <div className="act">
          <label>The signed terms need proof the goods were sent back</label><Upload onFile={retProof} busy={busy} />
          <label>…or paste its text</label><textarea value={rp} onChange={(e) => setRp(e.target.value)} />
          <div className="row" style={{ marginTop: 8 }}><button className="ghost" onClick={() => setRp(sampleDoc(d, "return_receipt"))}>Load sample return receipt</button>
            <button disabled={busy || rp.length < 10} onClick={() => retProof({ filename: "return_receipt.txt", text: rp })}>Submit return proof</button></div></div>}
        {m.return_proof_ok && m.state === "flagged" && m.return_received === "mismatch" && <div className="reason" style={{ marginTop: 8 }}>
          <b>The seller reports the returned goods do not match what was shipped.</b> {m.return_received_note} No refund moves until a reviewer decides.</div>}
        {m.return_proof_ok && m.state === "flagged" && !m.ruling && m.return_received !== "mismatch" && (d.returns.check_days === 0 || m.return_received === "confirmed") &&
          <div className="ok" style={{ marginTop: 8 }}>✓ Return proof accepted{m.return_received === "confirmed" ? " and the returned goods were confirmed" : ""}. Waiting for the reviewer's decision.</div>}
        {m.return_proof_ok && m.state === "flagged" && m.return_received === null && d.returns.check_days > 0 && (isSeller ? <div className="act">
          <label>The goods are back. Check them against what you shipped (serial numbers, seals, photos){m.return_check_due_at ? ` before ${new Date(m.return_check_due_at + "Z").toLocaleDateString()}` : ""}</label>
          <input placeholder="Note (required if something is wrong)" value={rcNote} onChange={(e) => setRcNote(e.target.value)} />
          <div className="row" style={{ marginTop: 8 }}>
            <button disabled={busy} onClick={() => checkReturn(true)}>Goods match, confirm</button>
            <button className="bad" disabled={busy || rcNote.trim().length < 5} onClick={() => checkReturn(false)}>Goods do not match</button></div>
          <div className="muted" style={{ marginTop: 6 }}>No answer by the date counts as confirmed. The refund moves only after this check.</div></div>
          : <div className="muted" style={{ marginTop: 8 }}>Return proof accepted. The seller is checking the returned goods{m.return_check_due_at ? ` (until ${new Date(m.return_check_due_at + "Z").toLocaleDateString()})` : ""}. No refund moves before that.</div>)}
        {m.ruling && m.state === "flagged" && !m.appealed && <div className="act">
          <div className="next" style={{ display: "block", margin: 0 }}><b>A reviewer ruled the {m.ruling} at fault.</b>{m.ruling_note ? ` Reason: ${m.ruling_note}.` : ""}
            <div className="muted">It takes effect {m.ruling_due_at ? new Date(m.ruling_due_at + "Z").toLocaleString() : "soon"}. Either side can appeal once before then.</div></div>
          {(isBuyer || isSeller) && <div className="row" style={{ marginTop: 8 }}><input className="grow" placeholder="Why do you appeal?" value={appealReason} onChange={(e) => setAppealReason(e.target.value)} />
            <button className="bad" disabled={busy || appealReason.length < 5} onClick={appeal}>Appeal once</button></div>}</div>}
        {m.appealed && m.state === "flagged" && <div className="reason" style={{ marginTop: 8 }}><b>Appealed.</b> A second reviewer will decide, and that decision is final.{m.appeal_reason ? ` Reason given: ${m.appeal_reason}` : ""}</div>}
        {info && <div className="muted">{info}</div>}
        {err && <div className="err">{err}</div>}
      </div>
    </div>
  );
}

export default function Deal({ id, me, go }) {
  const [d, setD] = useState(null);
  const [audit, setAudit] = useState(null);
  const [edit, setEdit] = useState(false);
  const { busy, err, run } = useAction();
  const reload = () => api("/deals/" + id).then(setD).catch(() => {});
  useEffect(() => { reload(); const t = setInterval(reload, 15000); return () => clearInterval(t); }, [id]);
  const upfront = usePayment({
    start: () => api(`/deals/${id}/fund`, "POST"), capture: () => api(`/deals/${id}/fund/capture`, "POST"), path: `/deals/${id}/fund/capture`, dealId: id,
    done: () => { celebrate("Escrow funded", "The full price is locked in escrow"); reload(); },
  });
  const deposit = usePayment({
    start: () => api(`/deals/${id}/deposit`, "POST"), capture: () => api(`/deals/${id}/deposit/capture`, "POST"), path: `/deals/${id}/deposit/capture`, dealId: id,
    done: () => { celebrate("Deposit held", "The buyer can now fund the order"); reload(); },
  });
  if (!d) return <div className="card"><div className="skel" style={{ height: 28, width: "50%" }} /><div className="skel" /><div className="skel" style={{ width: "70%" }} /></div>;
  const mine = d.my_role === "buyer" ? "buyer_confirmed" : "seller_confirmed";
  const initial = { total_amount: String(d.total_cents / 100), currency: d.currency, goods: d.goods, quantity: d.quantity, funding_mode: d.funding_mode, release_rule: d.release_rule, failure_scope: d.failure_scope, funding_deadline_days: d.funding_deadline_days, default_penalty_pct: d.default_penalty_pct, seller_deposit_pct: d.deposit.pct,
    inspection_days: d.inspection_days, milestones: d.milestones.map((m) => ({ name: m.name, share_pct: m.share_pct, required_proof: m.required_proof })),
    return_refund_pct: d.returns.refund_pct, return_shipping_by: d.returns.shipping_by, return_proof_required: d.returns.proof_required, return_check_days: d.returns.check_days };
  const [title, text] = nextStep(d);
  const currentId = d.milestones.find((m) => !STAGE_DONE.includes(m.state))?.id;
  const depLabel = { none: "Not paid yet", held: "Held in escrow", returned: "Returned to the seller", forfeited: "Forfeited" }[d.deposit.state];
  return (
    <div>
      <button className="ghost small" onClick={() => go("home")}><Icon name="back" size={14} />All orders</button>
      <div className="card rise">
        <div className="row"><h2 className="grow" style={{ fontSize: 22 }}>{d.title}</h2><span className={"pill " + d.state}>{label(d.state)}</span></div>
        <div className="muted">Seller {d.seller} (<code>{d.seller_id}</code>) · Buyer {d.buyer} (<code>{d.buyer_id}</code>)</div>
        <div className="big"><Money cents={d.total_cents} currency={d.currency} /> <span className="muted">{d.goods && `· ${d.quantity || ""} ${d.goods}`} · {d.funding_mode === "upfront" ? "paid up front" : "pay as you go"} · terms v{d.terms_version}</span></div>
        <PlanBar items={d.milestones.map((m) => ({ ...m, status: status(m) }))} currency={d.currency} total={d.total_cents} />
        <Summary d={d} />
        <div className="next"><span className="pulse" /><div><b>{title}</b><div className="muted">{text}</div></div></div>
        {(d.buyer_strikes > 0 || d.seller_strikes > 0) && <div className="muted">Past fault rulings: buyer {d.buyer_strikes} · seller {d.seller_strikes}</div>}

        {d.deposit.pct > 0 && d.state !== "draft" && <div className="depcard"><span className="ic"><Icon name="shield" /></span>
          <div className="grow"><b>Seller security deposit · {money(d.deposit.cents, d.currency)} ({d.deposit.pct}%)</b>
            <div className="muted">{depLabel}. {d.deposit.state === "none" ? "The buyer can fund only after it is held. It returns in full if the order goes well." : ""}{d.fault && ` Fault ruling: ${d.fault}.`}</div></div>
          {d.my_role === "seller" && d.deposit.state === "none" && <button disabled={deposit.busy} onClick={deposit.begin}>{deposit.busy && <span className="spin" />}Pay {money(d.deposit.cents, d.currency)} deposit</button>}
          {deposit.err && <div className="err" style={{ width: "100%" }}>{deposit.err}</div>}
          {deposit.sheet("Pay the security deposit", money(d.deposit.cents, d.currency))}</div>}


        <details className="dispute-rules"><summary>How disputes are settled</summary>
          <p className="muted">A reviewer decides who was at fault, and any ruling waits 48 hours so either side can appeal once to a different reviewer. Seller at fault: full refund plus 2% of the order, paid from the seller's deposit; the platform keeps 3%. Buyer at fault with goods returned: refund minus 5% (2% to the seller, 3% to the platform). Buyer keeps the goods: the seller is paid in full. Return shipping is paid by the {d.returns.shipping_by}; {d.returns.proof_required ? "proof of return is required." : "no proof of return is needed."}</p></details>

        {d.state === "draft" && <>
          <div className="row" style={{ marginTop: 12 }}><span className={"pill " + (d.seller_confirmed ? "verified" : "")}>{d.seller_confirmed ? "✓ " : ""}Seller {d.seller_confirmed ? "signed" : "not signed"}</span>
            <span className={"pill " + (d.buyer_confirmed ? "verified" : "")}>{d.buyer_confirmed ? "✓ " : ""}Buyer {d.buyer_confirmed ? "signed" : "not signed"}</span></div>
          <div className="row" style={{ marginTop: 10 }}>
            {!d[mine] && d.my_role !== "admin" && <button className="big-cta" disabled={busy} onClick={() => run(async () => { await api(`/deals/${d.id}/confirm`, "POST", { version: d.terms_version }); toast("Signed"); reload(); })}>{busy && <span className="spin" />}Sign these terms</button>}
            {d.my_role !== "admin" && <button className="ghost" onClick={() => setEdit(!edit)}>{edit ? "Cancel" : "Counter-propose (voids signatures)"}</button>}</div>
          {edit && <div style={{ marginTop: 10 }}><TermsForm initial={initial} submitLabel="Send new terms" onSubmit={async (t) => { await api(`/deals/${d.id}/terms`, "PUT", t); setEdit(false); toast("New terms sent. Signatures were voided."); reload(); }} /></div>}
        </>}
        {d.state === "terms_confirmed" && d.funding_mode === "upfront" && d.my_role === "buyer" && <div style={{ marginTop: 12 }}>
          <button className="big-cta" disabled={upfront.busy || !(d.deposit.pct === 0 || d.deposit.state === "held")} onClick={upfront.begin}>{upfront.busy && <span className="spin" />}Pay {money(d.total_cents, d.currency)} into escrow</button>
          {!(d.deposit.pct === 0 || d.deposit.state === "held") && <div className="muted" style={{ marginTop: 6 }}>Available once the seller's security deposit is held.</div>}
          {upfront.err && <div className="err">{upfront.err}</div>}
          {upfront.sheet("Pay into escrow", money(d.total_cents, d.currency))}</div>}
        {err && <div className="err">{err}</div>}
      </div>

      <div className="timeline">{d.milestones.map((m) => <Stage key={m.id} d={d} m={m} reload={reload} current={m.id === currentId} />)}</div>

      <div className="card"><div className="row"><h2 className="grow">Audit trail</h2>
        <button className="ghost" onClick={() => api(`/deals/${d.id}/audit`).then(setAudit)}>{audit ? "Refresh" : "Show"}</button></div>
        {audit && <><div className={audit.chain_ok ? "ok" : "err"} style={{ margin: "8px 0" }}>{audit.chain_ok ? "✓ Chain intact: no entry has been altered." : "Chain broken!"}</div>
          <table><tbody>{audit.events.map((e, i) => <tr key={i}><td className="muted">{new Date(e.at + "Z").toLocaleString()}</td><td>{e.actor}</td><td><b>{label(e.action)}</b></td></tr>)}</tbody></table></>}
      </div>
    </div>
  );
}
