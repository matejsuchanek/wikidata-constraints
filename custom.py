from pywikibot import WbQuantity
from pywikibot.exceptions import IsRedirectPageError, NoPageError
from pywikibot.page import Claim, WikibaseEntity

from .base import ClaimConstraintType, Context, Scope
from .builtin import PropertyScope
from .utils import cmp_key, resolve_target_entity

__all__ = [
    'HasValidReference',
    'LargeChange',
    'NoLinksToDisambiguation',
    'NoSelfLink',
    'SandboxProperty',
    'ValueExists',
]

class HasValidReference(ClaimConstraintType):

    def __init__(self, store) -> None:
        self.store = store

    def _is_valid_reference(self, reference) -> bool:
        for prop in reference:
            if prop not in {'P143', 'P813', 'P887', 'P3452', 'P4656'} and all(
                Scope.REFERENCE in scope_constr.type.values
                for scope_constr
                in self.store.get_constraints(prop, type=PropertyScope)
            ):
                return True

        return False

    def _count_valid_references(self, claim: Claim) -> int:
        return sum(int(self._is_valid_reference(ref)) for ref in claim.sources)

    def score_for_addition(self, context: Context):
        return -self._count_valid_references(context.new_claim)

    def score_for_removal(self, context: Context):
        return self._count_valid_references(context.old_claim)

    def score_for_update(self, context: Context):
        old_claim = context.old_claim
        new_claim = context.new_claim
        if cmp_key(old_claim) != cmp_key(new_claim) \
           and old_claim.sources == new_claim.sources:
            return self._count_valid_references(old_claim)

        return self._count_valid_references(old_claim) \
               - self._count_valid_references(new_claim)

    def violates(self, claim: Claim) -> bool:
        return False

    @property
    def scopes(self):
        return {Scope.MAIN}


class ValueExists(ClaimConstraintType):

    def violates(self, claim: Claim) -> bool:
        target = claim.getTarget()
        return isinstance(target, WikibaseEntity) and not target.exists()


class NoLinksToDisambiguation(ClaimConstraintType):

    def violates(self, claim: Claim) -> bool:
        target = claim.getTarget()
        if not isinstance(target, WikibaseEntity):
            return False

        try:
            target = resolve_target_entity(target)
        except NoPageError:
            return False

        return any(cl.target_equals('Q4167410')
                   for cl in target.claims.get('P31', []))


class NoSelfLink(ClaimConstraintType):

    def violates(self, claim: Claim) -> bool:
        target = claim.getTarget()
        return isinstance(target, WikibaseEntity) and target == claim.on_item


class SandboxProperty(ClaimConstraintType):

    def violates(self, claim: Claim) -> bool:
        return True


class LargeChange(ClaimConstraintType):

    def score_for_addition(self, context: Context):
        return 0

    def score_for_removal(self, context: Context):
        return 0

    def score_for_update(self, context: Context):
        old = context.old_claim.getTarget()
        new = context.new_claim.getTarget()
        if isinstance(old, WbQuantity) and isinstance(new, WbQuantity) \
           and not old.amount.is_zero() and not new.amount.is_zero():
            # TODO: find workaround for zeros
            abs_ = lambda x: x.copy_sign(1)
            magn = abs_(old.amount).log10() - abs_(new.amount).log10()
            return abs_(magn).to_integral_value()

        return 0

    def violates(self, claim: Claim) -> bool:
        return False
