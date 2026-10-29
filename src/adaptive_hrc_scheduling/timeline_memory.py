"""Equal adjacent event storage; never a substitute for decoding or auditing.

JSON inputs are private consumer-owned trees and remain read-only after sharing.
Native inputs are immutable domain records produced by the original decoder.
Every scalar comparison preserves its type and the sign of floating-point zero.
"""

from dataclasses import fields, is_dataclass, replace


def share_json(current, previous):
    if type(current) is not type(previous):
        return current
    if type(current) is dict:
        for key, value in current.items():
            if key in previous:
                current[key] = share_json(value, previous[key])
        if current.keys() == previous.keys() and all(
            current[key] is previous[key] for key in current
        ):
            return previous
    elif type(current) is list:
        for index in range(min(len(current), len(previous))):
            current[index] = share_json(current[index], previous[index])
        if len(current) == len(previous) and all(a is b for a, b in zip(current, previous)):
            return previous
    elif type(current) is float:
        if current == previous and current.hex() == previous.hex():
            return previous
    elif type(current) in (str, int, bool, type(None)) and current == previous:
        return previous
    return current


def share_record(value, previous):
    if type(value) is not type(previous):
        return value
    if type(value) is tuple:
        parts = tuple(
            share_record(v, previous[i]) if i < len(previous) else v for i, v in enumerate(value)
        )
        if len(parts) == len(previous) and all(a is b for a, b in zip(parts, previous)):
            return previous
        return parts
    if is_dataclass(value) and type(value).__dataclass_params__.frozen:
        parts = {
            f.name: share_record(getattr(value, f.name), getattr(previous, f.name))
            for f in fields(value)
        }
        if all(v is getattr(previous, k) for k, v in parts.items()):
            return previous
        return replace(value, **parts)
    if type(value) in (str, int, bool, type(None)) and value == previous:
        return previous
    if type(value) is float and value.hex() == previous.hex():
        return previous
    return value
