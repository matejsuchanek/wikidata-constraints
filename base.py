from dataclasses import dataclass
from enum import Enum, IntEnum
from typing import Optional, Union

from pywikibot.page import Claim, WikibaseEntity


Scope = Enum('Scope', ['MAIN', 'QUALIFIER', 'REFERENCE'])

class Status(IntEnum):
    SUGGESTION = 1
    REGULAR = 2
    MANDATORY = 4


@dataclass(eq=False, frozen=True)
class VersionContext:

    rev: WikibaseEntity
    parent: Union[WikibaseEntity, Claim, None] = None
    claim: Optional[Claim] = None

    @property
    def prop(self):
        return self.claim.getID()

    @property
    def sibling_mapping(self):
        if isinstance(self.parent, Claim):
            return self.parent.qualifiers
        else:
            return self.parent.claims

    @classmethod
    def new_for_claim(cls, rev: WikibaseEntity, claim: Claim):
        return cls(rev, rev, claim)

    def for_qualifier(self, qual: Optional[Claim]):
        assert self.claim is not None
        return VersionContext(self.rev, self.claim, qual)


@dataclass(eq=False, frozen=True)
class Context:

    old: VersionContext
    new: VersionContext

    @property
    def old_rev(self):
        return self.old.rev

    @property
    def new_rev(self):
        return self.new.rev

    @property
    def old_claim(self):
        return self.old.claim

    @property
    def new_claim(self):
        return self.new.claim

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
        return int(self.violates_ctx(context.new))

    def score_for_removal(self, context: Context):
        return -int(self.violates_ctx(context.old))

    def score_for_update(self, context: Context):
        return int(self.violates_ctx(context.new)) \
               - int(self.violates_ctx(context.old))

    def violates_ctx(self, ctx: VersionContext) -> bool:
        return self.violates(ctx.claim)

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
