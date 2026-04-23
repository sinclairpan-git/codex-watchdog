from __future__ import annotations

from dataclasses import dataclass

from watchdog.contracts.session_spine.enums import ActionCode


@dataclass(frozen=True, slots=True)
class CanonicalActionRegistration:
    action_ref: str
    action_code: ActionCode
    argument_keys: tuple[str, ...] = ()


_CANONICAL_ACTION_REGISTRY: dict[str, CanonicalActionRegistration] = {
    "continue_session": CanonicalActionRegistration(
        action_ref="continue_session",
        action_code=ActionCode.CONTINUE_SESSION,
    ),
    "request_recovery": CanonicalActionRegistration(
        action_ref="request_recovery",
        action_code=ActionCode.REQUEST_RECOVERY,
    ),
    "execute_recovery": CanonicalActionRegistration(
        action_ref="execute_recovery",
        action_code=ActionCode.EXECUTE_RECOVERY,
    ),
    "post_operator_guidance": CanonicalActionRegistration(
        action_ref="post_operator_guidance",
        action_code=ActionCode.POST_OPERATOR_GUIDANCE,
        argument_keys=("message", "reason_code", "stuck_level"),
    ),
}


def list_registered_actions() -> tuple[CanonicalActionRegistration, ...]:
    return tuple(_CANONICAL_ACTION_REGISTRY.values())


def get_registered_action(action_ref: str) -> CanonicalActionRegistration:
    try:
        return _CANONICAL_ACTION_REGISTRY[action_ref]
    except KeyError as exc:
        raise KeyError(f"unsupported canonical action: {action_ref}") from exc
