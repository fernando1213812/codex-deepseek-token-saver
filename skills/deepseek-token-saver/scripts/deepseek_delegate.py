#!/usr/bin/env python3
"""Delegate low-risk Codex work to DeepSeek and log token savings.

This script is intentionally standard-library only so it can be bundled inside
a Codex skill. It never prints API keys and can read the key from either
DEEPSEEK_API_KEY or macOS Keychain.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import email.utils
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from typing import Any


API_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-chat"
DEFAULT_KEYCHAIN_SERVICE = "codex-deepseek-api-key"
RETRYABLE_HTTP_STATUS = {408, 409, 429}
DEFAULT_SYSTEM = (
    "You are assisting Codex by producing candidate material for a low-risk "
    "drafting or exploration phase. Be concise, concrete, and easy to review. "
    "When asked to implement code, produce complete candidate source files "
    "instead of only an outline. Do not claim final authority; Codex will audit "
    "your output."
)
FINAL_REVIEW_TERMS = {
    "audit",
    "review",
    "final",
    "ship",
    "release",
    "publish",
    "deploy",
    "security",
    "auth",
    "credential",
    "payment",
    "legal",
    "medical",
    "delete",
    "destructive",
    "production",
    "merge",
}
DEEPSEEK_FRIENDLY_TERMS = {
    "draft",
    "brainstorm",
    "summarize",
    "extract",
    "rewrite",
    "boilerplate",
    "example",
    "variant",
    "batch",
    "translate",
    "outline",
    "candidate",
}


@dataclasses.dataclass(frozen=True)
class RouteDecision:
    route: str
    reason: str
    requires_gpt55_review: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Route a task and optionally delegate low-risk work to DeepSeek.",
    )
    parser.add_argument("prompt", nargs="*", help="Task prompt. Uses stdin when omitted.")
    parser.add_argument("--model", default=os.environ.get("DEEPSEEK_MODEL", DEFAULT_MODEL))
    parser.add_argument("--system", default=os.environ.get("DEEPSEEK_SYSTEM", DEFAULT_SYSTEM))
    parser.add_argument(
        "--phase",
        choices=("auto", "brainstorm", "draft", "batch", "implement", "review", "final"),
        default="auto",
        help="Work phase. Review/final phases route to GPT-5.5 unless forced.",
    )
    parser.add_argument(
        "--risk",
        choices=("low", "medium", "high"),
        default="low",
        help="Task risk. High risk routes to GPT-5.5 unless forced.",
    )
    parser.add_argument(
        "--urgency",
        choices=("low", "normal", "high"),
        default="normal",
        help="DeepSeek is preferred for non-urgent work; urgent final work stays with GPT-5.5.",
    )
    parser.add_argument("--max-tokens", type=int, default=1800)
    parser.add_argument(
        "--min-response-chars",
        type=int,
        default=int(os.environ.get("DEEPSEEK_MIN_RESPONSE_CHARS", "0")),
        help="Fail the call when the assistant response is shorter than this.",
    )
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument(
        "--max-retries",
        type=int,
        default=int(os.environ.get("DEEPSEEK_MAX_RETRIES", "2")),
        help="Retry transient HTTP/network failures this many times.",
    )
    parser.add_argument(
        "--retry-initial-delay",
        type=float,
        default=float(os.environ.get("DEEPSEEK_RETRY_INITIAL_DELAY", "0.5")),
        help="Initial exponential-backoff delay in seconds.",
    )
    parser.add_argument(
        "--retry-max-delay",
        type=float,
        default=float(os.environ.get("DEEPSEEK_RETRY_MAX_DELAY", "8")),
        help="Maximum exponential-backoff delay in seconds.",
    )
    parser.add_argument(
        "--thinking",
        choices=("auto", "enabled"),
        default=os.environ.get("DEEPSEEK_THINKING", "auto"),
        help="Send DeepSeek thinking mode only when explicitly enabled.",
    )
    parser.add_argument("--out", help="Write assistant text to this file.")
    parser.add_argument(
        "--log-file",
        default=os.environ.get(
            "DEEPSEEK_DELEGATE_LOG",
            str(Path.cwd() / ".deepseek-token-saver" / "calls.jsonl"),
        ),
        help="JSONL usage log path.",
    )
    parser.add_argument(
        "--route-only",
        action="store_true",
        help="Only print the routing decision; do not call DeepSeek.",
    )
    parser.add_argument(
        "--force-deepseek",
        action="store_true",
        help="Call DeepSeek even if routing policy recommends GPT-5.5.",
    )
    parser.add_argument("--json", action="store_true", help="Print a JSON result envelope.")
    parser.add_argument("--raw", action="store_true", help="Include sanitized raw API JSON.")
    parser.add_argument("--verbose", action="store_true", help="Print retry diagnostics to stderr.")
    parser.add_argument("--no-keychain", action="store_true")
    parser.add_argument(
        "--savings-ratio",
        type=float,
        default=float(os.environ.get("DEEPSEEK_CODEX_SAVINGS_RATIO", "0.70")),
        help="Rough fraction of DeepSeek tokens assumed to be saved from Codex usage.",
    )
    return parser.parse_args()


def read_prompt(args: argparse.Namespace) -> str:
    if args.prompt:
        return " ".join(args.prompt).strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    return ""


def redact_secrets(text: str) -> str:
    text = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "sk-****", text)
    text = re.sub(r"(Bearer\s+)[A-Za-z0-9._-]+", r"\1****", text)
    return text


def infer_route(prompt: str, phase: str, risk: str, urgency: str) -> RouteDecision:
    lower = prompt.lower()
    terms = set(re.findall(r"[a-z0-9_-]+", lower))
    has_final_term = bool(terms & FINAL_REVIEW_TERMS)
    has_deepseek_term = bool(terms & DEEPSEEK_FRIENDLY_TERMS)

    if phase in {"review", "final"}:
        return RouteDecision(
            "gpt-5.5",
            "review/final phases must stay with GPT-5.5 for correctness.",
            False,
        )
    if risk == "high" or has_final_term:
        return RouteDecision(
            "gpt-5.5",
            "high-risk or finality/security terms require GPT-5.5.",
            False,
        )
    if phase in {"brainstorm", "draft", "batch"}:
        return RouteDecision(
            "deepseek",
            "low-risk non-final drafting/batch work is suitable for DeepSeek.",
            True,
        )
    if phase == "implement":
        return RouteDecision(
            "hybrid",
            "DeepSeek can draft bounded implementation; GPT-5.5 must review and verify.",
            True,
        )
    if urgency == "low" or has_deepseek_term:
        return RouteDecision(
            "deepseek",
            "non-urgent exploratory wording indicates DeepSeek-friendly work.",
            True,
        )
    return RouteDecision(
        "hybrid",
        "default to DeepSeek for candidate generation and GPT-5.5 for audit.",
        True,
    )


def read_key_from_keychain() -> str | None:
    if sys.platform != "darwin":
        return None
    service = os.environ.get("DEEPSEEK_KEYCHAIN_SERVICE", DEFAULT_KEYCHAIN_SERVICE)
    account = os.environ.get("DEEPSEEK_KEYCHAIN_ACCOUNT", os.environ.get("USER", ""))
    if not account:
        return None
    try:
        result = subprocess.run(
            ["security", "find-generic-password", "-a", account, "-s", service, "-w"],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def read_api_key(args: argparse.Namespace) -> str | None:
    if os.environ.get("DEEPSEEK_API_KEY"):
        return os.environ["DEEPSEEK_API_KEY"]
    if args.no_keychain:
        return None
    return read_key_from_keychain()


def build_ssl_context() -> ssl.SSLContext:
    candidates = [
        os.environ.get("DEEPSEEK_CA_BUNDLE"),
        ssl.get_default_verify_paths().cafile,
        "/etc/ssl/cert.pem",
    ]
    for candidate in candidates:
        if candidate and os.path.exists(candidate):
            return ssl.create_default_context(cafile=candidate)
    return ssl.create_default_context()


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    non_cjk = len(text) - cjk
    return max(1, math.ceil(cjk * 1.2 + non_cjk / 4))


def parse_retry_after(headers: Any) -> float | None:
    if not headers:
        return None
    retry_after_ms = headers.get("retry-after-ms") if hasattr(headers, "get") else None
    try:
        return float(retry_after_ms) / 1000
    except (TypeError, ValueError):
        pass

    retry_after = headers.get("retry-after") if hasattr(headers, "get") else None
    try:
        return float(retry_after)
    except (TypeError, ValueError):
        pass

    retry_date_tuple = email.utils.parsedate_tz(retry_after)
    if retry_date_tuple is None:
        return None
    return float(email.utils.mktime_tz(retry_date_tuple) - time.time())


def calculate_retry_delay(args: argparse.Namespace, attempt: int, headers: Any = None) -> float:
    retry_after = parse_retry_after(headers)
    if retry_after is not None and 0 < retry_after <= 60:
        return retry_after
    capped_attempt = min(attempt, 12)
    base = min(args.retry_initial_delay * pow(2.0, capped_attempt), args.retry_max_delay)
    return max(0.0, base * (1 - 0.25 * random.random()))


def should_retry_http(status_code: int) -> bool:
    return status_code in RETRYABLE_HTTP_STATUS or status_code >= 500


def call_deepseek(args: argparse.Namespace, prompt: str) -> dict[str, Any]:
    api_key = read_api_key(args)
    if not api_key:
        raise RuntimeError(
            "No DeepSeek API key found. Set DEEPSEEK_API_KEY or store it in "
            f"macOS Keychain service {DEFAULT_KEYCHAIN_SERVICE!r}."
        )

    payload: dict[str, Any] = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": args.system},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": args.max_tokens,
        "temperature": args.temperature,
    }
    if args.thinking == "enabled":
        payload["thinking"] = {"type": "enabled"}

    max_retries = max(0, args.max_retries)
    context = build_ssl_context()
    last_error: str | None = None
    for attempt in range(max_retries + 1):
        request = urllib.request.Request(
            API_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=args.timeout,
                context=context,
            ) as response:
                body = response.read().decode("utf-8")
                status = getattr(response, "status", 200)
                headers = response.headers
        except urllib.error.HTTPError as exc:
            detail = redact_secrets(exc.read().decode("utf-8", errors="replace"))
            last_error = f"DeepSeek API returned HTTP {exc.code}: {detail}"
            if attempt < max_retries and should_retry_http(exc.code):
                delay = calculate_retry_delay(args, attempt, exc.headers)
                if args.verbose:
                    print(
                        f"Retrying DeepSeek HTTP {exc.code} in {delay:.2f}s "
                        f"({attempt + 1}/{max_retries})",
                        file=sys.stderr,
                    )
                time.sleep(delay)
                continue
            raise RuntimeError(last_error) from exc
        except urllib.error.URLError as exc:
            last_error = f"Could not reach DeepSeek API: {exc.reason}"
            if attempt < max_retries:
                delay = calculate_retry_delay(args, attempt)
                if args.verbose:
                    print(
                        f"Retrying DeepSeek network error in {delay:.2f}s "
                        f"({attempt + 1}/{max_retries})",
                        file=sys.stderr,
                    )
                time.sleep(delay)
                continue
            raise RuntimeError(last_error) from exc

        try:
            result = json.loads(body)
        except json.JSONDecodeError as exc:
            raise RuntimeError("DeepSeek response was not valid JSON: " + redact_secrets(body[:800])) from exc
        result["_codex_request"] = {
            "attempts": attempt + 1,
            "status": status,
            "thinking": args.thinking,
        }
        return result

    raise RuntimeError(last_error or "DeepSeek request failed.")


def extract_message(result: dict[str, Any]) -> str:
    choices = result.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    return ""


def extract_finish_reason(result: dict[str, Any]) -> str | None:
    choices = result.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    choice = choices[0]
    if not isinstance(choice, dict):
        return None
    reason = choice.get("finish_reason")
    return reason if isinstance(reason, str) else None


def extract_reasoning_chars(result: dict[str, Any]) -> int:
    choices = result.get("choices")
    if not isinstance(choices, list) or not choices:
        return 0
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return 0
    reasoning = message.get("reasoning_content")
    return len(reasoning) if isinstance(reasoning, str) else 0


def request_meta(result: dict[str, Any]) -> dict[str, Any]:
    meta = result.get("_codex_request")
    return meta if isinstance(meta, dict) else {}


def usage_summary(result: dict[str, Any], prompt: str, response_text: str) -> dict[str, int]:
    usage = result.get("usage")
    if not isinstance(usage, dict):
        prompt_tokens = estimate_tokens(prompt)
        completion_tokens = estimate_tokens(response_text)
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "estimated": 1,
        }
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or prompt_tokens + completion_tokens)
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "estimated": 0,
    }


def log_call(
    *,
    args: argparse.Namespace,
    prompt: str,
    decision: RouteDecision,
    response_text: str,
    usage: dict[str, int],
    finish_reason: str | None,
    reasoning_chars: int,
    request_metadata: dict[str, Any],
    quality_status: str = "unchecked",
    quality_issues: list[str] | None = None,
    output_written: bool = False,
) -> dict[str, Any]:
    saved = max(0, round(usage["total_tokens"] * max(0.0, args.savings_ratio)))
    entry = {
        "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
        "model": args.model,
        "route": decision.route,
        "phase": args.phase,
        "risk": args.risk,
        "urgency": args.urgency,
        "requires_gpt55_review": decision.requires_gpt55_review,
        "reason": decision.reason,
        "prompt_hash": hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16],
        "prompt_chars": len(prompt),
        "response_chars": len(response_text),
        "finish_reason": finish_reason,
        "reasoning_chars": reasoning_chars,
        "quality_gate": {
            "status": quality_status,
            "issues": quality_issues or [],
        },
        "output_written": output_written,
        "request": request_metadata,
        "usage": usage,
        "estimated_codex_tokens_saved": saved,
        "savings_ratio": args.savings_ratio,
    }
    if args.out:
        entry["output_path"] = str(Path(args.out))

    log_path = Path(args.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
    return entry


def print_text_result(decision: RouteDecision, text: str, log_entry: dict[str, Any] | None) -> None:
    print(f"Route: {decision.route}")
    print(f"Reason: {decision.reason}")
    if decision.requires_gpt55_review:
        print("Review: GPT-5.5 must audit before final use.")
    if log_entry:
        usage = log_entry["usage"]
        print(
            "DeepSeek tokens: "
            f"{usage['total_tokens']} total "
            f"({usage['prompt_tokens']} prompt, {usage['completion_tokens']} completion)"
        )
        print(f"Estimated Codex tokens saved: {log_entry['estimated_codex_tokens_saved']}")
    if text:
        print("\n" + text)


def main() -> int:
    args = parse_args()
    prompt = read_prompt(args)
    if not prompt:
        print("No prompt provided.", file=sys.stderr)
        return 1

    decision = infer_route(prompt, args.phase, args.risk, args.urgency)
    if args.force_deepseek and decision.route == "gpt-5.5":
        decision = RouteDecision(
            "hybrid",
            "forced DeepSeek candidate generation; GPT-5.5 review remains required.",
            True,
        )

    if args.route_only or decision.route == "gpt-5.5":
        envelope = {"decision": dataclasses.asdict(decision)}
        if args.json:
            print(json.dumps(envelope, ensure_ascii=False, indent=2))
        else:
            print_text_result(decision, "", None)
        return 0

    try:
        result = call_deepseek(args, prompt)
    except RuntimeError as exc:
        print(redact_secrets(str(exc)), file=sys.stderr)
        return 2

    response_text = extract_message(result)
    if not response_text:
        print("DeepSeek returned an empty assistant message.", file=sys.stderr)
        if args.raw:
            print(redact_secrets(json.dumps(result, ensure_ascii=False, indent=2)))
        return 3

    usage = usage_summary(result, prompt, response_text)
    finish_reason = extract_finish_reason(result)
    reasoning_chars = extract_reasoning_chars(result)
    request_metadata = request_meta(result)
    if args.min_response_chars and len(response_text) < args.min_response_chars:
        entry = log_call(
            args=args,
            prompt=prompt,
            decision=decision,
            response_text=response_text,
            usage=usage,
            finish_reason=finish_reason,
            reasoning_chars=reasoning_chars,
            request_metadata=request_metadata,
            quality_status="fail",
            quality_issues=[f"response_too_short:{len(response_text)}<{args.min_response_chars}"],
            output_written=False,
        )
        print(
            "DeepSeek response failed quality gate: "
            f"{len(response_text)} chars < {args.min_response_chars} required "
            f"(finish_reason={finish_reason}, reasoning_chars={reasoning_chars}).",
            file=sys.stderr,
        )
        if args.raw:
            print(redact_secrets(json.dumps(result, ensure_ascii=False, indent=2)))
        return 4

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(response_text, encoding="utf-8")

    entry = log_call(
        args=args,
        prompt=prompt,
        decision=decision,
        response_text=response_text,
        usage=usage,
        finish_reason=finish_reason,
        reasoning_chars=reasoning_chars,
        request_metadata=request_metadata,
        quality_status="pass",
        output_written=bool(args.out),
    )

    envelope: dict[str, Any] = {
        "decision": dataclasses.asdict(decision),
        "model": args.model,
        "usage": usage,
        "estimated_codex_tokens_saved": entry["estimated_codex_tokens_saved"],
        "log_file": args.log_file,
        "finish_reason": finish_reason,
        "reasoning_chars": reasoning_chars,
        "request": request_metadata,
        "response": response_text,
    }
    if args.raw:
        envelope["raw"] = json.loads(redact_secrets(json.dumps(result, ensure_ascii=False)))

    if args.json:
        print(json.dumps(envelope, ensure_ascii=False, indent=2))
    else:
        print_text_result(decision, response_text, entry)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
