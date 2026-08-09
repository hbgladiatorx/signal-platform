"""Render the signed, shareable Referee Report.

Two artifacts from one verdict:
  * a signed JSON record (machine-verifiable), and
  * a one-page HTML note that reads like a research memo, not a marketing badge.

Signature design (Ed25519 asymmetric — see referee.signing):
  * content_hash = sha256(canonical_json). DETERMINISTIC: the same verdict content
    regenerates the identical hash, so a verifier can confirm what was signed.
  * verification_id = RFE-... derived from content_hash; key_id identifies the
    signing key (rotation-safe).
  * signature = Ed25519( content_hash | verification_id | key_id ) under a PRIVATE
    key only the server holds. Anyone verifies with the PUBLISHED public key; no
    one can forge without the private key. There is no secret printed on the
    report — removing the old seed that made forgery possible.

If no production key is configured, signing REFUSES (referee.signing.SigningError)
unless REFEREE_ALLOW_INSECURE=1, in which case a dev key signs and the cert is
stamped insecure:true with a loud banner. Production never sets that flag.

PDF is intentionally deferred: the HTML is print-to-PDF ready (A4 @page CSS); a
weasyprint hook renders PDF when the lib is installed in the image.
"""
from __future__ import annotations

import hashlib
import html
import json

from referee import signing

SIGNATURE_NOTE = (
    "Authenticity is guaranteed by an Ed25519 digital signature over this cert's "
    "content (content_hash | verification_id | key_id), produced with a private key "
    "only Bayn holds. Verify with the published public key — see the verify line "
    "above — using `python -m referee verify <report.json>`. Editing any field "
    "invalidates the signature, and no party without the private key can produce a "
    "valid one. An insecure:true marker means a dev key signed it: do not trust it."
)

_BADGE = {
    "DEPLOY": ("#0a7d28", "PASS"),
    "HOLD_CONDITIONAL": ("#b9770e", "CONDITIONAL"),
    "REJECT": ("#b3261e", "REJECT"),
    "UNVERIFIABLE": ("#5f6368", "UNVERIFIABLE"),
}


_SIG_KEYS = ("content_hash", "signature", "verification_id", "_artifacts")


def _canonical_body(rec: dict) -> bytes:
    """Deterministic serialization of the verdict CONTENT (signed fields only):
    sorted keys, compact separators, excluding the signature envelope itself."""
    body = {k: v for k, v in rec.items() if k not in _SIG_KEYS}
    return json.dumps(body, sort_keys=True, default=float, separators=(",", ":")).encode()


def _content_hash(body_bytes: bytes) -> str:
    return hashlib.sha256(body_bytes).hexdigest()


def _verification_id(content_hash: str) -> str:
    h = content_hash.upper()
    return f"RFE-{h[:4]}-{h[4:8]}-{h[8:12]}"


def _signing_message(content_hash: str, verification_id: str, key_id: str) -> bytes:
    # the signature binds content + id + key together; swapping any one invalidates it
    return f"{content_hash}|{verification_id}|{key_id}".encode()


def sign(verdict: dict) -> dict:
    """Attach content_hash + verification_id + Ed25519 signature. Returns a new dict.

    Raises referee.signing.SigningError under the production guard (no key set and
    REFEREE_ALLOW_INSECURE != 1) — a cert is NOT produced without a signing key."""
    body_bytes = _canonical_body(verdict)
    content_hash = _content_hash(body_bytes)
    verification_id = _verification_id(content_hash)

    priv, insecure = signing.get_signer()            # may raise SigningError
    kid = signing.key_id(priv.public_key())
    sig_hex = signing.sign(_signing_message(content_hash, verification_id, kid), priv)

    pub_location = (f"referee/keys/{kid}.pub (also served at {signing.PUBKEY_ENDPOINT})")
    body = {k: v for k, v in verdict.items() if k not in _SIG_KEYS}
    return {**body,
            "content_hash": content_hash,
            "verification_id": verification_id,
            "signature": {"alg": "ed25519", "key_id": kid, "value": sig_hex,
                          "insecure": insecure, "public_key": pub_location,
                          "verify": "python -m referee verify <report.json>",
                          "note": SIGNATURE_NOTE}}


def verify(signed: dict) -> dict:
    """Forgery-resistant verification with the PUBLISHED public key only.

    content_ok : the body re-hashes to the stored content_hash (nothing edited).
    signature_ok : the Ed25519 signature over the RECOMPUTED content binds — only a
                   holder of the private key could have produced it. Editing any
                   field changes the recomputed hash and breaks this independently.
    """
    body_bytes = _canonical_body(signed)
    recomputed = _content_hash(body_bytes)
    content_ok = (recomputed == signed.get("content_hash"))

    sigblk = signed.get("signature", {})
    kid = sigblk.get("key_id")
    vid = signed.get("verification_id")
    pub = signing.public_key_for_verify(kid, bool(sigblk.get("insecure")))
    msg = _signing_message(recomputed, vid, kid)
    sig_ok = bool(pub is not None and signing.verify(msg, sigblk.get("value", ""), pub))
    return {"content_ok": content_ok, "signature_ok": sig_ok,
            "insecure": bool(sigblk.get("insecure")), "key_id": kid,
            "verification_id": vid}


# --------------------------------------------------------------- HTML render
def _row(label, value):
    return f'<tr><td class="k">{html.escape(str(label))}</td><td class="v">{value}</td></tr>'


def _fmt(x, nd=3):
    return "—" if x is None else (f"{x:.{nd}f}" if isinstance(x, (int, float)) else html.escape(str(x)))


def render_html(signed: dict) -> str:
    v = signed["verdict"]
    color, badge = _BADGE.get(v, ("#5f6368", v))
    m = signed.get("metrics", {})
    tr = signed.get("trials", {})
    cost = signed.get("cost_model", {})
    integ = signed.get("integrity", {})
    pbo = signed.get("pbo_cscv")
    noise = signed.get("noise_battery", {})
    sig = signed.get("signature", {})

    # headline metrics (— when not graded)
    dsr = _fmt(m.get("dsr"))
    dsr_bar = _fmt(m.get("dsr_bar"), 2)
    netsh = _fmt(m.get("net_sharpe_annualized"), 2)
    trl = m.get("min_trl"); T = m.get("T")
    trl_disp = "—" if not m else (f"{trl:.0f} / {T}" if trl is not None else f"∞ / {T}")
    pbo_disp = "n/a (single config)" if pbo is None else f"{pbo['pbo']:.2f} (bar &lt; {pbo['bar']})"

    declared = tr.get("declared_trials")
    floor = tr.get("provable_floor")
    n_used = tr.get("n_trials_used")
    under = tr.get("declared_below_floor")
    trial_line = (f'<b>{declared}</b> <span class="sd">self-declared</span>'
                  + (f' · floor {floor}' if floor and floor > 1 else "")
                  + (f' · <b>deflated at {n_used}</b>' if n_used != declared else ""))
    under_flag = ('<div class="warn">⚠ Declared trial count is below the provable floor '
                  f'({declared} &lt; {floor}); deflation uses {n_used}.</div>' if under else "")

    # integrity block
    ist = integ.get("status", "—")
    icolor = {"CLEAN": "#0a7d28", "FLAG": "#b9770e", "UNVERIFIABLE": "#b3261e"}.get(ist, "#5f6368")
    ireasons = "".join(f"<li>{html.escape(x)}</li>" for x in integ.get("reasons", []))
    iflags = "".join(f"<li>{html.escape(x)}</li>" for x in integ.get("flags", []))
    integ_lists = ""
    if ireasons:
        integ_lists += f'<div class="sub">Disqualifying</div><ul class="bad">{ireasons}</ul>'
    if iflags:
        integ_lists += f'<div class="sub">Noted</div><ul class="flag">{iflags}</ul>'
    if not integ_lists:
        integ_lists = '<div class="ok">No integrity issues found.</div>'

    regime = m.get("regime", {})
    regime_disp = " · ".join(f"{y}: {val:+.3f}" for y, val in sorted(regime.items())) or "—"

    insecure = bool(sig.get("insecure"))
    banner = ('<div class="banner">⚠ INSECURE — signed with a development key. '
              'This is NOT a valid Bayn certificate and must not be trusted.</div>'
              if insecure else "")
    insec = ' <b class="insec">[insecure dev key]</b>' if insecure else ""

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<title>Referee Report {html.escape(signed.get('verification_id',''))}</title>
<style>
  @page {{ size: A4; margin: 18mm 16mm; }}
  * {{ box-sizing: border-box; }}
  body {{ font: 13px/1.5 -apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
          color:#1a1a1a; max-width: 760px; margin: 0 auto; padding: 24px; }}
  .hd {{ display:flex; justify-content:space-between; align-items:flex-start;
         border-bottom:2px solid #111; padding-bottom:12px; }}
  .hd h1 {{ font-size:20px; margin:0 0 2px; letter-spacing:-.2px; }}
  .hd .sub {{ color:#666; font-size:12px; }}
  .badge {{ color:#fff; background:{color}; font-weight:700; font-size:15px;
            padding:8px 16px; border-radius:6px; white-space:nowrap; }}
  .vid {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:12px;
          color:#444; margin-top:6px; }}
  h2 {{ font-size:13px; text-transform:uppercase; letter-spacing:.6px; color:#333;
        margin:22px 0 8px; border-bottom:1px solid #ddd; padding-bottom:4px; }}
  table {{ border-collapse:collapse; width:100%; }}
  td {{ padding:5px 8px; vertical-align:top; border-bottom:1px solid #f0f0f0; }}
  td.k {{ color:#555; width:42%; }}
  td.v {{ font-weight:600; }}
  .narr {{ background:#f7f7f8; border-left:3px solid {color}; padding:10px 14px;
           border-radius:0 4px 4px 0; margin:6px 0 4px; }}
  .sd {{ font-size:11px; color:#fff; background:#777; padding:1px 6px; border-radius:8px; }}
  .warn {{ color:#8a5a00; background:#fff6e0; border:1px solid #f0d28a; padding:6px 10px;
           border-radius:4px; font-size:12px; margin-top:6px; }}
  .sub {{ font-size:11px; text-transform:uppercase; letter-spacing:.5px; color:#888; margin:8px 0 2px; }}
  ul {{ margin:2px 0 6px; padding-left:20px; }}
  ul.bad li {{ color:#b3261e; }} ul.flag li {{ color:#8a5a00; }}
  .ok {{ color:#0a7d28; }}
  .ist {{ color:#fff; background:{icolor}; font-size:11px; font-weight:700; padding:2px 8px; border-radius:4px; }}
  .foot {{ margin-top:24px; border-top:1px solid #ddd; padding-top:10px; color:#666; font-size:11px; }}
  .sig {{ font-family:ui-monospace,Menlo,monospace; font-size:10.5px; color:#444; word-break:break-all; }}
  .insec {{ color:#b3261e; font-weight:700; }}
  .banner {{ background:#b3261e; color:#fff; font-weight:700; padding:10px 14px;
             border-radius:6px; margin-bottom:14px; text-align:center; }}
</style></head><body>
{banner}
<div class="hd">
  <div>
    <h1>Referee Report</h1>
    <div class="sub">Independent statistical certification of strategy evidence</div>
    <div class="vid">Verification&nbsp;ID&nbsp;<b>{html.escape(signed.get('verification_id',''))}</b></div>
  </div>
  <div style="text-align:right">
    <div class="badge">{badge}</div>
  </div>
</div>

<h2>Verdict</h2>
<div class="narr"><b>{html.escape(v)}.</b> {html.escape(signed.get('narrative',''))}</div>

<h2>Headline metrics</h2>
<table>
  {_row("Deflated Sharpe (DSR)", f"<b>{dsr}</b> &nbsp;(pass bar &gt; {dsr_bar})")}
  {_row("Net Sharpe, annualized", netsh + " &nbsp;vs " + html.escape(str(signed.get('benchmark','—'))))}
  {_row("Probability of Backtest Overfitting", pbo_disp)}
  {_row("Min Track Record Length / T", trl_disp)}
  {_row("Positive in both halves", "yes" if m.get("both_halves") else ("—" if not m else "no"))}
  {_row("Per-year regime", regime_disp)}
  {_row("Total return (raw, net of stated cost)", _fmt(m.get("total_return_pct"), 1) + "%")}
</table>

<h2>Declared search &amp; cost (self-reported, on the record)</h2>
<table>
  {_row("Trials declared", trial_line)}
  {_row("Floor basis", html.escape("; ".join(tr.get("floor_basis", []))))}
  {_row("Cost assumption", f'{_fmt(cost.get("round_trip_bps"),1)} bps round-trip — {html.escape(str(cost.get("label","")))}')}
  {_row("Deflation benchmark SR₀ / V", f'{_fmt(m.get("sr0_per_bar"))} / {_fmt(m.get("deflation_V"),6)}')}
</table>
{under_flag}

<h2>Data integrity <span class="ist">{html.escape(ist)}</span></h2>
{integ_lists}

<h2>Noise battery</h2>
<div>Block-bootstrapped demeaned null, {noise.get('n_boot','—')} resamples:
<b>{html.escape(str(noise.get('status','—')))}</b>
({noise.get('null_passes','—')} of {noise.get('n_boot','—')} nulls cleared DSR;
max null DSR {_fmt(noise.get('max_null_dsr'))}). A green battery means the verdict
is not an artifact of this series' distribution shape.</div>

<div class="foot">
  <div>Graded by the Referee gauntlet (Deflated Sharpe — Bailey &amp; López de Prado 2014;
  PBO via CSCV — Bailey, Borwein, López de Prado &amp; Zhu 2017; Minimum Track Record Length;
  purge + embargo; both-halves; regime conditioning; noise battery). Thresholds are frozen and
  identical to the operator's own runs; no customer override. Returns graded net of the
  self-declared cost above. Trial count is self-declared and shown so a reader can judge it.</div>
  <div style="margin-top:8px"><b>Verification&nbsp;ID</b> {html.escape(signed.get('verification_id',''))}
       &nbsp;·&nbsp; <b>key</b> {html.escape(sig.get('key_id','—'))}{insec}</div>
  <div><b>Verify:</b> {html.escape(sig.get('verify',''))} &nbsp;·&nbsp; public key:
       {html.escape(sig.get('public_key',''))}</div>
  <div>content_hash <span class="sig">{html.escape(signed.get('content_hash',''))}</span></div>
  <div>signature ({html.escape(sig.get('alg','—'))}) <span class="sig">{html.escape(sig.get('value',''))}</span></div>
  <div style="margin-top:6px;color:#999">{html.escape(SIGNATURE_NOTE)}</div>
</div>
</body></html>"""


def render_pdf(html_str: str, out_path: str) -> bool:
    """Best-effort PDF (weasyprint when present). Returns True on success."""
    try:
        from weasyprint import HTML  # type: ignore
    except Exception:
        return False
    HTML(string=html_str).write_pdf(out_path)
    return True


def build_report(verdict: dict, *, out_dir: str, stem: str) -> dict:
    """Sign the verdict and write JSON + HTML (+ PDF if available). Returns the signed dict.

    Raises referee.signing.SigningError if no signing key is configured (production
    guard) — no files are written in that case."""
    signed = sign(verdict)               # production guard enforced here
    json_path = f"{out_dir}/{stem}.json"
    html_path = f"{out_dir}/{stem}.html"
    with open(json_path, "w") as f:
        json.dump(signed, f, indent=2, default=float)
    html_str = render_html(signed)
    with open(html_path, "w") as f:
        f.write(html_str)
    pdf_ok = render_pdf(html_str, f"{out_dir}/{stem}.pdf")
    signed["_artifacts"] = {"json": json_path, "html": html_path,
                            "pdf": (f"{out_dir}/{stem}.pdf" if pdf_ok else None)}
    return signed
