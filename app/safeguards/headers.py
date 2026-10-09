"""
app/safeguards/headers.py

Header Validation and Authentication Safeguard for the Document Intelligence System.
Parses, analyzes, and scores document/email metadata for SPF/DKIM/DMARC alignment,
domain mismatch anomalies, origin spoofing, and relay hop latencies.
"""

import logging
import re
import time
from email.utils import parsedate_to_datetime
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger("document_intelligence_api.safeguards.headers")


class HeaderValidationReport(BaseModel):
    is_suspicious: bool = Field(
        ..., 
        description="Flag set to True if cumulative risk score exceeds suspicious thresholds."
    )
    risk_score: float = Field(
        ..., 
        description="Normalized risk score between 0.0 (clean) and 1.0 (malicious/spoofed)."
    )
    spf_status: str = Field(
        default="none", 
        description="Parsed SPF authentication result (pass, fail, softfail, neutral, none)."
    )
    dkim_status: str = Field(
        default="none", 
        description="Parsed DKIM authentication result (pass, fail, none, present_unverified, invalid_signature)."
    )
    dmarc_status: str = Field(
        default="none", 
        description="Parsed DMARC evaluation result (pass, fail, none)."
    )
    findings: list[str] = Field(
        default_factory=list, 
        description="Detailed list of threat indicators and anomalies detected."
    )
    extracted_metadata: dict[str, Any] = Field(
        default_factory=dict, 
        description="Parsed structural components (e.g., from_domain, return_path_domain, originating_ip, hop_count)."
    )


class HeaderValidator:
    """
    Comprehensive header analysis engine for document intelligence and message authenticity.
    """

    # Domain extraction pattern
    _DOMAIN_REGEX = re.compile(r"@([a-zA-Z0-9.\-]+)", re.IGNORECASE)
    # Generic IPv4 extraction pattern
    _IPV4_REGEX = re.compile(r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b")
    # Headers that must strictly appear at most once
    _SINGLE_INSTANCE_HEADERS = {"from", "subject", "date", "to", "reply-to", "message-id"}

    @classmethod
    def verify_spf_dkim_dmarc(cls, headers: dict[str, Any]) -> HeaderValidationReport:
        """
        Main entry point to perform complete multi-layered verification on metadata headers.
        
        Args:
            headers: Case-insensitive dictionary or object mapping header keys to values.
            
        Returns:
            HeaderValidationReport with findings and risk assessment.
        """
        # Multi-value normalized header tracking
        raw_headers_list: list[tuple[str, str]] = []
        normalized_headers: dict[str, str] = {}
        header_counts: dict[str, int] = {}

        for k, v in headers.items():
            key_lower = str(k).lower().strip()
            val_str = str(v).strip()
            raw_headers_list.append((key_lower, val_str))
            header_counts[key_lower] = header_counts.get(key_lower, 0) + 1
            
            # Store first instance in flat dict for quick lookup
            if key_lower not in normalized_headers:
                normalized_headers[key_lower] = val_str

        findings: list[str] = []
        risk_score: float = 0.0

        # Extract primary identity fields
        from_header = normalized_headers.get("from", "")
        return_path = normalized_headers.get("return-path", "")
        reply_to = normalized_headers.get("reply-to", "")
        auth_results = normalized_headers.get("authentication-results", "").lower()
        received_spf = normalized_headers.get("received-spf", "").lower()
        dkim_signature = normalized_headers.get("dkim-signature", "")
        message_id = normalized_headers.get("message-id", "")
        originating_ip = cls._extract_originating_ip(normalized_headers)

        from_domain = cls._extract_domain(from_header)
        return_path_domain = cls._extract_domain(return_path)
        reply_to_domain = cls._extract_domain(reply_to)

        # ----------------------------------------------------------------------
        # 1. Structural Header Duplication & Anomaly Checks
        # ----------------------------------------------------------------------
        for single_hdr in cls._SINGLE_INSTANCE_HEADERS:
            if header_counts.get(single_hdr, 0) > 1:
                findings.append(f"Header duplication anomaly: '{single_hdr}' header appears {header_counts[single_hdr]} times.")
                risk_score += 0.35

        # ----------------------------------------------------------------------
        # 2. SPF Verification
        # ----------------------------------------------------------------------
        spf_status = cls._parse_spf_status(auth_results, received_spf)
        if spf_status == "fail":
            findings.append("SPF check failed explicitly.")
            risk_score += 0.45
        elif spf_status == "softfail":
            findings.append("SPF check returned softfail.")
            risk_score += 0.25
        elif spf_status == "none" and from_domain:
            findings.append("No SPF authentication record detected in headers.")
            risk_score += 0.10

        # ----------------------------------------------------------------------
        # 3. Deep DKIM Signature Inspection
        # ----------------------------------------------------------------------
        dkim_status = cls._parse_dkim_status(auth_results, dkim_signature)
        if dkim_signature:
            dkim_findings, dkim_risk_delta = cls._verify_dkim_signature_headers(dkim_signature, from_domain)
            findings.extend(dkim_findings)
            risk_score += dkim_risk_delta
            if dkim_risk_delta >= 0.40 and dkim_status == "pass":
                dkim_status = "invalid_signature"

        if dkim_status == "fail":
            findings.append("DKIM cryptographic signature verification failed.")
            risk_score += 0.50

        # ----------------------------------------------------------------------
        # 4. DMARC Evaluation & Domain Alignment
        # ----------------------------------------------------------------------
        dmarc_status = cls._parse_dmarc_status(auth_results)
        if dmarc_status == "fail":
            findings.append("DMARC alignment/policy check failed.")
            risk_score += 0.40

        # Check alignment between 'From' header and 'Return-Path'
        if from_domain and return_path_domain and from_domain != return_path_domain:
            findings.append(
                f"Domain alignment mismatch: From domain ('{from_domain}') "
                f"differs from Return-Path ('{return_path_domain}')."
            )
            risk_score += 0.35

        # Check alignment between 'From' header and 'Reply-To'
        if from_domain and reply_to_domain and from_domain != reply_to_domain:
            findings.append(
                f"Reply-To mismatch: From domain ('{from_domain}') "
                f"differs from Reply-To ('{reply_to_domain}')."
            )
            risk_score += 0.25

        # ----------------------------------------------------------------------
        # 5. Received Hops & Relay Delay Analysis
        # ----------------------------------------------------------------------
        hop_findings, hop_count, total_delay = cls._analyze_received_hops(raw_headers_list)
        findings.extend(hop_findings)
        if total_delay > 1800:  # > 30 minutes unaccounted latency
            risk_score += 0.20

        # ----------------------------------------------------------------------
        # 6. Formatting Anomalies & Tracking Headers
        # ----------------------------------------------------------------------
        if not from_header:
            findings.append("Missing mandatory 'From' header.")
            risk_score += 0.30

        if not message_id:
            findings.append("Missing 'Message-ID' tracking header.")
            risk_score += 0.15
        elif from_domain:
            msg_id_domain = cls._extract_domain(message_id)
            if msg_id_domain and not cls._is_subdomain_or_equal(msg_id_domain, from_domain):
                findings.append(
                    f"Suspicious Message-ID domain ('{msg_id_domain}') "
                    f"does not match From domain ('{from_domain}')."
                )
                risk_score += 0.20

        # Normalize final risk score
        final_risk_score = round(min(1.0, max(0.0, risk_score)), 2)
        is_suspicious = final_risk_score >= 0.40 or len(findings) >= 2

        logger.info(
            f"Header verification complete. Suspicious: {is_suspicious} | "
            f"Risk Score: {final_risk_score} | Hops: {hop_count} | Findings: {len(findings)}"
        )

        return HeaderValidationReport(
            is_suspicious=is_suspicious,
            risk_score=final_risk_score,
            spf_status=spf_status,
            dkim_status=dkim_status,
            dmarc_status=dmarc_status,
            findings=findings,
            extracted_metadata={
                "from_domain": from_domain,
                "return_path_domain": return_path_domain,
                "reply_to_domain": reply_to_domain,
                "originating_ip": originating_ip,
                "relay_hop_count": hop_count,
                "total_relay_delay_seconds": total_delay,
                "has_dkim_sig": bool(dkim_signature),
            }
        )

    # --------------------------------------------------------------------------
    # Private Parsing & Verification Helpers
    # --------------------------------------------------------------------------

    @classmethod
    def _verify_dkim_signature_headers(cls, dkim_sig: str, from_domain: str | None) -> tuple[list[str], float]:
        """Deep parsing of DKIM-Signature tags (v, a, d, s, t, x, b, bh)."""
        findings: list[str] = []
        risk_score = 0.0

        # Parse key=value pairs inside DKIM header
        tags: dict[str, str] = {}
        for part in dkim_sig.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                tags[k.strip().lower()] = v.strip()

        # Check required tags
        required_tags = {"v", "a", "d", "s", "b", "bh"}
        missing_tags = required_tags - set(tags.keys())
        if missing_tags:
            findings.append(f"DKIM signature malformed: missing required tag(s) {', '.join(missing_tags)}.")
            return findings, 0.30

        # Check weak algorithm
        algorithm = tags.get("a", "").lower()
        if "sha1" in algorithm:
            findings.append(f"Insecure/deprecated DKIM algorithm used: '{algorithm}'.")
            risk_score += 0.25

        # Check signature expiration time (x tag) vs creation time (t tag)
        now = time.time()
        if "x" in tags:
            try:
                exp_time = float(tags["x"])
                if now > exp_time:
                    findings.append("DKIM signature has expired.")
                    risk_score += 0.40
            except ValueError:
                findings.append("Invalid DKIM expiration timestamp format.")
                risk_score += 0.15

        # Alignment check: Signing domain (d=) vs From domain
        signing_domain = tags.get("d", "").lower()
        if from_domain and not cls._is_subdomain_or_equal(signing_domain, from_domain):
            findings.append(
                f"DKIM signing domain mismatch: Signature signed by '{signing_domain}', "
                f"but From domain is '{from_domain}'."
            )
            risk_score += 0.35

        return findings, risk_score

    @classmethod
    def _analyze_received_hops(cls, raw_headers: list[tuple[str, str]]) -> tuple[list[str], int, float]:
        """Analyzes Received headers for hop counts, execution delays, and routing anomalies."""
        findings: list[str] = []
        received_headers = [v for k, v in raw_headers if k == "received"]
        hop_count = len(received_headers)
        total_delay = 0.0

        if hop_count > 10:
            findings.append(f"Excessive relay hops detected ({hop_count} hops). Possible mail loop or obfuscation.")

        timestamps: list[float] = []
        for rh in received_headers:
            # Extract date portion after semicolon in Received header
            if ";" in rh:
                date_str = rh.split(";")[-1].strip()
                try:
                    dt = parsedate_to_datetime(date_str)
                    timestamps.append(dt.timestamp())
                except Exception:
                    continue

        # Timestamps in Received headers appear top-to-bottom (newest to oldest)
        if len(timestamps) >= 2:
            timestamps.sort()  # Sort chronologically (oldest to newest)
            total_delay = timestamps[-1] - timestamps[0]
            if total_delay > 1800:  # > 30 mins
                findings.append(f"High transmission delay detected across relay hops ({round(total_delay / 60, 1)} mins).")

        return findings, hop_count, total_delay

    @classmethod
    def _extract_domain(cls, value: str) -> str | None:
        if not value:
            return None
        match = cls._DOMAIN_REGEX.search(value)
        if match:
            return match.group(1).rstrip(">").strip().lower()
        return None

    @classmethod
    def _extract_originating_ip(cls, headers: dict[str, str]) -> str | None:
        for key in ("x-originating-ip", "x-sender-ip", "client-ip"):
            if key in headers:
                ip_match = cls._IPV4_REGEX.search(headers[key])
                if ip_match:
                    return ip_match.group(0)

        received = headers.get("received", "")
        if received:
            ip_match = cls._IPV4_REGEX.search(received)
            if ip_match:
                return ip_match.group(0)

        return None

    @classmethod
    def _parse_spf_status(cls, auth_results: str, received_spf: str) -> str:
        combined = f"{auth_results} {received_spf}"
        if "spf=pass" in combined or "pass" in received_spf:
            return "pass"
        if "spf=fail" in combined or "fail" in received_spf or "hardfail" in received_spf:
            return "fail"
        if "spf=softfail" in combined or "softfail" in received_spf:
            return "softfail"
        if "spf=neutral" in combined:
            return "neutral"
        return "none"

    @classmethod
    def _parse_dkim_status(cls, auth_results: str, dkim_sig: str) -> str:
        if "dkim=pass" in auth_results:
            return "pass"
        if "dkim=fail" in auth_results:
            return "fail"
        if dkim_sig:
            return "present_unverified"
        return "none"

    @classmethod
    def _parse_dmarc_status(cls, auth_results: str) -> str:
        if "dmarc=pass" in auth_results:
            return "pass"
        if "dmarc=fail" in auth_results:
            return "fail"
        return "none"

    @staticmethod
    def _is_subdomain_or_equal(domain1: str, domain2: str) -> bool:
        """Returns True if domain1 is equal to or a subdomain of domain2, or vice versa."""
        d1, d2 = domain1.lower(), domain2.lower()
        return d1 == d2 or d1.endswith(f".{d2}") or d2.endswith(f".{d1}")