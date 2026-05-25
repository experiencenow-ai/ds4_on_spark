from __future__ import annotations
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

@dataclass(frozen=True)
class ModelProfile:
    profile_id: str
    model_id: str
    backend: str
    capability_classes: tuple[str, ...]
    supported_job_classes: tuple[str, ...]
    supports_chat: bool
    supports_completion: bool
    supports_thinking: bool
    production_eligible: bool
    default_for: tuple[str, ...]
    quality: dict[str, Any]
    performance: dict[str, Any]
    routing: dict[str, Any]

    @staticmethod
    def from_json(data: dict[str, Any]) -> "ModelProfile":
        required = ["profile_id", "model_id", "backend", "capability_classes", "supported_job_classes", "supports_chat", "supports_completion", "production_eligible"]
        missing = [key for key in required if key not in data]
        if missing:
            raise ValueError(f"model profile missing fields: {missing}")
        routing = dict(data.get("routing", {}))
        return ModelProfile(
            profile_id=str(data["profile_id"]),
            model_id=str(data["model_id"]),
            backend=str(data["backend"]),
            capability_classes=tuple(str(item) for item in data["capability_classes"]),
            supported_job_classes=tuple(str(item) for item in data["supported_job_classes"]),
            supports_chat=bool(data["supports_chat"]),
            supports_completion=bool(data["supports_completion"]),
            supports_thinking=bool(data.get("supports_thinking", False)),
            production_eligible=bool(data["production_eligible"]),
            default_for=tuple(routing.get("default_for", [])),
            quality=dict(data.get("quality", {})),
            performance=dict(data.get("performance", {})),
            routing=routing,
        )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "model_id": self.model_id,
            "backend": self.backend,
            "capability_classes": list(self.capability_classes),
            "supported_job_classes": list(self.supported_job_classes),
            "supports_chat": self.supports_chat,
            "supports_completion": self.supports_completion,
            "supports_thinking": self.supports_thinking,
            "production_eligible": self.production_eligible,
            "quality": self.quality,
            "performance": self.performance,
            "routing": self.routing,
        }

class ProfileRegistry:
    def __init__(self, profiles: list[ModelProfile]) -> None:
        if not profiles:
            raise ValueError("at least one model profile is required")
        self._profiles = profiles
        self._by_id = {profile.profile_id: profile for profile in profiles}
        if len(self._by_id) != len(profiles):
            raise ValueError("duplicate profile_id in registry")

    @staticmethod
    def load(profiles_dir: str | Path) -> "ProfileRegistry":
        profiles: list[ModelProfile] = []
        for path in sorted(Path(profiles_dir).glob("*.json")):
            with path.open("r", encoding="utf-8") as handle:
                profiles.append(ModelProfile.from_json(json.load(handle)))
        return ProfileRegistry(profiles)

    def all_profiles(self) -> list[ModelProfile]:
        return list(self._profiles)

    def get(self, profile_id: str) -> ModelProfile:
        try:
            return self._by_id[profile_id]
        except KeyError as exc:
            raise ValueError(f"unknown model profile: {profile_id}") from exc

    def resolve(self, *, capability: str | None, chat: bool, job_class: str, model_pin: dict[str, Any] | None = None) -> ModelProfile:
        if model_pin:
            profile_id = str(model_pin.get("profile_id", ""))
            if not profile_id:
                raise ValueError("model_pin.profile_id is required")
            profile = self.get(profile_id)
            self._check_profile_support(profile, chat=chat, job_class=job_class)
            return profile
        if not capability:
            raise ValueError("capability is required when model_pin is not provided")
        candidates = [
            profile for profile in self._profiles
            if profile.production_eligible
            and capability in profile.capability_classes
            and job_class in profile.supported_job_classes
            and ((chat and profile.supports_chat) or ((not chat) and profile.supports_completion))
        ]
        if not candidates:
            raise ValueError(f"no production profile supports capability={capability!r}, chat={chat}, job_class={job_class!r}")
        defaults = [profile for profile in candidates if capability in profile.default_for]
        return sorted(defaults or candidates, key=_routing_rank)[0]

    @staticmethod
    def _check_profile_support(profile: ModelProfile, *, chat: bool, job_class: str) -> None:
        if job_class not in profile.supported_job_classes:
            raise ValueError(f"profile {profile.profile_id} does not support job_class={job_class}")
        if chat and not profile.supports_chat:
            raise ValueError(f"profile {profile.profile_id} does not support chat mode")
        if not chat and not profile.supports_completion:
            raise ValueError(f"profile {profile.profile_id} does not support completion mode")

def _routing_rank(profile: ModelProfile) -> tuple[int, float, str]:
    rank = int(profile.routing.get("rank", 1000))
    latency = float(profile.performance.get("p95_latency_s", profile.performance.get("latency_rank", 1_000_000.0)))
    return (rank, latency, profile.profile_id)
