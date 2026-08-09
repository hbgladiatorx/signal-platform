"""Referee certification HTTP surface.

Wires the existing, unchanged `referee/` engine (intake -> certify -> cert_report
-> signing) to authenticated HTTP. An external caller submits strategy evidence
and gets back the same honest, Ed25519-signed verdict the CLI produces.

Endpoints (prefix /referee):
  POST /referee/certify          submit evidence + declared trials + cost -> signed cert
  GET  /referee/cert/{vid}       fetch a previously issued cert (our copy) by id
  GET  /referee/cert/{vid}/report  the one-page HTML research note for a cert
  GET  /referee/pubkey           published Ed25519 public key (PUBLIC — offline verify)
  POST /referee/verify           verify a posted cert against the published key (PUBLIC)

The boundary guard is the whole point: the API enforces the SAME production
signing guard the library does. If no real key is configured and insecure mode
isn't explicitly enabled, `certify` returns 503 and NO cert — there is no silent
dev-key fallback over HTTP. When insecure mode is explicitly on, every cert is
stamped `insecure:true`, exactly as the CLI. No gauntlet threshold is loosened
for an API caller; the declared trial count is fed into the deflation verbatim
and stated on the cert as self_declared.

Minimal adapter (no engine change): the engine's `intake.parse_submission` reads
a CSV *path*, so posted evidence (a JSON returns array or inline CSV text) is
written to a short-lived temp CSV and handed to the unchanged parser. That is the
only glue; the gauntlet, signing scheme, and report are untouched.
"""
from __future__ import annotations

import os
import tempfile
from typing import Any, Literal, Optional
from uuid import uuid4

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator

from referee import cert_report, certify as certmod, intake, signing
from services.api.deps import get_current_user_record

router = APIRouter(prefix="/referee", tags=["referee"])


# ============================================================
# Request / response models (documented, not loose dicts)
# ============================================================
class CertifyRequest(BaseModel):
    """An external strategy submission to grade.

    Provide the evidence as EITHER a posted returns series (`returns`) OR inline
    CSV text (`csv_text`, a trade-log / equity-curve / returns export) — exactly
    one. `declared_trials` and `cost_bps` are the submitter's self-declared search
    size and round-trip cost; both are stamped on the cert and fed to the gauntlet
    unchanged.
    """

    model_config = ConfigDict(extra="forbid")

    declared_trials: int = Field(
        ..., ge=1,
        description="Configs/variants the submitter tried to reach this strategy "
                    "(>=1; declare 1 if no search was run). Fed into the deflation.",
    )
    cost_bps: float = Field(
        ..., ge=0,
        description="Round-trip cost assumption in bps; labeled on the cert.",
    )
    returns: Optional[list[float]] = Field(
        default=None,
        description="Posted per-observation returns series (net unless returns_are_gross).",
    )
    csv_text: Optional[str] = Field(
        default=None,
        description="Inline CSV upload (trade_log / equity_curve / returns columns).",
    )
    fmt: Optional[Literal["trade_log", "equity_curve", "returns"]] = Field(
        default=None, description="Force a format; default autodetects.",
    )
    returns_are_gross: bool = Field(
        default=False,
        description="If true (trade logs only), the engine deducts cost_bps per trade.",
    )
    benchmark: Optional[list[float]] = Field(
        default=None,
        description="Optional benchmark returns; the strategy is graded on excess.",
    )
    declared_grid_size: Optional[int] = Field(
        default=None, ge=1,
        description="Declared parameter-grid size; raises the provable trial floor.",
    )
    config_matrix: Optional[list[list[float]]] = Field(
        default=None,
        description="Optional T x C matrix of per-config return series; enables "
                    "PBO/CSCV and a measured deflation variance.",
    )
    periods_per_year: Optional[float] = Field(
        default=None, gt=0, description="Override annualization density (else inferred).",
    )
    seed: str = Field(default="referee-cert-v1", description="Deterministic report seed.")

    @model_validator(mode="after")
    def _exactly_one_evidence(self) -> "CertifyRequest":
        if bool(self.returns) == bool(self.csv_text):
            raise ValueError("provide exactly one of `returns` or `csv_text`")
        return self


class CertResponse(BaseModel):
    """A signed Referee cert plus the convenience fields lifted to the top level."""

    verification_id: Optional[str] = Field(
        None, description="RFE-... id; also the handle for GET /referee/cert/{id}.",
    )
    verdict: str = Field(..., description="DEPLOY | HOLD_CONDITIONAL | REJECT | UNVERIFIABLE.")
    insecure: bool = Field(..., description="True if signed by the dev key (do not trust).")
    declared_trials: Optional[int] = Field(None, description="Self-declared trial count.")
    n_trials_used: Optional[int] = Field(
        None, description="Trials actually used in deflation = max(declared, provable floor).",
    )
    self_declared: bool = Field(True, description="The trial/cost figures are submitter-declared.")
    report_url: Optional[str] = Field(None, description="Path to fetch the rendered cert.")
    cert: dict[str, Any] = Field(
        ..., description="The full signed verdict, verbatim (server file paths stripped).",
    )


class PubkeyResponse(BaseModel):
    alg: str = "ed25519"
    key_id: str
    public_key_b64: str
    published_endpoint: str


class VerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    cert: dict[str, Any] = Field(..., description="A signed cert to check against the published key.")


class VerifyResponse(BaseModel):
    content_ok: bool = Field(..., description="Body re-hashes to the stored content_hash.")
    signature_ok: bool = Field(..., description="Ed25519 signature binds under the published key.")
    insecure: bool
    authentic: bool = Field(..., description="content_ok AND signature_ok AND not insecure.")
    key_id: Optional[str] = None
    verification_id: Optional[str] = None


# ============================================================
# Helpers
# ============================================================
def _store_dir() -> str:
    """Directory where issued certs (signed JSON + HTML) are written and later
    looked up by verification_id. Configurable via REFEREE_CERT_STORE."""
    d = os.environ.get("REFEREE_CERT_STORE") or os.path.join(
        tempfile.gettempdir(), "referee_certs")
    os.makedirs(d, exist_ok=True)
    return d


def _require_signing_or_503() -> None:
    """The boundary guard. Enforce the library's production signing rule BEFORE
    running the gauntlet: no real key and no explicit insecure flag => refuse with
    a clear 503 and never a cert. No silent dev-key fallback over HTTP."""
    try:
        signing.get_signer()
    except signing.SigningError as e:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "signing_unavailable",
                "msg": str(e),
                "hint": f"Set {signing.PRIVATE_ENV} to a real Ed25519 key, or (dev only) "
                        f"set {signing.ALLOW_INSECURE_ENV}=1 to sign with the insecure dev key.",
            },
        )


def _certify_to_signed(*, evidence_csv_path: str, req: CertifyRequest) -> dict:
    """intake -> certify -> sign+write, identical to the CLI flow. A parse failure
    is itself a signed UNVERIFIABLE cert (never a silent drop)."""
    try:
        sub = intake.parse_submission(
            evidence_csv_path, fmt=req.fmt, cost_bps=req.cost_bps,
            declared_trials=req.declared_trials,
            returns_are_gross=req.returns_are_gross,
            periods_per_year=req.periods_per_year,
        )
    except intake.SubmissionError as e:
        verdict = {
            "schema": "referee.cert/1", "seed": req.seed, "verdict": "UNVERIFIABLE",
            "narrative": f"Submission could not be parsed: {e}",
            "integrity": {"status": "UNVERIFIABLE", "reasons": [str(e)], "flags": []},
            "trials": {"declared_trials": req.declared_trials, "self_declared": True},
        }
    else:
        bench = (np.asarray(req.benchmark, dtype=float)
                 if req.benchmark is not None else None)
        matrix = (np.asarray(req.config_matrix, dtype=float)
                  if req.config_matrix else None)
        verdict = certmod.certify(
            sub, benchmark_returns=bench, config_matrix=matrix,
            declared_grid_size=req.declared_grid_size, seed=req.seed,
        )
    # build_report signs (production guard enforced again here) and writes the
    # JSON+HTML into the store, keyed for later lookup by verification_id.
    return cert_report.build_report(verdict, out_dir=_store_dir(), stem=uuid4().hex)


def _to_cert_response(signed: dict) -> CertResponse:
    sig = signed.get("signature", {}) or {}
    trials = signed.get("trials", {}) or {}
    # `_artifacts` holds server-local file paths and is excluded from the signed
    # body, so stripping it does not affect verification.
    cert = {k: v for k, v in signed.items() if k != "_artifacts"}
    vid = signed.get("verification_id")
    declared = trials.get("declared_trials")
    n_used = trials.get("n_trials_used", declared)
    return CertResponse(
        verification_id=vid,
        verdict=signed.get("verdict", "UNVERIFIABLE"),
        insecure=bool(sig.get("insecure")),
        declared_trials=int(declared) if declared is not None else None,
        n_trials_used=int(n_used) if n_used is not None else None,
        self_declared=bool(trials.get("self_declared", True)),
        report_url=(f"/referee/cert/{vid}" if vid else None),
        cert=cert,
    )


# ============================================================
# Endpoints
# ============================================================
@router.post("/certify", response_model=CertResponse)
async def certify_submission(
    req: CertifyRequest,
    user: Any = Depends(get_current_user_record),
) -> CertResponse:
    """Grade an external submission and return a signed verdict. Same bar as the
    CLI; the declared trial count is fed into the deflation verbatim."""
    _require_signing_or_503()  # refuse up front; never run the gauntlet then refuse

    tmpdir = tempfile.mkdtemp(prefix="referee_in_")
    try:
        csv_path = os.path.join(tmpdir, "submission.csv")
        if req.returns is not None:
            with open(csv_path, "w") as f:
                f.write("return\n")
                f.write("\n".join(repr(float(x)) for x in req.returns))
        else:
            with open(csv_path, "w") as f:
                f.write(req.csv_text)
        try:
            signed = _certify_to_signed(evidence_csv_path=csv_path, req=req)
        except signing.SigningError as e:
            # Defense in depth: build_report enforces the guard too.
            raise HTTPException(
                status_code=503,
                detail={"error": "signing_unavailable", "msg": str(e)},
            )
    finally:
        try:
            for n in os.listdir(tmpdir):
                os.remove(os.path.join(tmpdir, n))
            os.rmdir(tmpdir)
        except OSError:
            pass
    return _to_cert_response(signed)


@router.get("/cert/{verification_id}", response_model=CertResponse)
async def get_cert(
    verification_id: str,
    user: Any = Depends(get_current_user_record),
) -> CertResponse:
    """Return OUR stored copy of a previously issued cert (the caller verifies it
    independently). Uses the engine's verification_id_lookup contract."""
    rec = signing.verification_id_lookup(verification_id, _store_dir())
    if rec is None:
        raise HTTPException(
            status_code=404,
            detail={"error": "not_found",
                    "msg": f"No cert issued for {verification_id!r}."},
        )
    return _to_cert_response(rec)


@router.get("/cert/{verification_id}/report", response_class=HTMLResponse)
async def get_cert_report(
    verification_id: str,
    user: Any = Depends(get_current_user_record),
) -> HTMLResponse:
    """The one-page HTML research note for an issued cert."""
    rec = signing.verification_id_lookup(verification_id, _store_dir())
    if rec is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    html_path = (rec.get("_artifacts") or {}).get("html")
    if html_path and os.path.exists(html_path):
        with open(html_path) as f:
            return HTMLResponse(f.read())
    # Fall back to regenerating the note from the stored signed JSON.
    return HTMLResponse(cert_report.render_html(rec))


@router.get("/pubkey", response_model=PubkeyResponse)
async def get_pubkey() -> PubkeyResponse:
    """The published Ed25519 public key (PUBLIC). Any third party verifies a cert
    offline with this — no auth, no secret."""
    pub = signing.load_published_public(None)
    if pub is None:
        raise HTTPException(
            status_code=503,
            detail={"error": "no_published_key", "msg": "No public key is published."},
        )
    return PubkeyResponse(
        key_id=signing.key_id(pub),
        public_key_b64=signing.pub_to_b64(pub),
        published_endpoint=signing.PUBKEY_ENDPOINT,
    )


@router.post("/verify", response_model=VerifyResponse)
async def verify_cert(req: VerifyRequest) -> VerifyResponse:
    """Check a posted cert against the published key (PUBLIC). `authentic` is true
    only when the content is unedited, the signature binds, and it isn't insecure."""
    res = cert_report.verify(req.cert)
    authentic = bool(res["content_ok"] and res["signature_ok"] and not res["insecure"])
    return VerifyResponse(
        content_ok=bool(res["content_ok"]),
        signature_ok=bool(res["signature_ok"]),
        insecure=bool(res["insecure"]),
        authentic=authentic,
        key_id=res.get("key_id"),
        verification_id=res.get("verification_id"),
    )
