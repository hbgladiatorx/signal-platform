"""Referee CLI.

  python -m referee certify <path> --trials N --cost-bps X [options]
  python -m referee verify  <signed.json>

Options for certify:
  --trials N            declared number of configs/params/variants tried (>=1, required)
  --cost-bps X          round-trip cost assumption in bps (required; labeled on the cert)
  --format FMT          trade_log | equity_curve | returns (default: autodetect)
  --gross               returns are gross; deduct cost (trade logs only)
  --benchmark PATH      optional benchmark returns CSV (graded on excess)
  --matrix PATH         optional config-matrix CSV (T x C) -> enables PBO + measured V
  --grid-size N         declared parameter-grid size (raises the provable trial floor)
  --periods-per-year F  override annualization density (default: inferred)
  --seed S              report seed (default: referee-cert-v1)
  --out DIR             output directory (default: alongside input)
  --stem NAME           output filename stem (default: <input>_referee_cert)

No execution, no broker. Grades impersonal evidence; does not manage money.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

import numpy as np
import pandas as pd

from referee import intake, certify as certmod, cert_report, signing


def _load_series(path, kind):
    df = pd.read_csv(path)
    col = intake._find(df.columns, "return", "ret", "r", kind)
    if col is None:
        col = df.columns[-1]
    return pd.to_numeric(df[col], errors="coerce").to_numpy(float)


def _load_matrix(path):
    df = pd.read_csv(path)
    num = df.select_dtypes(include=[np.number])
    return num.to_numpy(float)


def cmd_certify(a) -> int:
    signing.startup_check()        # worker-side posture assertion (loud on insecure)
    out_dir = a.out or os.path.dirname(os.path.abspath(a.path)) or "."
    os.makedirs(out_dir, exist_ok=True)
    stem = a.stem or (os.path.splitext(os.path.basename(a.path))[0] + "_referee_cert")

    try:
        sub = intake.parse_submission(
            a.path, fmt=a.format, cost_bps=a.cost_bps, declared_trials=a.trials,
            returns_are_gross=a.gross, periods_per_year=a.periods_per_year)
    except intake.SubmissionError as e:
        # a parse failure is itself an UNVERIFIABLE verdict, signed and reported
        verdict = {"schema": "referee.cert/1", "seed": a.seed, "verdict": "UNVERIFIABLE",
                   "narrative": f"Submission could not be parsed: {e}",
                   "integrity": {"status": "UNVERIFIABLE", "reasons": [str(e)], "flags": []},
                   "trials": {"declared_trials": a.trials, "self_declared": True}}
        return _emit(verdict, out_dir, stem, rc=2)

    bench = _load_series(a.benchmark, "benchmark") if a.benchmark else None
    matrix = _load_matrix(a.matrix) if a.matrix else None

    verdict = certmod.certify(sub, benchmark_returns=bench, config_matrix=matrix,
                              declared_grid_size=a.grid_size, seed=a.seed)
    return _emit(verdict, out_dir, stem, rc=0)


def _emit(verdict, out_dir, stem, rc) -> int:
    """Sign + write the report, honoring the production signing guard."""
    try:
        signed = cert_report.build_report(verdict, out_dir=out_dir, stem=stem)
    except signing.SigningError as e:
        print("=" * 70)
        print("REFEREE: REFUSING TO ISSUE CERTIFICATE")
        print("=" * 70)
        print(f"  {e}")
        print(f"  Set {signing.PRIVATE_ENV} to a real Ed25519 key, or (dev only) "
              f"export {signing.ALLOW_INSECURE_ENV}=1 to sign with the insecure dev key.")
        return 4
    _print_summary(signed)
    return rc


def cmd_verify(a) -> int:
    signed = json.load(open(a.path))
    res = cert_report.verify(signed)
    sig = signed.get("signature", {})
    print(f"verification_id : {res.get('verification_id')}")
    print(f"key_id          : {res.get('key_id')}  (alg {sig.get('alg','—')})")
    print(f"content_hash ok : {res['content_ok']}")
    print(f"signature   ok  : {res['signature_ok']}"
          + ("   *** INSECURE DEV KEY — do not trust ***" if res.get("insecure") else ""))
    ok = res["content_ok"] and res["signature_ok"] and not res.get("insecure")
    print(f"AUTHENTIC       : {ok}")
    return 0 if ok else 1


def cmd_keygen(a) -> int:
    """Generate an Ed25519 keypair, publish the PUBLIC key, print the PRIVATE key
    once for the operator to store in a secret manager. Private key is never
    written to disk by this command."""
    priv_b64, pub_b64 = signing.generate_keypair()
    pub = signing.load_public_b64(pub_b64)
    kid = signing.key_id(pub)
    pub_path = signing.publish_public_key(pub_b64, kid, make_current=not a.not_current)
    print("=" * 70)
    print("REFEREE Ed25519 KEYPAIR")
    print("=" * 70)
    print(f"key_id        : {kid}")
    print(f"published .pub : {pub_path}")
    print(f"public (b64)  : {pub_b64}")
    print()
    print(f"PRIVATE KEY (store as {signing.PRIVATE_ENV} in a secret manager; shown ONCE):")
    print(f"  {priv_b64}")
    print()
    print("Do NOT commit, log, or paste the private key anywhere persistent.")
    return 0


def _print_summary(signed):
    m = signed.get("metrics", {})
    tr = signed.get("trials", {})
    print("=" * 70)
    print(f"REFEREE CERT  {signed.get('verification_id','')}")
    print("=" * 70)
    print(f"verdict        : {signed['verdict']}")
    print(f"  {signed.get('narrative','')}")
    if m:
        print(f"DSR            : {m.get('dsr'):.3f}  (bar > {m.get('dsr_bar')})")
        print(f"net Sharpe ann : {m.get('net_sharpe_annualized'):.2f}  vs {signed.get('benchmark')}")
        trl = m.get('min_trl')
        print(f"MinTRL / T     : {('%.0f'%trl) if trl else '∞'} / {m.get('T')}")
        print(f"both halves    : {m.get('both_halves')}   regime: {m.get('regime')}")
    pbo = signed.get("pbo_cscv")
    print(f"PBO            : {('n/a (single config)' if pbo is None else round(pbo['pbo'],3))}")
    nb = signed.get("noise_battery", {})
    print(f"noise battery  : {nb.get('status')}  ({nb.get('null_passes')}/{nb.get('n_boot')} null passes)")
    print(f"trials         : declared {tr.get('declared_trials')} (self_declared)"
          f"  floor {tr.get('provable_floor')}  -> deflated at {tr.get('n_trials_used')}")
    print(f"integrity      : {signed.get('integrity',{}).get('status')}")
    sig = signed.get("signature", {})
    print(f"verification_id: {signed.get('verification_id')}  key {sig.get('key_id')}")
    print(f"content_hash   : {signed.get('content_hash','')[:32]}...")
    print(f"signature      : {sig.get('alg')} {sig.get('value','')[:24]}..."
          + ("  [INSECURE DEV KEY]" if sig.get("insecure") else ""))
    art = signed.get("_artifacts", {})
    print(f"report HTML    : {art.get('html')}")
    print(f"report JSON    : {art.get('json')}")
    print(f"report PDF     : {art.get('pdf') or '(weasyprint not installed; HTML is print-to-PDF ready)'}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="referee", description="Referee strategy certification")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("certify", help="certify an external strategy submission")
    c.add_argument("path")
    c.add_argument("--trials", type=int, required=True)
    c.add_argument("--cost-bps", dest="cost_bps", type=float, required=True)
    c.add_argument("--format", choices=["trade_log", "equity_curve", "returns"], default=None)
    c.add_argument("--gross", action="store_true")
    c.add_argument("--benchmark", default=None)
    c.add_argument("--matrix", default=None)
    c.add_argument("--grid-size", dest="grid_size", type=int, default=None)
    c.add_argument("--periods-per-year", dest="periods_per_year", type=float, default=None)
    c.add_argument("--seed", default="referee-cert-v1")
    c.add_argument("--out", default=None)
    c.add_argument("--stem", default=None)
    c.set_defaults(func=cmd_certify)

    vy = sub.add_parser("verify", help="verify a signed cert JSON")
    vy.add_argument("path")
    vy.set_defaults(func=cmd_verify)

    kg = sub.add_parser("keygen", help="generate + publish an Ed25519 signing keypair")
    kg.add_argument("--not-current", dest="not_current", action="store_true",
                    help="publish the key but do not make it the current signer")
    kg.set_defaults(func=cmd_keygen)

    a = p.parse_args(argv)
    return a.func(a)


if __name__ == "__main__":
    sys.exit(main())
