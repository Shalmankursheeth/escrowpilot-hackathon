import { useState } from "react";
import { PROOFS, label, useAction } from "./common.jsx";
import { money } from "./api.js";

const COLORS = ["var(--c1)", "var(--c2)", "var(--c3)", "var(--c4)", "var(--c5)", "var(--c6)"];

export const PRESETS = [
  { name: "Standard 30 / 40 / 30", ms: [["Order confirmation", 30, "order_confirmation"], ["Shipment", 40, "bill_of_lading"], ["Delivery", 30, "delivery_receipt"]] },
  { name: "Simple 50 / 50", ms: [["Order confirmation", 50, "order_confirmation"], ["Delivery", 50, "delivery_receipt"]] },
  { name: "4 stages 20 / 30 / 30 / 20", ms: [["Order confirmation", 20, "order_confirmation"], ["Packing", 30, "packing_list"], ["Shipment", 30, "bill_of_lading"], ["Delivery", 20, "delivery_receipt"]] },
  { name: "All on delivery", ms: [["Delivery", 100, "delivery_receipt"]] },
];
const fromPreset = (p) => p.ms.map(([name, share_pct, required_proof]) => ({ name, share_pct, required_proof }));

export const blankTerms = () => ({
  total_amount: "50000", currency: "USD", goods: "granite countertop slabs", quantity: 1000, inspection_days: 3,
  milestones: fromPreset(PRESETS[0]), funding_mode: "per_milestone", release_rule: "on_completion", failure_scope: "whole_order", funding_deadline_days: 7, default_penalty_pct: 10, seller_deposit_pct: 5,
  return_refund_pct: 100, return_shipping_by: "seller", return_proof_required: true, return_check_days: 5,
});
// A bar split into stages. In the builder it shows the plan; on an order it also shows each stage's progress.
export function PlanBar({ items, currency, total }) {
  return (
    <div className="plan">
      {items.map((m, i) => (
        <div key={i} className={"seg " + (m.status || "")} style={{ width: `${Math.max(Number(m.share_pct) || 0, 0)}%`, background: m.status ? undefined : COLORS[i % COLORS.length] }}
          title={`${m.name}: ${m.share_pct}%`}>
          <b>{m.share_pct}%</b>
          <small>{money(Math.round(total * (Number(m.share_pct) || 0) / 100), currency)}</small>
        </div>))}
    </div>
  );
}

const cents = (v) => Math.round((parseFloat(String(v).replace(/,/g, "")) || 0) * 100);

function sentences(t) {
  const total = cents(t.total_amount), cur = t.currency || "USD";
  const out = t.milestones.map((m, i) => {
    const amt = money(Math.round(total * (Number(m.share_pct) || 0) / 100), cur);
    const when = t.funding_mode === "upfront" ? "is already in escrow" : i === 0 ? "pays it into escrow when the order is signed" : "pays it into escrow once the previous stage is settled";
    return `Stage ${i + 1} · ${m.name || "Untitled"}: the buyer ${when} (${amt}). ${t.release_rule === "per_stage" ? "It goes to the seller when" : "It is verified and kept locked when"} a matching ${label(m.required_proof)} is uploaded.`;
  });
  if (t.release_rule !== "per_stage") out.push("Nothing is paid to the seller until every stage is verified and the buyer accepts the delivery. Then all stages are paid together.");
  if (t.milestones.some((m) => m.required_proof === "delivery_receipt") && t.inspection_days > 0)
    out.push(`After delivery the buyer has ${t.inspection_days} day${t.inspection_days > 1 ? "s" : ""} to inspect. No complaint means the money is released automatically.`);
  const dep = Number(t.seller_deposit_pct) || 0;
  if (dep > 0) out.push(`The seller pays a ${dep}% security deposit (${money(Math.round(total * dep / 100), cur)}) before the buyer funds. It comes back in full if the order goes well.`);
  out.push(`The 2% platform fee is taken from the seller's payout. If there is a dispute, a reviewer decides who was at fault.${t.return_proof_required ? " Goods go back with a return receipt." : ""} Return shipping is paid by the ${t.return_shipping_by}.`);
  if (t.return_proof_required && Number(t.return_check_days) > 0)
    out.push(`No refund is paid until the seller has the returned goods back and checks them against what was shipped. The seller has ${Number(t.return_check_days)} days to confirm them or report a mismatch. No answer counts as confirmed. A reported mismatch goes to a reviewer, and the refund waits.`);
  out.push(dep > 0
    ? "Seller at fault: the buyer gets the full refund plus 2% of the order, taken from the seller's deposit. The platform keeps the other 3%."
    : "Seller at fault: the buyer gets the full refund.");
  out.push("A fault ruling waits 48 hours before any money moves. Either side can appeal once, and a different reviewer then decides for good.");
  out.push("Buyer at fault with goods sent back: the buyer is refunded minus 5% of the order. The seller gets 2% of that, the platform 3%, and the seller's deposit returns. If the buyer keeps the goods, the seller is paid in full.");
  out.push(`${t.failure_scope === "stage" ? "A failure only affects the failed stage." : "A failure undoes the whole order: every stage still locked is refunded on the same terms."}`);
  out.push(`The buyer has ${t.funding_deadline_days || 7} days to fund each stage. If they miss it, the order closes, unstarted stages are cancelled, and the seller keeps ${t.default_penalty_pct}% of the money locked at that point.`);
  return out;
}

export function TermsForm({ initial, onSubmit, submitLabel, extra }) {
  const [t, setT] = useState(initial || blankTerms());
  const { busy, err, run } = useAction();
  const set = (k, v) => setT({ ...t, [k]: v });
  const setM = (i, k, v) => set("milestones", t.milestones.map((m, j) => (j === i ? { ...m, [k]: v } : m)));
  const sum = t.milestones.reduce((a, m) => a + Number(m.share_pct || 0), 0);
  const left = 100 - sum;
  const total = cents(t.total_amount);
  const submit = () => run(async () => onSubmit({
    ...t, total_amount: String(t.total_amount).replace(/,/g, ""), quantity: t.quantity ? Number(t.quantity) : null, goods: t.goods || null,
    seller_deposit_pct: Number(t.seller_deposit_pct) || 0, inspection_days: Number(t.inspection_days), return_check_days: Number(t.return_check_days) || 0, funding_deadline_days: Number(t.funding_deadline_days) || 7, return_refund_pct: Number(t.return_refund_pct),
    milestones: t.milestones.map((m) => ({ ...m, share_pct: Number(m.share_pct) })),
  }));
  return (
    <div className="builder">
      {extra}
      <div className="bstep"><span className="n">1</span><h3>The deal</h3></div>
      <div className="grid">
        <div><label>Total price</label><input inputMode="decimal" value={t.total_amount} onChange={(e) => set("total_amount", e.target.value)} /></div>
        <div><label>Currency</label><input value={t.currency} maxLength={3} onChange={(e) => set("currency", e.target.value.toUpperCase())} /></div>
        <div><label>Goods</label><input value={t.goods || ""} onChange={(e) => set("goods", e.target.value)} /></div>
        <div><label>Quantity (units)</label><input inputMode="numeric" value={t.quantity || ""} onChange={(e) => set("quantity", e.target.value)} /></div>
      </div>

      <div className="bstep"><span className="n">2</span><h3>How it is paid</h3></div>
      <div className="choice">
        {[["per_milestone", "Pay as you go", "Recommended. The buyer pays each stage into escrow just before it starts. Less cash tied up, and the seller still sees the money locked before working."],
          ["upfront", "All up front", "The buyer funds the full price first. Safest for the seller, heavy for the buyer."]].map(([v, title, text]) => (
          <button type="button" key={v} className={"opt" + (t.funding_mode === v ? " on" : "")} onClick={() => set("funding_mode", v)}>
            <b>{title}</b><span>{text}</span></button>))}
      </div>
      <div className="bstep"><span className="n">2b</span><h3>When the seller gets paid</h3></div>
      <div className="choice">
        {[["on_completion", "Hold until the order is accepted", "Recommended. Every stage is checked, but all the money stays locked until the final delivery is accepted. A failed delivery can still be settled from locked funds."],
          ["per_stage", "Pay each stage when proven", "The seller is paid as each stage passes. Faster for the seller; earlier stages cannot be clawed back."]].map(([v, title, text]) => (
          <button type="button" key={v} className={"opt" + (t.release_rule === v ? " on" : "")} onClick={() => set("release_rule", v)}>
            <b>{title}</b><span>{text}</span></button>))}
      </div>
      <div className="chips">{PRESETS.map((p) => <button type="button" key={p.name} className="chip" onClick={() => set("milestones", fromPreset(p))}>{p.name}</button>)}</div>
      <PlanBar items={t.milestones} currency={t.currency} total={total} />
      <div className={"balance " + (left === 0 ? "ok" : "bad")}>
        {left === 0 ? "✓ The stages add up to 100%." : left > 0 ? `${left}% still unassigned.` : `${-left}% over. Reduce a stage.`}
        {left !== 0 && <button type="button" className="ghost small" onClick={() => setM(t.milestones.length - 1, "share_pct", Math.max(1, Number(t.milestones[t.milestones.length - 1].share_pct) + left))}>Fix the last stage</button>}
      </div>
      {t.milestones.map((m, i) => (
        <div className="mrow" key={i}>
          <span className="dotn" style={{ background: COLORS[i % COLORS.length] }}>{i + 1}</span>
          <input className="grow" aria-label="Stage name" value={m.name} onChange={(e) => setM(i, "name", e.target.value)} />
          <input type="range" min="5" max="100" step="5" value={m.share_pct} aria-label="Share" onChange={(e) => setM(i, "share_pct", Number(e.target.value))} />
          <input className="pct" inputMode="numeric" value={m.share_pct} onChange={(e) => setM(i, "share_pct", e.target.value)} />
          <select value={m.required_proof} onChange={(e) => setM(i, "required_proof", e.target.value)}>{PROOFS.map((p) => <option key={p} value={p}>{label(p)}</option>)}</select>
          {t.milestones.length > 1 && <button type="button" className="ghost small" aria-label="Remove stage" onClick={() => set("milestones", t.milestones.filter((_, j) => j !== i))}>✕</button>}
        </div>))}
      <button type="button" className="ghost" onClick={() => set("milestones", [...t.milestones, { name: "", share_pct: Math.max(left, 5), required_proof: "packing_list" }])}>+ Add a stage</button>

      <div className="bstep"><span className="n">3</span><h3>Inspection and failure</h3></div>
      <div className="grid">
        <div><label>Inspection window after delivery (days)</label><input inputMode="numeric" value={t.inspection_days} onChange={(e) => set("inspection_days", e.target.value)} /></div>
        <div><label>If delivery fails, refund to buyer: <b>{t.return_refund_pct}%</b></label>
          <input type="range" min="0" max="100" step="5" value={t.return_refund_pct} onChange={(e) => set("return_refund_pct", Number(e.target.value))} /></div>
        <div><label>If delivery fails, what is undone</label>
          <select value={t.failure_scope} onChange={(e) => set("failure_scope", e.target.value)}><option value="whole_order">The whole order (all locked money)</option><option value="stage">Only the failed stage</option></select></div>
        <div><label>Buyer must fund each stage within (days)</label><input inputMode="numeric" value={t.funding_deadline_days} onChange={(e) => set("funding_deadline_days", e.target.value)} /></div>
        <div><label>If the buyer misses it, seller keeps: <b>{t.default_penalty_pct}%</b> of locked money</label>
          <input type="range" min="0" max="100" step="5" value={t.default_penalty_pct} onChange={(e) => set("default_penalty_pct", Number(e.target.value))} /></div>
        <div><label>Return shipping paid by</label>
          <select value={t.return_shipping_by} onChange={(e) => set("return_shipping_by", e.target.value)}><option value="seller">Seller</option><option value="buyer">Buyer</option></select></div>
        <div><label>Buyer must prove the goods went back</label>
          <select value={String(t.return_proof_required)} onChange={(e) => set("return_proof_required", e.target.value === "true")}><option value="true">Yes</option><option value="false">No</option></select></div>
        <div><label>Seller checks returned goods within (days, 0 = no check)</label><input inputMode="numeric" value={t.return_check_days} onChange={(e) => set("return_check_days", e.target.value)} /></div>
      </div>

      <div className="bstep"><span className="n">4</span><h3>What you are both agreeing to</h3></div>
      <div className="explain">{sentences(t).map((x, i) => <p key={x} style={{ animationDelay: `${i * 60}ms` }}>{x}</p>)}</div>
      {err && <div className="err">{err}</div>}
      <button style={{ marginTop: 14 }} disabled={busy || left !== 0 || total <= 0} onClick={submit}>{submitLabel}</button>
    </div>
  );
}
