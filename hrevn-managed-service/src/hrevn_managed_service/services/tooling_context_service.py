from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from ..config import settings


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass
class GenerationContext:
    distribution_channel: str = "commercial-managed"
    delivery_mode: str = "api"
    license_id: str | None = None
    installation_id: str | None = None
    telemetry_enabled: bool = False
    generated_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        if self.distribution_channel in {"commercial-self-hosted", "commercial-managed"}:
            if not self.license_id:
                raise ValueError("license_id is required for commercial distribution channels")
            if not self.installation_id:
                raise ValueError("installation_id is required for commercial distribution channels")

        data: dict[str, Any] = {
            "generator_name": "hrevn-managed-service",
            "generator_version": settings.service_version,
            "distribution_channel": self.distribution_channel,
            "delivery_mode": self.delivery_mode,
            "generated_at": self.generated_at or _utc_now(),
            "telemetry_enabled": self.telemetry_enabled,
        }
        if self.license_id:
            data["license_id"] = self.license_id
        if self.installation_id:
            data["installation_id"] = self.installation_id
        return data


def build_generation_tooling_context(
    distribution_channel: str = "commercial-managed",
    delivery_mode: str = "api",
    license_id: str | None = None,
    installation_id: str | None = None,
    telemetry_enabled: bool = False,
    generated_at: str | None = None,
) -> dict[str, Any]:
    generation = GenerationContext(
        distribution_channel=distribution_channel,
        delivery_mode=delivery_mode,
        license_id=license_id,
        installation_id=installation_id,
        telemetry_enabled=telemetry_enabled,
        generated_at=generated_at,
    )
    return {"generation_context": generation.to_dict()}
