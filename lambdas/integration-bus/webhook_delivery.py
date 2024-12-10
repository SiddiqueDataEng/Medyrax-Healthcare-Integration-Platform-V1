"""
integration-bus-webhook Lambda (task 12.4).

Polls SQS mdx-{orgId}-webhook-queue.
HTTP POST to org's configured webhook URL with exponential backoff:
1s, 2s, 4s, 8s, 16s (5 attempts). Logs final failure to CloudWatch.

Requirements: 5.7
"""
from __future__ import annotations
import json, logging, os, sys, time, urllib.request, urllib.error, urllib.parse
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

_BACKOFF = [1.0, 2.0, 4.0, 8.0, 16.0]
_TIMEOUT_S = 10
_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Process SQS webhook queue messages."""
    failures = []
    for record in event.get("Records", []):
        try:
            _process(record)
        except Exception as exc:
            logger.error("Webhook delivery failed: %s", exc)
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}


def _process(record: dict) -> None:
    body = json.loads(record.get("body", "{}"))
    org_id = body.get("orgId", "")
    payload = body.get("payload", {})

    # Get webhook URL from tenant config
    from mdx_common.tenant_config_service import get_tenant_config  # type: ignore
    config = get_tenant_config(org_id)
    webhook_url = config.webhook_url

    if not webhook_url:
        logger.info("No webhook URL configured for org=%s, skipping", org_id)
        return

    _deliver_with_retry(webhook_url, payload, org_id)


def _deliver_with_retry(url: str, payload: dict, org_id: str) -> None:
    """POST payload to url with exponential backoff up to 5 attempts."""
    data = json.dumps(payload).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "X-Medyrax-OrgId": org_id,
        "User-Agent": "Medyrax-Webhook/1.0",
    }

    last_exc: Exception | None = None
    for attempt, backoff in enumerate(_BACKOFF, start=1):
        try:
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                status = resp.status
                if status < 300:
                    logger.info("Webhook delivered to org=%s attempt=%d status=%d",
                                org_id, attempt, status)
                    return
                logger.warning("Webhook non-2xx response: org=%s status=%d attempt=%d",
                               org_id, status, attempt)
        except urllib.error.HTTPError as exc:
            logger.warning("Webhook HTTP error: org=%s attempt=%d error=%s", org_id, attempt, exc)
            last_exc = exc
        except Exception as exc:
            logger.warning("Webhook error: org=%s attempt=%d error=%s", org_id, attempt, exc)
            last_exc = exc

        if attempt < len(_BACKOFF):
            time.sleep(backoff)

    logger.error(
        "Webhook delivery exhausted all %d retries for org=%s url=%s: %s",
        len(_BACKOFF), org_id, url, last_exc,
    )
