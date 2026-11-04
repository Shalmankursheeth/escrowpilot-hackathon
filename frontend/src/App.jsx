import { useEffect, useState } from "react";
import { api, hasToken, money, setToken } from "./api.js";
import { Avatar, Icon, Overlays, Ring, label, toast, useAction } from "./common.jsx";
import { TermsForm } from "./plan.jsx";
import Deal from "./deal.jsx";

const DONE = ["released", "refunded", "cancelled", "accepted"];
const SETTLED = ["released", "refunded", "cancelled"];

function Bell({ go }) {
  const [n, setN] = useState({ unread: 0, items: [] });
  const [open, setOpen] = useState(false);
  const load = () => api("/notifications").then(setN).catch(() => {});
  useEffect(() => { load(); const t = setInterval(load, 20000); return () => clearInterval(t); }, []);
  return (
    <div style={{ position: "relative" }}>
      <button className="iconbtn" aria-label="Notifications" onClick={() => { setOpen(!open); if (!open && n.unread) api("/notifications/read", "POST").then(load); }}>
        <Icon name="bell" />{n.unread > 0 && <span className="badge">{n.unread}</span>}</button>
      {open && <div className="pop">
        {!n.items.length && <div className="muted" style={{ padding: 10 }}>Nothing yet. Updates about your orders show up here.</div>}
        {n.items.map((i) => <div key={i.id} className={"note" + (i.read ? "" : " unread")} onClick={() => { setOpen(false); i.deal_id && go("deal", i.deal_id); }}>
          {i.text}<div className="muted">{new Date(i.at + "Z").toLocaleString()}</div></div>)}</div>}
    </div>
  );
}

function MockDeal() {
  return (
    <div className="mock" aria-hidden="true">
      <div className="muted">Granite slabs · Nordic Home Imports</div>
      <div className="amt">$50,000.00</div>
      <div className="plan" style={{ height: 38, margin: "10px 0" }}>
        <div className="seg done" style={{ width: "30%" }}><b>30%</b></div><div className="seg done" style={{ width: "40%" }}><b>40%</b></div><div className="seg funded" style={{ width: "30%" }}><b>30%</b></div></div>
      <div className="st d"><span className="n">✓</span><b>Order confirmation</b><span>verified</span></div>
      <div className="st d"><span className="n">✓</span><b>Bill of lading</b><span>verified</span></div>
      <div className="st l"><span className="n">3</span><b>Delivery receipt</b><span>locked in escrow</span></div>
    </div>
  );
}

function Features() {
  const f = [["doc", "Agree", "Find your partner by id. Propose milestones and the failure terms. Both sign the same version."],
    ["bolt", "Prove", "Upload the bill of lading or receipt. AI reads it; plain rules compare it to the contract."],
    ["scale", "Settle", "Match: paid. Mismatch: held for review. A fault ruling applies the percentages both signed."]];
  return (<>
    <div className="grid3">{f.map(([ic, t, d], i) => <div className="tile feat" key={t} style={{ animationDelay: `${i * 80}ms` }}>
      <span className="ic"><Icon name={ic} /></span><b>{t}</b><div className="muted">{d}</div></div>)}</div>
    <h2 style={{ marginTop: 28 }}>Fair rules, written down first</h2>
    <div className="rules">{[["5%", "Seller deposit, refunded when the order goes well"], ["2%", "Fee on the seller's payout, nothing for the buyer"],
      ["48h", "Cooling-off before any fault ruling moves money"], ["1", "Appeal to a different reviewer, final"]].map(([n, t], i) =>
      <div className="tile" key={n} style={{ animationDelay: `${i * 70}ms` }}><b>{n}</b><div className="muted">{t}</div></div>)}</div>
    <p className="muted">The AI only reads documents and explains facts. It never decides where money goes. Sandbox demo: test money only.</p>
  </>);
}

function Auth({ onDone }) {
  const [mode, setMode] = useState("login");
  const [f, setF] = useState({ email: "", password: "", role: "seller", company_name: "", paypal_email: "" });
  const { busy, err, run } = useAction();
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const submit = () => run(async () => {
    const body = mode === "login" ? { email: f.email, password: f.password } : { ...f };
    const r = await api(mode === "login" ? "/auth/login" : "/auth/register", "POST", body);
    setToken(r.token); onDone(r.user);
  });
  const key = (e) => { if (e.key === "Enter" && !busy) submit(); };
  return (
    <div className="landing"><span className="blob a" /><span className="blob b" />
      <div className="wrap" style={{ position: "relative", zIndex: 1 }}>
        <div className="row" style={{ justifyContent: "space-between", padding: "4px 0" }}>
          <div className="brand"><span className="logo"><Icon name="shield" size={18} /></span>EscrowPilot</div>
          <span className="chip-tag"><i />Sandbox · test money only</span></div>
        <div className="hero2">
          <div>
            <span className="chip-tag">Built for the PayPal AI Hackathon</span>
            <h1>Trust is great.<br /><em>Terms are better.</em></h1>
            <p className="lead">Thirty years of handshakes built your business. When the order is big, let the system hold the money:
              it moves only when the paperwork proves the work is done.</p>
            <div style={{ marginTop: 22, maxWidth: 380 }}><MockDeal /></div>
          </div>
          <div className="card rise" style={{ margin: 0 }} onKeyDown={key}>
            <div className="seg-ctl" role="tablist">
              <button className={mode === "login" ? "on" : ""} onClick={() => setMode("login")}>Log in</button>
              <button className={mode === "register" ? "on" : ""} onClick={() => setMode("register")}>Create account</button></div>
            <h2 style={{ marginTop: 12 }}>{mode === "login" ? "Welcome back" : "Start in a minute"}</h2>
            <label>Email</label><input value={f.email} onChange={set("email")} type="email" autoComplete="email" />
            <label>Password (8+ characters)</label><input value={f.password} onChange={set("password")} type="password" autoComplete={mode === "login" ? "current-password" : "new-password"} />
            {mode === "register" && <>
              <label>I am a</label>
              <div className="roles">{[["seller", "Seller", "Exporter shipping goods"], ["buyer", "Buyer", "Importer paying for goods"]].map(([v, t, s]) =>
                <button type="button" key={v} className={"role" + (f.role === v ? " on" : "")} onClick={() => setF({ ...f, role: v })}>{t}<span>{s}</span></button>)}</div>
              <label>Company name</label><input value={f.company_name} onChange={set("company_name")} />
              <label>PayPal sandbox email (payouts and refunds go here)</label><input value={f.paypal_email} onChange={set("paypal_email")} type="email" />
            </>}
            {err && <div className="err">{err}</div>}
            <button className="big-cta" style={{ width: "100%", marginTop: 16 }} disabled={busy} onClick={submit}>
              {busy && <span className="spin" />}{mode === "login" ? "Log in" : "Create account"}</button>
          </div>
        </div>
        <Features />
      </div>
    </div>
  );
}

function Connections({ me }) {
  const [list, setList] = useState(null);
  const [pid, setPid] = useState("");
  const [found, setFound] = useState(null);
  const { err, run, setErr } = useAction();
  const load = () => api("/connections").then(setList).catch(() => setList([]));
  useEffect(() => { load(); }, []);
  const lookup = () => run(async () => { setFound(await api("/users/lookup/" + encodeURIComponent(pid.trim()))); });
  const request = () => run(async () => { await api("/connections", "POST", { public_id: found.public_id }); setFound(null); setPid(""); load(); toast("Connection request sent"); });
  const accept = (id) => run(async () => { await api(`/connections/${id}/accept`, "POST"); load(); toast("Connected"); });
  return (
    <div className="card">
      <div className="row"><h2 className="grow">Trading partners</h2><span className="muted">Your id <code>{me.public_id}</code></span></div>
      <div className="row" style={{ marginTop: 6 }}><input className="grow" placeholder="Partner id, e.g. EP-7K2M9Q" value={pid}
        onKeyDown={(e) => e.key === "Enter" && pid.trim() && lookup()} onChange={(e) => { setPid(e.target.value); setErr(""); }} />
        <button onClick={lookup} disabled={!pid.trim()}>Find</button></div>
      {err && <div className="err">{err}</div>}
      {found && <div className="card flat rise" style={{ margin: "12px 0 0" }}><div className="row"><Avatar name={found.company_name} />
        <div className="grow"><b>{found.company_name}</b> <span className="pill">{found.role}</span>{" "}<span className={"pill " + found.trust.level}>{found.trust.level}</span>
          <div className="muted">{found.trust.completed_deals} completed deals · {found.trust.milestones_settled} stages settled
            {found.trust.clean_rate_pct !== null && ` · ${found.trust.clean_rate_pct}% clean`}{found.trust.strikes > 0 && ` · ${found.trust.strikes} past fault ruling${found.trust.strikes > 1 ? "s" : ""}`}</div></div>
        <button onClick={request}>Connect</button></div></div>}
      {list === null && <><div className="skel" /><div className="skel" style={{ width: "70%" }} /></>}
      {list && !list.length && !found && <div className="empty"><Icon name="users" size={30} /><div><b>No partners yet</b></div><div className="muted">Ask your buyer or seller for their id, or send them yours.</div></div>}
      {list && list.map((c) => (
        <div className="partner" key={c.id}><Avatar name={c.partner.company_name} />
          <div className="grow"><b>{c.partner.company_name}</b><div className="muted"><code>{c.partner.public_id}</code> · {c.partner.role}</div></div>
          <span className={"pill " + c.status}>{c.status}{c.status === "pending" ? ` (${c.direction})` : ""}</span>
          {c.status === "pending" && c.direction === "received" && <button onClick={() => accept(c.id)}>Accept</button>}
        </div>))}
    </div>
  );
}

function NewOrder({ me, go }) {
  const [pid, setPid] = useState("");
  const [title, setTitle] = useState("");
  const [conns, setConns] = useState([]);
  useEffect(() => { api("/connections").then((l) => setConns(l.filter((c) => c.status === "accepted"))).catch(() => {}); }, []);
  return (
    <div className="card"><button className="ghost small" onClick={() => go("home")}><Icon name="back" size={14} />Back</button>
      <h2 style={{ marginTop: 10 }}>New order</h2>
      <div className="grid"><div><label>Order title</label><input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. Granite slabs, Q1" /></div>
        <div><label>Partner (connected {me.role === "seller" ? "buyers" : "sellers"} only)</label>
          <select value={pid} onChange={(e) => setPid(e.target.value)}>
            <option value="">Choose…</option>
            {conns.filter((c) => c.partner.role !== me.role).map((c) => <option key={c.id} value={c.partner.public_id}>{c.partner.company_name} ({c.partner.public_id})</option>)}
          </select></div></div>
      <TermsForm submitLabel="Create order and propose terms" onSubmit={async (terms) => {
        if (!pid || title.trim().length < 2) throw new Error("Choose a partner and give the order a title");
        const d = await api("/deals", "POST", { title, counterparty_id: pid, terms });
        toast("Order created. Waiting for both signatures."); go("deal", d.id);
      }} />
    </div>
  );
}

function QueueItem({ q, review, go, reload, working }) {
  const [brief, setBrief] = useState(null);
  const [busy, setBusy] = useState(false);
  const m = q.milestone;
  const waiting = m.ruling && m.ruling_due_at && !m.appealed;
  const lock = waiting || working;
  const [scope, setScope] = useState(q.scope);
  const load = async () => { setBusy(true); try { setBrief(await api(`/admin/deals/${q.deal_id}/milestones/${m.id}/brief`)); } finally { setBusy(false); } };
  const checkReturn = async (ok) => {
    try { await api(`/admin/deals/${q.deal_id}/milestones/${m.id}/return-check`, "POST", { ok, note: ok ? "Reviewer checked the evidence: goods match" : "Reviewer checked the evidence: mismatch confirmed" }); toast("Return check recorded"); reload(); }
    catch (e) { toast(e.message || "Could not record", "bad"); }
  };
  return (
    <div className="qcard rise">
      <div className="qhead">
        <div className="grow"><div className="qtitle">{q.deal_title}</div><div className="muted">Stage {m.seq}: {m.name} · order #{q.deal_id}</div></div>
        <div className="qamt">{money(m.amount_cents)}<small>held in escrow</small></div></div>
      <div className="scopebar"><span className="muted">If a fault is ruled, settle:</span>
        <div className="seg">
          <button className={"segb" + (scope === "stage" ? " on" : "")} onClick={() => setScope("stage")}>Refund this stage</button>
          <button className={"segb" + (scope === "whole_order" ? " on" : "")} onClick={() => setScope("whole_order")}>Full return, whole order</button></div>
        {scope !== q.scope && <span className="muted">Differs from the signed terms; the change is logged.</span>}</div>
      <div className="qfacts">
        {m.verdict?.reasons.map((r, i) => <div key={i} className={"fact " + (/^All checks passed/.test(r) ? "good" : "alert")}><i />{r}</div>)}
        {m.return_proof_ok && <div className="fact good"><i />Return proof on file{m.return_received === "confirmed" ? ", seller confirmed the returned goods" : m.return_received === null ? ", seller still checking the returned goods" : ""}</div>}
        {m.return_proof_ok && m.return_received === "mismatch" && <div className="fact alert"><i /><span><b>Seller reports a mismatch:</b> {m.return_received_note}
          <span className="row" style={{ marginTop: 6 }}>
            <button className="ghost small" onClick={() => checkReturn(true)}>Reviewed: goods match</button>
            <button className="ghost small" onClick={() => checkReturn(false)}>Reviewed: mismatch stands</button></span></span></div>}
        <div className="fact"><i /><span><b>Signed scope: {q.scope === "stage" ? "this stage only" : "whole order"}.</b>{" "}
          {scope === "stage" ? "A ruling settles only this stage; the other stages carry on."
            : q.other_locked_cents > 0 ? `A ruling also ends the order: ${money(q.other_locked_cents)} still locked in other stages is settled with it. Seller at fault: all of it goes back to the buyer. Buyer at fault: delivered stages are paid to the seller, undelivered funded stages go back to the buyer.`
            : "A ruling ends the order. No other stage has money locked."}</span></div>
        {waiting && <div className="fact wait"><i /><span><b>Ruling: {m.ruling} at fault.</b> Takes effect {new Date(m.ruling_due_at + "Z").toLocaleString()} unless appealed.</span></div>}
        {m.appealed && <div className="fact wait"><i /><span><b>Appealed:</b> {m.appeal_reason}. A different reviewer must decide; that is final.</span></div>}
      </div>
      {brief && <div className="qbrief"><b>Evidence summary</b> <span className="muted">({brief.provider}, facts only, no recommendation)</span>
        <div style={{ marginTop: 6 }}>{brief.summary}</div></div>}
      <div className="qacts">
        <button className="ghost" disabled={busy} onClick={load}>{busy && <span className="spin" />}{brief ? "Refresh summary" : "AI evidence summary"}</button>
        <button className="ghost" onClick={() => go("deal", q.deal_id)}>Open deal</button>
        <span className="grow" />
        <button disabled={lock} onClick={() => review(q, "approve")}>{working && <span className="spin" />}Approve payout</button>
        <button className="bad" disabled={lock} onClick={() => review(q, "seller_fault", scope)}>Seller at fault</button>
        <button className="bad" disabled={lock} onClick={() => review(q, "buyer_fault", scope)}>Buyer at fault</button></div></div>
  );
}

const EVENT_TONE = { capture: "in", deposit_capture: "in", payout: "out", refund: "back", deposit_return: "back" };
const SIGN = { in: "+", out: "−", back: "−" };

function Ledger() {
  const [data, setData] = useState(null);
  const [showAll, setShowAll] = useState(false);
  const load = () => api("/admin/ledger").then(setData).catch(() => setData({ events: [], fees: [] }));
  useEffect(() => { load(); }, []);
  if (!data) return <div className="card"><div className="skel" /><div className="skel" style={{ width: "70%" }} /></div>;
  const moves = (data.events || []).filter((e) => !["order", "deposit_order"].includes(e.kind));
  const shown = showAll ? moves : moves.slice(0, 8);
  return (
    <>
      <div className="tiles">
        <div className="tile accent"><small>Platform earned</small><b>{money(data.platform_cents || 0)}</b><small>{money(data.stage_fees_cents || 0)} stage fees · {money(data.deposit_kept_cents || 0)} from deposits</small></div>
        <div className="tile"><small>Money in</small><b>{money(data.collected_cents || 0)}</b><small>buyer stages and seller deposits</small></div>
        <div className="tile"><small>Held in escrow now</small><b>{money(data.held_cents || 0)}</b><small>not yet paid or refunded</small></div>
        <div className="tile"><small>Paid to sellers</small><b>{money(data.paid_out_cents || 0)}</b><small>incl. deposits returned</small></div>
        <div className="tile"><small>Refunded to buyers</small><b>{money(data.refunded_cents || 0)}</b><small>after rulings and returns</small></div></div>
      <div className="card"><div className="row"><h2 className="grow">Platform fees earned</h2></div>
        {!(data.fees || []).length && <div className="muted">No fees yet. A fee is taken when a stage is paid out or a buyer-at-fault refund settles.</div>}
        {(data.fees || []).map((f, i) => <div className="mrow" key={i}><div className="grow"><b>{f.deal}</b><div className="muted">{f.stage} · {f.state}</div></div><b className="in">+{money(f.fee_cents)}</b></div>)}</div>
      <div className="card"><div className="row"><h2 className="grow">Money log</h2><span className="muted">{moves.length} movements</span></div>
        {!moves.length && <div className="muted">Nothing has moved yet.</div>}
        {shown.map((e) => { const t = EVENT_TONE[e.kind] || "out"; return (
          <div className="mrow" key={e.id}><span className={"dot " + t} /><div className="grow"><b>{e.label}</b>
            <div className="muted">{e.deal}{e.stage ? ` · ${e.stage}` : ""} · {new Date(e.at + "Z").toLocaleString()}</div></div>
            <div style={{ textAlign: "right" }}><b className={t}>{SIGN[t]}{money(e.amount_cents)}</b><div><span className="pill">{String(e.status || "").toLowerCase()}</span></div></div></div>); })}
        {moves.length > 8 && <button className="ghost small" style={{ marginTop: 8 }} onClick={() => setShowAll(!showAll)}>{showAll ? "Show fewer" : `Show all ${moves.length}`}</button>}</div>
    </>
  );
}

function Admin({ go }) {
  const [users, setUsers] = useState([]);
  const [queue, setQueue] = useState(null);
  const [tab, setTab] = useState("review");
  const [msg, setMsg] = useState("");
  const [working, setWorking] = useState(false);
  const { err, run } = useAction();
  const load = () => { api("/admin/users").then(setUsers); api("/admin/queue").then(setQueue); };
  useEffect(() => { load(); }, []);
  // One decision at a time: while a ruling is being sent every action button is locked, so a double tap cannot fire twice.
  const review = (q, decision, scope) => {
    if (working) return;
    setWorking(true);
    return run(async () => {
      await api(`/admin/deals/${q.deal_id}/milestones/${q.milestone.id}/review`, "POST", { decision, scope, note: decision === "approve" ? "Reviewed and approved" : "" }); load();
      toast(decision === "approve" ? "Payout approved" : "Ruling recorded");
    }).finally(() => setWorking(false));
  };
  const waiting = queue ? queue.length : 0;
  const tabs = [["review", "Review", waiting], ["money", "Money", 0], ["users", "Users", 0], ["tools", "Tools", 0]];
  return (
    <div className="page">
      <div className="greet">Admin console</div>
      <div className="muted">Reviewers name who was at fault. The AI only summarizes facts, and code applies the numbers.</div>
      <div className="tabs">{tabs.map(([k, name, n]) => <button key={k} className={"tab" + (tab === k ? " on" : "")} onClick={() => setTab(k)}>{name}{n > 0 && <span className="badge">{n}</span>}</button>)}</div>
      {tab === "review" && <div className="card"><div className="row"><h2 className="grow">Review queue</h2><span className="muted">{waiting} waiting</span></div>
        {queue === null && <div className="skel" />}
        {queue && !queue.length && <div className="empty"><Icon name="check" size={30} /><div><b>All clear</b></div><div className="muted">Nothing is waiting for review.</div></div>}
        {queue && queue.map((q) => <QueueItem key={q.milestone.id} q={q} review={review} go={go} reload={load} working={working} />)}
        {err && <div className="err">{err}</div>}</div>}
      {tab === "money" && <Ledger />}
      {tab === "users" && <div className="card"><h2>Users (simulated KYC)</h2>
        {users.map((u) => <div className="partner" key={u.id}><Avatar name={u.company_name} />
          <div className="grow"><b>{u.company_name}</b><div className="muted">{u.email} · <code>{u.public_id}</code> · {u.role}</div></div>
          {u.verified ? <span className="pill verified">verified</span> : <button onClick={() => run(async () => { await api(`/admin/users/${u.id}/verify`, "POST"); load(); toast("User verified"); })}>Verify</button>}</div>)}</div>}
      {tab === "tools" && <div className="card"><h2>Timers</h2><p className="muted">Releases stages whose inspection window ended, and applies rulings whose cooling-off ended. Runs on the server every minute.</p>
        <div className="row"><button onClick={() => run(async () => { const r = await api("/admin/run-timers", "POST"); setMsg(`${r.released} action(s) applied`); })}>Run now</button><span className="muted">{msg}</span></div></div>}
    </div>
  );
}

function Home({ me, go }) {
  const [deals, setDeals] = useState(null);
  useEffect(() => { api("/deals").then(setDeals).catch(() => setDeals([])); }, []);
  const ms = (deals || []).flatMap((d) => d.milestones);
  const locked = ms.filter((m) => m.funded && !SETTLED.includes(m.state)).reduce((a, m) => a + m.amount_cents, 0);
  const active = (deals || []).filter((d) => !["completed", "cancelled"].includes(d.state)).length;
  const pct = (d) => (d.milestones.length ? 100 * d.milestones.filter((m) => DONE.includes(m.state)).length / d.milestones.length : 0);
  return (
    <div className="page">
      <div className="greet">Hi, {me.company_name}</div>
      <div className="muted">{me.role === "seller" ? "Ship the goods, upload the paperwork, get paid." : "Fund each stage, inspect, and release with confidence."}</div>
      {!me.verified && <div className="card flat"><b>Waiting for verification.</b> <span className="muted">An admin must verify your account (simulated KYC) before you can connect or trade.</span></div>}
      <div className="tiles">
        <div className="tile accent"><small>Locked in escrow</small><b>{money(locked)}</b></div>
        <div className="tile"><small>Active orders</small><b>{active}</b></div>
        <div className="tile"><small>All orders</small><b>{deals ? deals.length : "–"}</b></div></div>
      <div className="card"><div className="row"><h2 className="grow">Orders</h2><button onClick={() => go("new")}><Icon name="plus" size={16} />New order</button></div>
        {deals === null && <><div className="skel" /><div className="skel" style={{ width: "80%" }} /></>}
        {deals && !deals.length && <div className="empty"><Icon name="doc" size={30} /><div><b>No orders yet</b></div><div className="muted">Connect with a trading partner below, then create your first order with its payment terms.</div></div>}
        {deals && deals.map((d) => <div key={d.id} className="order" onClick={() => go("deal", d.id)}>
          <Ring pct={pct(d)} done={d.state === "completed"} />
          <div className="t"><b>{d.title}</b><div className="muted">{d.my_role === "buyer" ? `Seller ${d.seller}` : `Buyer ${d.buyer}`}</div></div>
          <div style={{ textAlign: "right" }}><b>{money(d.total_cents, d.currency)}</b><div><span className={"pill " + d.state}>{label(d.state)}</span></div></div></div>)}</div>
      <Connections me={me} />
    </div>
  );
}

// PayPal lands the payer here after approval. Capture the payment saved by the sheet, tell the other tab, then open the order.
function PayReturn({ onDone }) {
  const [msg, setMsg] = useState("Finishing your payment…");
  const [bad, setBad] = useState(false);
  useEffect(() => {
    let pending = null;
    try { pending = JSON.parse(localStorage.getItem("ep_pending") || "null"); } catch { /* none */ }
    const token = new URLSearchParams(window.location.search).get("token");
    if (!pending || pending.token !== token) { onDone(pending && pending.dealId); return; }
    api(pending.path, "POST").then(() => {
      localStorage.removeItem("ep_pending");
      localStorage.setItem("ep_done", String(Date.now()));
      setMsg("Payment confirmed. Opening your order…");
      setTimeout(() => onDone(pending.dealId), 900);
    }).catch((e) => { setBad(true); setMsg(String((e && e.message) || e)); });
  }, []);
  return <div className="page"><div className="card" style={{ textAlign: "center" }}>
    <h2>{bad ? "We could not confirm the payment" : "One moment"}</h2>
    <p className="muted">{msg}</p>
    {bad && <button onClick={() => onDone(null)}>Back to EscrowPilot</button>}</div></div>;
}

export default function App() {
  const [me, setMe] = useState(null);
  const [returning, setReturning] = useState(window.location.pathname === "/paypal/return");
  const [ready, setReady] = useState(!hasToken());
  const hashDeal = /^#deal-(\d+)$/.exec(window.location.hash);
  const [view, setView] = useState(hashDeal ? { name: "deal", id: Number(hashDeal[1]) } : { name: "home" });
  useEffect(() => { if (hasToken()) api("/me").then(setMe).catch(() => setToken(null)).finally(() => setReady(true)); }, []);
  if (!ready) return null;
  if (!me) return <><Auth onDone={setMe} /><Overlays /></>;
  const go = (name, id) => { setView({ name, id }); window.scrollTo({ top: 0, behavior: "smooth" }); };
  const leaveReturn = (dealId) => {
    window.history.replaceState(null, "", dealId ? `/#deal-${dealId}` : "/");
    setReturning(false);
    setView(dealId ? { name: "deal", id: Number(dealId) } : { name: "home" });
  };
  if (returning) return <><PayReturn onDone={leaveReturn} /><Overlays /></>;
  return (
    <div>
      <header><div className="brand" onClick={() => go("home")}><span className="logo"><Icon name="shield" size={18} /></span>EscrowPilot</div>
        <div className="hdr-right">
          <div className="who"><Avatar name={me.company_name} size={26} /><span className="nm">{me.company_name}<small>{me.role} · {me.public_id}</small></span></div>
          <button className="iconbtn" aria-label="Home" title="Home" onClick={() => go("home")}><Icon name="home" /></button>
          {me.role === "admin" && <button className="iconbtn" aria-label="Admin" title="Admin" onClick={() => go("admin")}><Icon name="admin" /></button>}
          <Bell go={go} />
          <button className="iconbtn" aria-label="Log out" title="Log out" onClick={() => { setToken(null); setMe(null); }}><Icon name="out" /></button></div></header>
      <div className="wrap" key={view.name + (view.id || "")}>
        {view.name === "home" && (me.role === "admin" ? <Admin go={go} /> : <Home me={me} go={go} />)}
        {view.name === "admin" && <Admin go={go} />}
        {view.name === "new" && <div className="page"><NewOrder me={me} go={go} /></div>}
        {view.name === "deal" && <div className="page"><Deal id={view.id} me={me} go={go} /></div>}
      </div>
      <Overlays />
    </div>
  );
}
