from collections import OrderedDict
from typing import Any, Dict, List, Set, Tuple

from pywikibot.exceptions import IsRedirectPageError
from pywikibot.page import Claim, WikibaseEntity


class LRUCache:

    def __init__(self, limit: int) -> None:
        self._cache = OrderedDict()
        self.limit = limit

    def keys(self):
        return self._cache.keys()

    def has(self, key) -> bool:
        return key in self._cache

    def get(self, key) -> Any:
        val = self._cache[key]
        self._cache.move_to_end(key)
        return val

    def set(self, key, val: Any) -> None:
        self._cache[key] = val
        self._cache.move_to_end(key)
        self._ensure_limit()

    def _ensure_limit(self) -> None:
        while len(self._cache) > self.limit:
            self._cache.popitem(last=False)


def cmp_key(claim: Claim) -> Tuple[str, Any]:
    return (claim.snaktype, claim.target)


def in_values(claim: Claim, values: Set[str]) -> bool:
    if claim.getSnakType() != 'value':
        return claim.getSnakType() in values
    else:
        return claim.getTarget().getID() in values


def item_has_claim(item: WikibaseEntity, claim: Claim, **kwargs) -> bool:
    haystack = item.claims.get(claim.getID())
    if haystack:
        return any(claim.same_as(cl, **kwargs) for cl in haystack)
    else:
        return False


def get_best_claims(mapping, id_: str):
    best = []
    rank = 'normal'
    for claim in mapping.get(id_, []):
        if claim.rank == 'preferred':
            rank = 'preferred'
            best = []
        if claim.rank == rank:
            best.append(claim)
    return best


def resolve_target_entity(target: WikibaseEntity) -> WikibaseEntity:
    while True:
        try:
            target.get()
            return target
        except IsRedirectPageError:
            target = target.getRedirectTarget()


def index_by_id(claims: List[Claim]) -> Dict[str, Claim]:
    return {claim.snak: claim for claim in claims}


def iter_claim_differences(old: WikibaseEntity, new: WikibaseEntity):
    for prop in old.claims.keys() | new.claims.keys():
        old_index = index_by_id(old.claims.get(prop, []))
        new_index = index_by_id(new.claims.get(prop, []))
        for key in old_index.keys() | new_index.keys():
            old_claim = old_index.get(key)
            new_claim = new_index.get(key)
            if old_claim is None or new_claim is None:
                yield (old_claim, new_claim)
            else:
                same = new_claim.same_as(
                    old_claim,
                    # TODO
                    ignore_rank=True,
                    ignore_quals=False,
                    ignore_refs=False)
                if not same:
                    yield (old_claim, new_claim)


def claim_differences(old: WikibaseEntity, new: WikibaseEntity):
    return list(iter_claim_differences(old, new))
