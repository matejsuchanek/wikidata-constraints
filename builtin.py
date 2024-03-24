import re
from collections import defaultdict, OrderedDict
from decimal import Decimal
from typing import List, Optional, Set

import pywikibot
from pywikibot import WbGeoShape, WbMonolingualText, WbQuantity, WbTabularData, WbTime
from pywikibot.data.sparql import SparqlQuery
from pywikibot.exceptions import NoPageError
from pywikibot.page import Claim, Page, WikibaseEntity

from .base import ClaimConstraintType, Context, ItemConstraintType, Scope
from .utils import cmp_key, in_values, resolve_target_entity

__all__ = [
    'CommonsLink',
    'ConflictsWith',
    'DescriptionInLanguage',
    'Format',
    'Integer',
    'Inverse',
    'ItemRequires',
    'LabelInLanguage',
    'NoBounds',
    'NoneOf',
    'OneOf',
    'PropertyScope',
    'Qualifiers',
    'QuantityRange',
    'RequiredQualifiers',
    'SubjectType',
    'Symmetric',
    'TimeRange',
    'Units',
    'ValueRequires',
    'ValueType',
]

class PropertyScope(ClaimConstraintType):

    def __init__(self, values: Set[Scope]) -> None:
        self.values = values

    def violates(self, claim: Claim) -> bool:
        if claim.isQualifier:
            return Scope.QUALIFIER not in self.values
        elif claim.isReference:
            return Scope.REFERENCE not in self.values
        else:
            return Scope.MAIN not in self.values

    def score_for_update(self, context: Context):
        return 0


class SubjectType(ItemConstraintType):

    CACHE_LIMIT = 100

    def __init__(
        self,
        sparql: SparqlQuery,
        relation: List[str],
        classes: Set[str],
        cache: Optional[OrderedDict] = None
    ) -> None:
        self.sparql = sparql
        self.relation = relation
        self.classes = classes

        self.pattern = 'SELECT REDUCED ?base ?super { '
        self.pattern += 'VALUES ?base { %s } . '
        self.pattern += '?base wdt:P279+ ?super }'

        self._cache = cache or OrderedDict()

    def satisfied(self, revision: WikibaseEntity) -> bool:
        check = set()
        for prop in self.relation:
            for claim in revision.claims.get(prop, []):
                target = claim.getTarget()
                if target:
                    check.add(target.getID())

        if not check:
            return False

        if check & self.classes:
            return True

        cross = set()
        for base in check:
            for item in self.classes:
                cross.add((base, item))

        for key in cross:
            if self._cache.get(key):
                self._cache.move_to_end(key)
                return True

        query = self.pattern % ' '.join(f'wd:{x}' for x in check)
        result = self.sparql.select(query, full_data=True)

        by_base = defaultdict(set)
        for row in result:
            base = row['base'].getID()
            item = row['super'].getID()
            by_base[base].add(item)
            self._cache[base, item] = True

        out = bool(cross & self._cache.keys())
        for key in cross:
            base, item = key
            self._cache[key] = item in by_base[base]
            self._cache.move_to_end(key)

        while len(self._cache) > 1000:
            self._cache.popitem(last=False)

        return out


class ItemRequires(ItemConstraintType):

    def __init__(self, prop: str, values: Optional[Set[str]] = None) -> None:
        self.prop = prop
        self.values = values

    def satisfied(self, revision: WikibaseEntity) -> bool:
        if not revision.claims.get(self.prop):
            return False

        if not self.values:
            return True

        return any(in_values(claim, self.values)
                   for claim in revision.claims[self.prop])


class ConflictsWith(ItemConstraintType):

    def __init__(self, prop: str, values: Optional[Set[str]] = None) -> None:
        self.prop = prop
        self.values = values

    def satisfied(self, revision: WikibaseEntity) -> bool:
        if not revision.claims.get(self.prop):
            return True

        if not self.values:
            return False

        return not any(in_values(claim, self.values)
                       for claim in revision.claims[self.prop])


class LabelInLanguage(ItemConstraintType):

    def __init__(self, langs: Set[str]) -> None:
        self.langs = langs

    def satisfied(self, revision: WikibaseEntity) -> bool:
        return bool(revision.labels.keys() & self.langs)


class DescriptionInLanguage(ItemConstraintType):

    def __init__(self, langs: Set[str]) -> None:
        self.langs = langs

    def satisfied(self, revision: WikibaseEntity) -> bool:
        return bool(revision.descriptions.keys() & self.langs)


class OneOf(ClaimConstraintType):

    def __init__(self, values: Set[str]) -> None:
        self.values = values

    def violates(self, claim: Claim) -> bool:
        return not in_values(claim, self.values)


class NoneOf(ClaimConstraintType):

    def __init__(self, values: Set[str]) -> None:
        self.values = values

    def violates(self, claim: Claim) -> bool:
        return in_values(claim, self.values)


class Format(ClaimConstraintType):

    def __init__(self, regex: str) -> None:
        self.regex = re.compile(regex)

    def violates(self, claim: Claim) -> bool:
        target = claim.getTarget()
        if isinstance(target, WbMonolingualText):
            target = target.text
        elif isinstance(target, WbGeoShape | WbTabularData):
            target = target.page.title(with_ns=True)
        elif isinstance(target, Page):
            target = target.title(with_ns=True)
        return not self.regex.fullmatch(target or '')


class ValueRequires(ClaimConstraintType):

    def __init__(self, prop: str, values: Optional[Set[str]] = None) -> None:
        self.prop = prop
        self.values = values

    def violates(self, claim: Claim) -> bool:
        target = claim.getTarget()
        if not isinstance(target, WikibaseEntity):
            return False

        try:
            target = resolve_target_entity(target)
        except NoPageError:
            return True

        if not target.claims.get(self.prop):
            return True
        if self.values is None:
            return False

        return all(not in_values(cl, self.values)
                   for cl in target.claims[self.prop])


class ValueType(ClaimConstraintType):

    CACHE_LIMIT = 100

    def __init__(
        self,
        sparql: SparqlQuery,
        relation: List[str],
        classes: Set[str]
    ) -> None:
        self.sparql = sparql
        self.relation = relation

        self.pattern = 'ASK { VALUES ?class { '
        self.pattern += ' '.join(f'wd:{x}' for x in classes)
        self.pattern += ' } . wd:%s '
        if relation != ['P279']:
            self.pattern += 'wdt:P31'
            if 'P279' in relation:
                self.pattern += '?'
            self.pattern += '/'
        self.pattern += 'wdt:P279* ?class }'

        self._cache = OrderedDict()

    def violates(self, claim: Claim) -> bool:
        target = claim.getTarget()
        if not isinstance(target, WikibaseEntity):
            return False

        if target.getID() in self._cache:
            self._cache.move_to_end(target.getID())
            return self._cache[target.getID()]

        out = not self.sparql.ask(self.pattern % target.getID())
        self._cache[target.getID()] = out
        while len(self._cache) > self.CACHE_LIMIT:
            self._cache.popitem(last=False)
        return out


class Symmetric(ClaimConstraintType):

    def violates(self, claim: Claim) -> bool:
        target = claim.getTarget()
        if not isinstance(target, WikibaseEntity):
            return False

        try:
            target = resolve_target_entity(target)
        except NoPageError:
            return True

        return all(not cl.target_equals(claim.on_item)
                   for cl in target.claims.get(claim.getID(), []))

    @property
    def scopes(self):
        return {Scope.MAIN}


class Inverse(ClaimConstraintType):

    def __init__(self, prop: str) -> None:
        self.prop = prop

    def violates(self, claim: Claim) -> bool:
        target = claim.getTarget()
        if not isinstance(target, WikibaseEntity):
            return False

        try:
            target = resolve_target_entity(target)
        except NoPageError:
            return True

        return all(not cl.target_equals(claim.on_item)
                   for cl in target.claims.get(self.prop, []))

    @property
    def scopes(self):
        return {Scope.MAIN}


class CommonsLink(ClaimConstraintType):

    def __init__(self, file_repo, namespace) -> None:
        self.file_repo = file_repo
        self.namespace = namespace

    def violates(self, claim: Claim) -> bool:
        try:
            target = claim.getTarget()
        except ValueError:
            return True

        if isinstance(target, Page):
            return target.namespace() != self.namespace or not target.exists()

        try:
            page = Page(self.file_repo, target, ns=self.namespace)
        except ValueError:
            return True
        else:
            return not page.exists()


class Integer(ClaimConstraintType):

    def violates(self, claim: Claim) -> bool:
        target = claim.getTarget()
        return isinstance(target, WbQuantity) and '.' in str(target.amount)


class NoBounds(ClaimConstraintType):

    def violates(self, claim: Claim) -> bool:
        target = claim.getTarget()
        return isinstance(target, WbQuantity) and (
            target.upperBound is not None or target.lowerBound is not None)


class QuantityRange(ClaimConstraintType):

    def __init__(self, lower: Optional[Decimal], upper: Optional[Decimal]
                 ) -> None:
        self.lower = lower
        self.upper = upper

    def violates(self, claim: Claim) -> bool:
        target = claim.getTarget()
        if isinstance(target, WbQuantity):
            if self.lower is not None and target.amount < self.lower:
                return True
            if self.upper is not None and target.amount > self.upper:
                return True

        return False


class TimeRange(ClaimConstraintType):

    def __init__(self, lower: Optional[WbTime], upper: Optional[WbTime]) -> None:
        self.lower = lower
        self.upper = upper

    @staticmethod
    def _as_tuple(value: WbTime, prec: int):
        t = (value.year, value.month, value.day,
             value.hour, value.minute, value.second)
        return t[:max(1, prec - 8)]

    def violates(self, claim: Claim) -> bool:
        target = claim.getTarget()
        if isinstance(target, WbTime):
            norm = target.normalize()
            if self.lower:
                prec = min(self.lower.precision, norm.precision)
                if self._as_tuple(norm, prec) < self._as_tuple(self.lower, prec):
                    return True

            if self.upper:
                prec = min(self.upper.precision, norm.precision)
                if self._as_tuple(norm, prec) > self._as_tuple(self.upper, prec):
                    return True

        return False


class Units(ClaimConstraintType):

    def __init__(self, units: Set[str]) -> None:
        self.units = units

    def violates(self, claim: Claim) -> bool:
        target = claim.getTarget()
        if not isinstance(target, WbQuantity):
            return False

        unit = target.get_unit_item(claim.repo)
        if not unit:
            return 'novalue' not in self.units

        return unit.getID() not in self.units


class Qualifiers(ClaimConstraintType):

    def __init__(self, qualifiers: Set[str]) -> None:
        self.qualifiers = qualifiers

    def violates(self, claim: Claim) -> bool:
        return bool(set(claim.qualifiers) - self.qualifiers)

    def value_change_needed(self) -> bool:
        return False

    @property
    def scopes(self):
        return {Scope.MAIN}


class RequiredQualifiers(ClaimConstraintType):

    def __init__(self, qualifiers: Set[str]) -> None:
        self.qualifiers = qualifiers

    def violates(self, claim: Claim) -> bool:
        return bool(self.qualifiers - set(claim.qualifiers))

    def value_change_needed(self) -> bool:
        return False

    @property
    def scopes(self):
        return {Scope.MAIN}
