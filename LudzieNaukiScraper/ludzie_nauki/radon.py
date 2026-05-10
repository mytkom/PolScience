from __future__ import annotations

import json
from typing import Any


def flatten_radon_institution(payload: dict[str, Any]) -> dict[str, Any]:
    """Map Radon portal-search JSON into flat columns for SQLite (plus raw JSON)."""
    obj = payload.get("object") or {}
    addr = (obj.get("addresses") or [{}])[0] if isinstance(obj.get("addresses"), list) and obj.get("addresses") else {}
    out: dict[str, Any] = {
        "id": payload.get("id") or obj.get("institutionUuid"),
        "name": payload.get("name") or obj.get("name") or "",
        "object_type": payload.get("objectType"),
        "country": obj.get("country") or addr.get("country"),
        "voivodeship": obj.get("voivodeship") or addr.get("voivodeship"),
        "city": obj.get("city") or addr.get("city"),
        "street": obj.get("street") or addr.get("street"),
        "postal_cd": obj.get("postalCd") or addr.get("postalCd"),
        "regon": obj.get("regon"),
        "nip": obj.get("nip"),
        "www": obj.get("www"),
        "email": obj.get("eMail"),
        "phone": obj.get("phone"),
        "status": obj.get("status"),
        "status_code": obj.get("statusCode"),
        "polon_object_id": obj.get("id"),
        "institution_uid": obj.get("institutionUid"),
        "manager_name": obj.get("managerName"),
        "manager_surname": obj.get("managerSurname"),
        "i_kind_name": obj.get("iKindName"),
        "u_type_name": obj.get("uTypeName"),
        "data_source": obj.get("dataSource"),
        "radon_raw_json": json.dumps(payload, ensure_ascii=False),
    }
    return out
