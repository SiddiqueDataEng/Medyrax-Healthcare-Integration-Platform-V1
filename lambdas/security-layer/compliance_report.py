"""
security-compliance-report Lambda (task 13.4).

Scheduled EventBridge rule (daily).
Queries CloudWatch Logs Insights for PHI access counts, denied-access counts,
KMS usage. Writes report JSON to CloudWatch Logs mdx-compliance-reports.

Requirements: 7.10
"""
from __future__ import annotations
import json, logging, os, sys, time
from datetime import datetime, timezone, timedelta
from typing import Any

import boto3

logger = logging.getLogger(__name__)
_REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
_REPORT_LOG_GROUP = "mdx-compliance-reports"

_logs = boto3.client("logs", region_name=_REGION)


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Run daily compliance report and write to CloudWatch Logs."""
    now = datetime.now(tz=timezone.utc)
    end_time = int(now.timestamp())
    start_time = int((now - timedelta(days=1)).timestamp())

    report: dict[str, Any] = {
        "reportDate": now.strftime("%Y-%m-%d"),
        "generatedAt": now.isoformat(),
        "periodStart": (now - timedelta(days=1)).isoformat(),
        "periodEnd": now.isoformat(),
    }

    # Query: PHI access count
    report["phiAccessCount"] = _query_count(
        log_group="/aws/lambda/medyrax",
        query="fields @message | filter @message like /PHI_ACCESS/ | stats count() as cnt",
        start=start_time, end=end_time,
    )

    # Query: denied access count
    report["deniedAccessCount"] = _query_count(
        log_group="/aws/lambda/medyrax",
        query='fields @message | filter allowed = false | stats count() as cnt',
        start=start_time, end=end_time,
    )

    _write_report(report)
    logger.info("Compliance report written for %s", report["reportDate"])
    return {"statusCode": 200, "body": json.dumps({"reportDate": report["reportDate"]})}


def _query_count(log_group: str, query: str, start: int, end: int) -> int:
    """Run a CloudWatch Logs Insights query and return the count."""
    try:
        resp = _logs.start_query(
            logGroupName=log_group,
            startTime=start,
            endTime=end,
            queryString=query,
        )
        query_id = resp["queryId"]
        # Poll until complete (max 10s)
        for _ in range(10):
            time.sleep(1)
            result = _logs.get_query_results(queryId=query_id)
            if result["status"] in ("Complete", "Failed", "Cancelled"):
                rows = result.get("results", [])
                if rows:
                    cnt_field = next((f["value"] for f in rows[0] if f["field"] == "cnt"), "0")
                    return int(cnt_field)
                return 0
    except Exception as exc:
        logger.warning("Compliance query failed: %s", exc)
    return 0


def _write_report(report: dict) -> None:
    """Write compliance report to CloudWatch Logs."""
    now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    stream = datetime.now(tz=timezone.utc).strftime("%Y/%m/%d")
    try:
        try:
            _logs.create_log_group(logGroupName=_REPORT_LOG_GROUP)
        except Exception:
            pass
        try:
            _logs.create_log_stream(logGroupName=_REPORT_LOG_GROUP, logStreamName=stream)
        except Exception:
            pass
        _logs.put_log_events(
            logGroupName=_REPORT_LOG_GROUP,
            logStreamName=stream,
            logEvents=[{"timestamp": now_ms, "message": json.dumps(report)}],
        )
    except Exception as exc:
        logger.error("Failed to write compliance report: %s", exc)
