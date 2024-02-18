from typing import Any, Set, Tuple
from pywikibot.exceptions import IsRedirectPageError
from pywikibot.page import Claim, WikibaseEntity


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


def resolve_target_entity(target: WikibaseEntity) -> WikibaseEntity:
    while True:
        try:
            target.get()
            return target
        except IsRedirectPageError:
            target = target.getRedirectTarget()
