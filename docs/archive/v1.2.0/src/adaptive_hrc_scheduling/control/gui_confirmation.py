"""P05.1 confirmed payload adapter at the existing Session consumption boundary.

Only optimistic global read versions are bound here. All business parameters,
target revision, producer sequence and ID remain reviewed; Session.receive keeps
every admission and application check. This never retries a rejected request.
"""

from copy import deepcopy
from hashlib import sha256

from ..contracts.codec import require
from ..contracts.session import canonical, digest, loads, request_digest, validate_request
from .session import save_atomic, submit_file


def bind_pending(session):
    if session.spec["mode"] != "INTERACTIVE_PRODUCTION":
        return None
    directory = session.output / "p051-confirmations"
    (directory / "results").mkdir(parents=True, exist_ok=True)
    for path in (directory / "inbox").glob("*.json"):
        raw = path.read_bytes()
        try:
            preview = validate_request(loads(raw))
        except (ValueError, TypeError, KeyError) as error:
            seen = getattr(session, "_p051_invalid_confirmations", {})
            key = path.name, sha256(raw).hexdigest()
            if key not in seen:
                session.protocol_errors.append(
                    dict(
                        ingress="P051_CONFIRMATION",
                        file=path.name,
                        sha256=key[1],
                        reason=str(error),
                    )
                )
                seen[key] = True
                session._p051_invalid_confirmations = seen
            continue
        key = preview["request_id"]
        result_path = directory / "results" / (key + ".json")
        if result_path.exists():
            require(
                loads(result_path.read_bytes())["confirmation_sha256"] == digest(preview),
                "CONFIRMATION_MUTATED",
            )
            continue
        result = dict(request_id=key, confirmation_sha256=digest(preview), adapter="P051-CONFIRM-1")
        try:
            require(preview["request_digest"] == request_digest(preview), "CONFIRMATION_DIGEST")
            require(session.spec["mode"] == "INTERACTIVE_PRODUCTION", "CONFIRMATION_MODE")
            require(preview["source"] == "GUI", "CONFIRMATION_SOURCE")
            require(
                (preview["run_id"], preview["epoch"])
                == (session.spec["run_id"], session.spec["epoch"]),
                "CONFIRMATION_IDENTITY",
            )
            require(key not in session.requests, "QUERY_ORIGINAL_ID; DO_NOT_RESUBMIT")
            target = session.catalog["objects"].get(preview["target_id"], {})
            require(
                target.get("revision", 0) == preview["expected_target_revision"],
                "TARGET_CHANGED_SINCE_PREVIEW",
            )
            bound = deepcopy(preview)
            bound.update(
                expected_catalog_version=session.version,
                expected_state_revision=session.world.s.revision,
            )
            bound["request_digest"] = request_digest(bound)
            # Immutable reviewed fields are byte-equivalent, including target revision.
            require(
                canonical(bound["payload"]) == canonical(preview["payload"]),
                "CONFIRMATION_PAYLOAD_CHANGED",
            )
            validate_request(bound)
            transport = submit_file(session.output, bound)
            result.update(
                status="BOUND",
                request=bound,
                transport=str(transport),
                business_payload_unchanged=True,
            )
        except (ValueError, TypeError, KeyError) as error:
            result.update(status="REJECTED", reason=str(error))
        save_atomic(result_path, result)
        # Bind at most one per boundary: later confirmations see the next
        # committed catalog, rather than sharing an optimistic global version.
        return result
    return None
