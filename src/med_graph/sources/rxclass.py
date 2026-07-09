"""RxClass (NLM RxNav) adapter: which medications may treat a condition.

Yields Medication nodes keyed by RxNorm CUI and TREATS edges tagged with
rxclass provenance. Uses MED-RT 'may_treat' relations at ingredient level.
"""

import httpx
from pydantic import ValidationError

from med_graph.models import EdgeSource, Medication, TreatsEdge
from med_graph.sources.base import SourceBatch, SourceFetchError
from med_graph.sources.conditions import ConditionSpec
from med_graph.sources.http import HttpSource

RXCLASS_BASE_URL = "https://rxnav.nlm.nih.gov/REST/rxclass"


class RxClassSource(HttpSource):
    def fetch(self, spec: ConditionSpec) -> SourceBatch:
        members = [
            member
            for class_id in spec.rxclass_ids
            for member in self._class_members(class_id)
        ]
        try:
            by_rxcui = {
                member["minConcept"]["rxcui"]: member["minConcept"]
                for member in members
            }
            medications = tuple(
                Medication(
                    rxcui=concept["rxcui"],
                    name=concept["name"],
                    generic_name=concept["name"],
                )
                for concept in by_rxcui.values()
            )
        except (KeyError, TypeError, ValidationError) as error:
            raise SourceFetchError(
                f"unexpected rxclass response shape: {error}"
            ) from error
        treats = tuple(
            TreatsEdge(
                medication_rxcui=med.rxcui,
                condition_id=spec.condition.id,
                source=EdgeSource.RXCLASS,
            )
            for med in medications
        )
        return SourceBatch(medications=medications, treats=treats)

    def _class_members(self, class_id: str) -> list[dict]:
        try:
            response = self._http.get(
                f"{RXCLASS_BASE_URL}/classMembers.json",
                params={
                    "classId": class_id,
                    "relaSource": "MEDRT",
                    "rela": "may_treat",
                    "ttys": "IN",
                },
            )
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise SourceFetchError(
                f"rxclass request failed for class {class_id}: {error}"
            ) from error
        members = response.json().get("drugMemberGroup", {}).get("drugMember", [])
        # RxNav JSON is XML-derived: a one-element array can collapse to a bare object
        if isinstance(members, dict):
            return [members]
        return members
