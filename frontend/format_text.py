# format_text.py
"""
RESCU - CAP v1.2 formatting entrypoint.

This file:
- calls BLE getter for MCU info
- applies basic fallbacks
- builds CAP XML
- returns the fully validated XML string

Later: this logic moves into the App layer.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re
import xml.etree.ElementTree as ET

# ---- Defined by CAP Standard, Do Not Change ----
# won't use all but these are the options,
ALLOWED_STATUS = {"Actual", "Exercise", "System", "Test", "Draft"}
ALLOWED_MSGTYPE = {"Alert", "Update", "Cancel", "Ack", "Error"}
ALLOWED_SCOPE = {"Public", "Restricted", "Private"}

ALLOWED_CATEGORY = {
    "Geo", "Met", "Safety", "Security", "Rescue", "Fire",
    "Health", "Env", "Transport", "Infra", "CBRNE", "Other"
}
ALLOWED_URGENCY = {"Immediate", "Expected", "Future", "Past", "Unknown"}
ALLOWED_SEVERITY = {"Extreme", "Severe", "Moderate", "Minor", "Unknown"}
ALLOWED_CERTAINTY = {"Observed", "Likely", "Possible", "Unlikely", "Unknown"}

IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,256}$")
# -----------------------------------

def _require(cond: bool, msg: str) -> None:
    if not cond:
        raise ValueError(msg)


def _cap_ts(dt: datetime) -> str:
    _require(dt.tzinfo is not None and dt.tzinfo.utcoffset(dt) is not None,
             "CAP timestamps must be timezone-aware.")
    return dt.isoformat(timespec="seconds")


def _build_cap_xml(
    *,
    identifier: str,
    sender: str,
    sent_time: datetime,
    status: str,
    msg_type: str,
    scope: str,
    category: str,
    event: str,
    urgency: str,
    severity: str,
    certainty: str,
    headline: str,
    description: str,
    instruction: str | None,
    latitude: float,
    longitude: float,
    radius_km: float,
) -> str:
    # Minimal validation
    _require(identifier and IDENTIFIER_PATTERN.match(identifier), "Invalid identifier.")
    _require(sender, "Sender required.")
    _require(status in ALLOWED_STATUS, "Invalid status.")
    _require(msg_type in ALLOWED_MSGTYPE, "Invalid msgType.")
    _require(scope in ALLOWED_SCOPE, "Invalid scope.")
    _require(category in ALLOWED_CATEGORY, "Invalid category.")
    _require(urgency in ALLOWED_URGENCY, "Invalid urgency.")
    _require(severity in ALLOWED_SEVERITY, "Invalid severity.")
    _require(certainty in ALLOWED_CERTAINTY, "Invalid certainty.")
    _require(event, "Event required.")
    _require(headline, "Headline required.")
    _require(description, "Description required.")
    _require(-90 <= latitude <= 90, "Latitude out of range.")
    _require(-180 <= longitude <= 180, "Longitude out of range.")
    _require(radius_km > 0, "Radius must be positive.")

    alert = ET.Element("alert")

    ET.SubElement(alert, "identifier").text = identifier
    ET.SubElement(alert, "sender").text = sender
    ET.SubElement(alert, "sent").text = _cap_ts(sent_time)
    ET.SubElement(alert, "status").text = status
    ET.SubElement(alert, "msgType").text = msg_type
    ET.SubElement(alert, "scope").text = scope

    info = ET.SubElement(alert, "info")
    ET.SubElement(info, "language").text = "en-US"
    ET.SubElement(info, "category").text = category
    ET.SubElement(info, "event").text = event
    ET.SubElement(info, "urgency").text = urgency
    ET.SubElement(info, "severity").text = severity
    ET.SubElement(info, "certainty").text = certainty
    ET.SubElement(info, "headline").text = headline
    ET.SubElement(info, "description").text = description
    if instruction:
        ET.SubElement(info, "instruction").text = instruction

    area = ET.SubElement(info, "area")
    ET.SubElement(area, "areaDesc").text = "User Location"
    # CAP circle format: "lat,lon radius" (radius in km)
    ET.SubElement(area, "circle").text = f"{latitude},{longitude} {radius_km}"

    return ET.tostring(alert, encoding="utf-8", xml_declaration=True).decode("utf-8")


def get_cap_xml_for_current_alert(mcu_data: dict, location_data: dict) -> str:
    """
    Public entrypoint:
    - Receives MCU info pushed from the Browser/Parent Shell
    - Receives Geolocation info from Chrome API via Frontend
    - Returns final CAP XML string
    """
    # 1. Process Time: Use Browser-provided timestamp or current system time
    # This replaces the old mcu.mcu_sent_time logic
    sent_time = datetime.now(timezone.utc)

    # 2. Process Location: Use coordinates captured by Chrome Geolocation API
    # Passed from JS as location: {lat: x, lon: y, accuracy: z}
    latitude = location_data.get('lat', 40.4237)   # Defaults to West Lafayette/Purdue
    longitude = location_data.get('lon', -86.9212)
    radius_km = location_data.get('accuracy', 200) / 1000.0  # Convert meters to km

    # 3. Process MCU Data: Extract fields from the ESP32 JSON payload
    # Based on your hardware.ino: {"type":"FALL", "device_id":"RESCU_001", "fall_count":X, "timestamp":"..."}
    device_id = mcu_data.get('device_id', 'RESCU_DEVICE')
    event = "Fall Detected"
    fall_count = mcu_data.get('fall_count', 1)

    # 4. CAP fields configuration
    identifier = f"rescu-{sent_time.strftime('%Y%m%dT%H%M%SZ')}"
    sender = "rescu-app@example.com"

    status = "Actual"
    msg_type = "Alert"
    scope = "Private"

    category = "Safety"
    urgency = "Immediate"
    severity = "Severe"
    certainty = "Observed"

    headline = "RESCU Alert: Fall Detected"
    description = (
        f"A fall was detected by the RESCU wearable device. "
        f"Device ID: {device_id}. "
        f"This is fall event #{fall_count} recorded this session."
    )
    instruction = "Attempt to contact the user immediately. If no response, call emergency services."

    # 5. Call the internal builder to generate XML
    return _build_cap_xml(
        identifier=identifier,
        sender=sender,
        sent_time=sent_time,
        status=status,
        msg_type=msg_type,
        scope=scope,
        category=category,
        event=event,
        urgency=urgency,
        severity=severity,
        certainty=certainty,
        headline=headline,
        description=description,
        instruction=instruction,
        latitude=latitude,
        longitude=longitude,
        radius_km=radius_km,
    )


if __name__ == "__main__":
    print(get_cap_xml_for_current_alert({}, {}))