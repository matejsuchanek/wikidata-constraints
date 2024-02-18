from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Optional

from pywikibot.page import Claim, WikibaseEntity

Scope = Enum('Scope', ['MAIN', 'QUALIFIER', 'REFERENCE'])

class Status(IntEnum):
    SUGGESTION = 1
    REGULAR = 2
    MANDATORY = 4


@dataclass(eq=False, frozen=True)
class Context:

    old_rev: WikibaseEntity
    new_rev: WikibaseEntity
    old_claim: Optional[Claim]
    new_claim: Optional[Claim]

    @property
    def prop(self):
        if self.old_claim:
            return self.old_claim.getID()
        else:
            return self.new_claim.getID()


class ConstraintType:

    def score_for_addition(self, context: Context):
        raise NotImplementedError

    def score_for_removal(self, context: Context):
        raise NotImplementedError

    def score_for_update(self, context: Context):
        raise NotImplementedError

    @property
    def scopes(self):
        return set(Scope)

    def value_change_needed(self) -> bool:
        return False


class ClaimConstraintType(ConstraintType):

    def score_for_addition(self, context: Context):
        return int(self.violates(context.new_claim))

    def score_for_removal(self, context: Context):
        return -int(self.violates(context.old_claim))

    def score_for_update(self, context: Context):
        return int(self.violates(context.new_claim)) \
               - int(self.violates(context.old_claim))

    def violates(self, claim: Claim) -> bool:
        raise NotImplementedError

    def value_change_needed(self) -> bool:
        return True


class ItemConstraintType(ConstraintType):

    def score_for_addition(self, context: Context):
        return int(not self.satisfied(context.new_rev))

    def score_for_removal(self, context: Context):
        return -int(not self.satisfied(context.old_rev))

    def score_for_update(self, context: Context):
        return int(not self.satisfied(context.new_rev)) \
               - int(not self.satisfied(context.old_rev))

    def satisfied(self, revision: WikibaseEntity) -> bool:
        raise NotImplementedError

    @property
    def scopes(self):
        return {Scope.MAIN}
