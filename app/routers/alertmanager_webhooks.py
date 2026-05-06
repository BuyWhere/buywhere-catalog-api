"""Alertmanager and Uptime Robot webhook handlers.

Accepts webhook payloads from:
- Uptime Robot (POST /webhooks/uptime-robot)
- Alertmanager (POST /webhooks/alertmanager)

For DOWN events, creates a Paperclip issue and/or sends email notifications.
"""
import json
import os
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.logging_centralized import get_logger

logger = get_logger("alertmanager-webhooks")

router = APIRouter()

PAPERCLIP_API_URL = os.environ.get("PAPERCLIP_API_URL", "")
PAPERCLIP_API_KEY = os.environ.get("PAPERCLIP_API_KEY", "")
PAPERCLIP_COMPANY_ID = os.environ.get("PAPERCLIP_COMPANY_ID", "")
UPTIME_ISSUE_TRACKER_ID = os.environ.get("UPTIME_ISSUE_TRACKER_ID", "BUY-10100")


class UptimeRobotPayload(BaseModel):
    monitorID: str
    monitorFriendlyName: str = ""
    monitorURL: str = ""
    monitorType: str = ""
    alertType: str = ""
    alertTypeFriendlyName: str = ""
    alertDetails: str = ""
    alertDuration: str = ""
    monitorAlertContacts: Optional[str] = None
    monitorStatusCode: str = ""
    monitorStatusDetails: str = ""

    class Config:
        extra = "allow"


ALERT_TYPE_DOWN = {"1", "1-Down"}
ALERT_TYPE_UP = {"2", "2-Up"}
ALERT_TYPE_SSL = {"3", "3-SSL expiry"}


def _paperclip_available() -> bool:
    return bool(PAPERCLIP_API_URL and PAPERCLIP_API_KEY and PAPERCLIP_COMPANY_ID)


async def _post_paperclip_comment(issue_identifier: str, body: str) -> bool:
    if not _paperclip_available():
        logger.warning("Paperclip not configured — cannot post comment")
        return False

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{PAPERCLIP_API_URL}/api/issues/{issue_identifier}/comments",
                headers={
                    "Authorization": f"Bearer {PAPERCLIP_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={"body": body},
            )
            if resp.status_code in (200, 201):
                logger.info(f"Posted Paperclip comment to {issue_identifier}")
                return True
            else:
                logger.error(
                    f"Failed to post Paperclip comment: {resp.status_code} {resp.text[:500]}"
                )
                return False
    except Exception as e:
        logger.error(f"Paperclip API call failed: {e}")
        return False


async def _create_paperclip_issue(title: str, description: str, priority: str = "high") -> Optional[str]:
    if not _paperclip_available():
        logger.warning("Paperclip not configured — cannot create issue")
        return None

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{PAPERCLIP_API_URL}/api/companies/{PAPERCLIP_COMPANY_ID}/issues",
                headers={
                    "Authorization": f"Bearer {PAPERCLIP_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "title": title,
                    "description": description,
                    "status": "todo",
                    "priority": priority,
                    "goalId": "2c19e8cc-3e32-4144-8fcb-c4f206cb9fa4",
                },
            )
            if resp.status_code in (200, 201):
                data = resp.json()
                issue_id = data.get("identifier") or data.get("id")
                logger.info(f"Created Paperclip issue {issue_id}: {title}")
                return issue_id
            else:
                logger.error(
                    f"Failed to create Paperclip issue: {resp.status_code} {resp.text[:500]}"
                )
                return None
    except Exception as e:
        logger.error(f"Paperclip API call failed: {e}")
        return None


@router.post("/webhooks/uptime-robot")
async def uptime_robot_webhook(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "INVALID_JSON",
                    "message": "Request body must be valid JSON",
                    "doc_url": "https://buywhere.ai/docs/errors#INVALID_JSON",
                }
            },
        )

    try:
        payload = UptimeRobotPayload.model_validate(body)
    except Exception as e:
        field_errors = []
        if hasattr(e, "errors"):
            for err in e.errors():
                loc = ".".join(str(x) for x in err.get("loc", []))
                msg = err.get("msg", "")
                if "missing" in err.get("type", ""):
                    field_errors.append(f"Required parameter '{loc}' is missing")
                    return JSONResponse(
                        status_code=400,
                        content={
                            "error": {
                                "code": "MISSING_REQUIRED_FIELD",
                                "message": f"{loc} is required",
                                "doc_url": "https://buywhere.ai/docs/errors#MISSING_REQUIRED_FIELD",
                            }
                        },
                    )
        return JSONResponse(
            status_code=400,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": str(e),
                    "doc_url": "https://buywhere.ai/docs/errors#VALIDATION_ERROR",
                }
            },
        )

    monitor_name = payload.monitorFriendlyName or payload.monitorID
    alert_type = payload.alertTypeFriendlyName or payload.alertType
    details = payload.alertDetails or f"Status {payload.monitorStatusCode}"

    logger.info(
        f"Uptime Robot alert: {monitor_name} [{payload.monitorURL}] = {alert_type} — {details}",
        extra={
            "monitor_id": payload.monitorID,
            "monitor_name": monitor_name,
            "monitor_url": payload.monitorURL,
            "alert_type": alert_type,
            "alert_details": details,
            "status_code": payload.monitorStatusCode,
        },
    )

    # Handle DOWN alerts
    if payload.alertType in ALERT_TYPE_DOWN or alert_type.lower() == "down":
        logger.error(
            f"MONITOR DOWN: {monitor_name} ({payload.monitorURL}) — {details}"
        )

        issue_body = (
            f"## Uptime Robot Alert: {monitor_name} is DOWN\n\n"
            f"- **Monitor:** {monitor_name}\n"
            f"- **URL:** {payload.monitorURL}\n"
            f"- **Status:** {details}\n"
            f"- **HTTP Code:** {payload.monitorStatusCode}\n"
            f"- **Time:** {datetime.now(timezone.utc).isoformat()}\n"
            f"- **Monitor ID:** {payload.monitorID}\n"
        )

        # Update the tracker issue first
        tracker_comment = (
            f"## Alert: {monitor_name} is DOWN\n\n"
            f"**Status:** {details} (HTTP {payload.monitorStatusCode})\n"
            f"**URL:** {payload.monitorURL}\n"
            f"**Time:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        )
        await _post_paperclip_comment(UPTIME_ISSUE_TRACKER_ID, tracker_comment)

        # Create a dedicated issue for new DOWN events if not the tracker itself
        if payload.monitorID != UPTIME_ISSUE_TRACKER_ID:
            await _create_paperclip_issue(
                title=f"DOWN: {monitor_name}",
                description=issue_body,
                priority="critical",
            )

    # Handle UP alerts (recovery)
    elif payload.alertType in ALERT_TYPE_UP or alert_type.lower() == "up":
        logger.info(
            f"MONITOR RECOVERED: {monitor_name} ({payload.monitorURL})"
        )
        recovery_comment = (
            f"## Recovered: {monitor_name} is UP\n\n"
            f"**Status:** {details}\n"
            f"**URL:** {payload.monitorURL}\n"
            f"**Time:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        )
        await _post_paperclip_comment(UPTIME_ISSUE_TRACKER_ID, recovery_comment)

    return JSONResponse(content={"status": "ok"})


@router.post("/webhooks/alertmanager")
async def alertmanager_webhook(request: Request):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "INVALID_JSON", "message": "Body must be valid JSON"}},
        )

    logger.info(f"Alertmanager webhook received: {json.dumps(body, default=str)[:2000]}")

    alerts = body.get("alerts", [])
    for alert in alerts:
        status = alert.get("status", "unknown")
        labels = alert.get("labels", {})
        alertname = labels.get("alertname", "unknown")
        severity = labels.get("severity", "warning")
        annotations = alert.get("annotations", {})

        logger.info(
            f"Alertmanager: {alertname} [{status}] severity={severity}",
            extra={"alert": alertname, "status": status, "severity": severity},
        )

        if status == "firing":
            issue_body = (
                f"## Alertmanager: {alertname} is FIRING\n\n"
                f"- **Severity:** {severity}\n"
                f"- **Summary:** {annotations.get('summary', 'N/A')}\n"
                f"- **Description:** {annotations.get('description', 'N/A')}\n"
                f"- **Time:** {datetime.now(timezone.utc).isoformat()}\n"
                f"- **Labels:** {json.dumps(labels)}\n"
            )
            await _post_paperclip_comment(
                UPTIME_ISSUE_TRACKER_ID,
                f"## Alertmanager FIRING: {alertname}\n\n"
                f"**Severity:** {severity}\n"
                f"**Summary:** {annotations.get('summary', 'N/A')}\n"
                f"**Time:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}\n",
            )

    return JSONResponse(content={"status": "ok"})


@router.get("/webhooks/uptime-robot")
async def uptime_robot_webhook_diagnostic():
    return JSONResponse(content={"status": "ok", "mode": "diagnostic"})
