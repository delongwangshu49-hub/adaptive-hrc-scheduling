"""P05.3 declared initial-fatigue inputs, separate from frozen S18 inputs.

The canonical S18 physical model is checked with its original people. Only F0
may differ in this family; execution uses the actual declared people and the
unchanged fatigue, duration, qualification and admission equations.
"""

from dataclasses import replace

from .contracts.codec import as_data, require
from .control.online import OnlinePolicy

VERSION = "P053-PROD-1.0"
SPECIFICATION = "P053-PROD-SPEC-1.0"


class ResearchOnlinePolicy(OnlinePolicy):
    """Bound search counts while retaining complete candidates and the shield."""

    def _search_allowed(self, trigger):
        cap = self.limits.max_search_calls
        if trigger in ("FEEDBACK", "CATALOG_CHANGED") and self.budget_account:
            cap += self.budget_account.profile.change_reserve_calls
        return self.calls < cap and super()._search_allowed(trigger)


def configuration(base, *, initial_f=None):
    from .contracts.production import validate

    require(base.schema_version == "S18-PROD-2.0", "RESEARCH_INITIAL_BASE_FAMILY")
    validate(base)
    people = base.people
    if initial_f is not None:
        people = tuple(replace(p, initial_f=initial_f) for p in people)
    result = replace(
        base,
        schema_version=VERSION,
        specification=SPECIFICATION,
        id="P053-RESEARCH-r1:" + base.id,
        people=people,
    )
    return validate(result)


def validate_configuration(config):
    from .contracts.codec import decode
    from .domain.building import Person
    from .dynamic_orders import templates
    from .production_admission import validate_admission

    require(config.specification == SPECIFICATION, "RESEARCH_INITIAL_SPECIFICATION")
    require(config.id.startswith("P053-RESEARCH-r1:"), "RESEARCH_INITIAL_IDENTITY")
    baseline = tuple(decode(Person, p) for p in templates()["SR-W1"]["people"])
    require(len(config.people) == len(baseline), "RESEARCH_INITIAL_PEOPLE")
    require(
        all(
            as_data(replace(p, initial_f=b.initial_f)) == as_data(b)
            and p.initial_f in (b.initial_f, 0.60)
            and p.initial_f <= config.cap
            for p, b in zip(config.people, baseline)
        ),
        "RESEARCH_INITIAL_PARAMETER_DRIFT",
    )
    canonical = replace(
        config,
        schema_version="S18-PROD-2.0",
        specification="S18-PROD-SPEC-2.0",
        people=baseline,
    )
    validate_admission(canonical)
