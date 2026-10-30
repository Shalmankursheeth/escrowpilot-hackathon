import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { money } from "./api.js";

export const PROOFS = ["order_confirmation", "bill_of_lading", "commercial_invoice", "packing_list", "delivery_receipt"];
export const label = (s) => (s || "").replaceAll("_", " ");

export function useAction() {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const run = async (fn) => {
    setBusy(true); setErr("");
    try { return await fn(); } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };
  return { busy, err, run, setErr };
}

export const fileToB64 = (file) => new Promise((resolve, reject) => {
  const r = new FileReader();
  r.onload = () => resolve(String(r.result).split(",")[1]);
  r.onerror = () => reject(new Error("Could not read the file"));
  r.readAsDataURL(file);
});

export function Upload({ onFile, busy }) {
  const [name, setName] = useState("");
  return (
    <label className="drop">
      <input type="file" accept=".pdf,.png,.jpg,.jpeg,.txt" disabled={busy} onChange={async (e) => {
        const f = e.target.files[0]; if (!f) return;
        if (f.size > 5 * 1024 * 1024) { toast("Please choose a file under 5 MB", "bad"); return; }
        setName(f.name); await onFile({ filename: f.name, content_type: f.type, data_b64: await fileToB64(f) }); e.target.value = "";
      }} />
      <span>{busy ? "Reading the document…" : name ? `Uploaded ${name}` : "Drop a PDF, photo or text file, or click to choose"}</span>
    </label>
  );
}

// Numbers that count up smoothly when they change (skipped if the user prefers reduced motion).
export function Money({ cents, currency = "USD" }) {
  const [shown, setShown] = useState(cents);
  const from = useRef(cents);
  useEffect(() => {
    if (typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) { setShown(cents); return; }
    const start = performance.now(), a = from.current, b = cents;
    let raf;
    const tick = (t) => {
      const p = Math.min(1, (t - start) / 600);
      setShown(Math.round(a + (b - a) * (1 - Math.pow(1 - p, 3))));
      if (p < 1) raf = requestAnimationFrame(tick); else from.current = b;
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [cents]);
  return <span>{money(shown, currency)}</span>;
}

// ---------------------------------------------------------------- icons (stroke, 24px grid)
const PATHS = {
  shield: "M12 3l7 3v5c0 4.5-3 8-7 10-4-2-7-5.5-7-10V6l7-3zM9 12l2 2 4-4",
  lock: "M7 11V8a5 5 0 0110 0v3M6 11h12v9H6z",
  bell: "M6 16V11a6 6 0 0112 0v5l2 2H4l2-2zM10 21h4",
  home: "M4 11l8-7 8 7M6 10v10h12V10",
  doc: "M7 3h7l4 4v14H7zM14 3v4h4M10 12h5M10 16h5",
  scale: "M12 4v16M6 20h12M5 8h14M5 8l-3 7a3.5 3.5 0 006 0L5 8zM19 8l-3 7a3.5 3.5 0 006 0l-3-7z",
  bolt: "M13 3L5 14h6l-1 7 8-11h-6l1-7z",
  check: "M5 12.5l4.5 4.5L19 7.5",
  plus: "M12 5v14M5 12h14",
  back: "M15 5l-7 7 7 7",
  arrow: "M5 12h14M13 6l6 6-6 6",
  users: "M16 11a3 3 0 100-6 3 3 0 000 6zM8 12a3 3 0 100-6 3 3 0 000 6zM2 20c0-3 3-5 6-5s6 2 6 5M14 15c3 0 8 1 8 5",
  out: "M10 5H5v14h5M15 8l4 4-4 4M19 12H9",
  admin: "M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3zM9 12h6M12 9v6",
};
export function Icon({ name, size = 20 }) {
  return (<svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={PATHS[name]} /></svg>);
}

export const initials = (s) => (s || "?").split(/\s+/).filter(Boolean).slice(0, 2).map((w) => w[0].toUpperCase()).join("");
export function Avatar({ name, size = 32 }) {
  return <span className="avatar" style={{ width: size, height: size, fontSize: Math.round(size * 0.38) }}>{initials(name)}</span>;
}

// Progress ring: how far an order has come (settled stages / all stages).
export function Ring({ pct, done }) {
  const r = 19, c = 2 * Math.PI * r;
  return (
    <div className="ring"><svg width="44" height="44" viewBox="0 0 44 44"><circle className="bg" cx="22" cy="22" r={r} />
      <circle className={"fg" + (done ? " done" : "")} cx="22" cy="22" r={r} strokeDasharray={c} strokeDashoffset={c * (1 - pct / 100)} /></svg>
      <span>{done ? "✓" : `${Math.round(pct)}%`}</span></div>
  );
}

// ---------------------------------------------------------------- toasts and the success moment
export const toast = (text, kind = "ok") => window.dispatchEvent(new CustomEvent("ep-toast", { detail: { text, kind, id: Math.random() } }));
export const celebrate = (title, sub) => window.dispatchEvent(new CustomEvent("ep-celebrate", { detail: { title, sub } }));

export function Overlays() {
  const [toasts, setToasts] = useState([]);
  const [cel, setCel] = useState(null);
  useEffect(() => {
    const onToast = (e) => { setToasts((t) => [...t, e.detail]); setTimeout(() => setToasts((t) => t.filter((x) => x.id !== e.detail.id)), 3400); };
    const onCel = (e) => { setCel(e.detail); setTimeout(() => setCel(null), 1900); };
    window.addEventListener("ep-toast", onToast); window.addEventListener("ep-celebrate", onCel);
    return () => { window.removeEventListener("ep-toast", onToast); window.removeEventListener("ep-celebrate", onCel); };
  }, []);
  return (<>
    {cel && <div className="celebrate" onClick={() => setCel(null)}><div className="box">
      <div className="check"><svg viewBox="0 0 96 96"><circle cx="48" cy="48" r="44" /><path d="M28 50l14 14 27-30" /></svg></div>
      <h2 style={{ fontSize: 24 }}>{cel.title}</h2>{cel.sub && <div className="muted">{cel.sub}</div>}</div></div>}
    <div className="toasts" aria-live="polite">{toasts.map((t) => <div key={t.id} className={"toastmsg" + (t.kind === "bad" ? " bad" : "")}>{t.text}</div>)}</div>
  </>);
}

// A bottom sheet (centered on desktop) used for the PayPal approval step.
export function Sheet({ title, children, onClose }) {
  useEffect(() => { const k = (e) => e.key === "Escape" && onClose(); window.addEventListener("keydown", k); return () => window.removeEventListener("keydown", k); }, [onClose]);
  // Rendered at the top of the page: an animated parent card would otherwise become the containing block of this fixed layer.
  return createPortal(
    <div className="backdrop" onClick={onClose}><div className="sheet" role="dialog" aria-label={title} onClick={(e) => e.stopPropagation()}>
      <div className="grab" /><h2 style={{ fontSize: 20 }}>{title}</h2>{children}</div></div>,
    document.body);
}

export function Spin({ on, children }) { return <>{on && <span className="spin" />}{children}</>; }
