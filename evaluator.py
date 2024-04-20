import re
from collections import defaultdict, OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import pywikibot
from pywikibot.data.sparql import SparqlQuery
from pywikibot.exceptions import ServerError
from pywikibot.page import Claim, PropertyPage, WikibaseEntity
from requests.exceptions import ConnectionError

from .base import ClaimConstraintType, ConstraintType, Context, Scope, Status
from .builtin import *
from .custom import *
from .utils import cmp_key, item_has_claim
from .performance import performance_stats


@dataclass(eq=False, frozen=False)
class Constraint:

    prop: str
    claim_id: Optional[str]
    type: ConstraintType
    status: Status
    scopes: Set[Scope]

    def __str__(self) -> str:
        return f'{self.prop}.{self.type.__class__.__name__}'

    def as_link(self) -> str:
        if self.claim_id:
            return f'[[Property:{self.prop}#{self.claim_id}|{str(self)}]]'
        else:
            return str(self)

    @performance_stats
    def handle_addition(self, context: Context, result: 'Result') -> None:
        score = self.type.score_for_addition(context)
        if self.status == Status.SUGGESTION:
            score = min(0, score)
        result.add(self, score)

    @performance_stats
    def handle_removal(self, context: Context, result: 'Result') -> None:
        score = self.type.score_for_removal(context)
        result.add(self, score)

    @performance_stats
    def handle_update(self, context: Context, result: 'Result') -> None:
        score = self.type.score_for_update(context) * self.status
        result.add(self, score)

    def may_check(self, scope: Scope) -> bool:
        return scope in self.scopes and scope in self.type.scopes


class Result:

    def __init__(self) -> None:
        self.score = 0
        self.evaluated = []

    def add(self, constraint: Constraint, score: int) -> None:
        self.score += score
        self.evaluated.append((constraint, score))

    def get_violated_constraints(self) -> List[Constraint]:
        return [constraint for constraint, score in self.evaluated if score > 0]

    def get_fixed_constraints(self) -> List[Constraint]:
        return [constraint for constraint, score in self.evaluated if score < 0]


class ConstraintsStore:

    def __init__(self, repo, sparql: SparqlQuery) -> None:
        self.repo = repo
        self.sparql = sparql
        self._cache: Dict[str, List[Constraint]] = {}
        self._caches = defaultdict(OrderedDict)

    def _get_input(self, prop) -> Tuple[str, PropertyPage]:
        if isinstance(prop, str):
            return prop, PropertyPage(self.repo, prop)
        else:
            return prop.getID(), page

    def get_constraints(self, prop,
                        *,
                        type: Optional[type[ConstraintType]] = None,
                        scope: Optional[Scope] = None
                        ) -> List[Constraint]:
        key, page = self._get_input(prop)
        out = []
        if key not in self._cache:
            #print(f'Loading constraints for {key}...')
            self.load_constraints(page)
        out += self._cache[key]

        if scope:
            out = [constr for constr in out if constr.may_check(scope)]
        if type is not None:
            out = [constr for constr in out if isinstance(constr.type, type)]

        return out

    @staticmethod
    def _get_values(qualifiers) -> Set[str]:
        values = set()
        for qual in qualifiers:
            if qual.getSnakType() != 'value':
                values.add(qual.getSnakType())
            else:
                values.add(qual.getTarget().getID())
        return values

    def _get_pv_constraint(self, type_: type[ConstraintType], qualifiers
                           ) -> Optional[ConstraintType]:
        for qual_p in qualifiers.get('P2306', []):
            target_p = qual_p.getTarget()
            if not target_p:
                continue

            if not qualifiers.get('P2305'):
                return type_(target_p.getID())

            values = self._get_values(qualifiers['P2305'])
            return type_(target_p.getID(), values)

        return None

    def load_constraints(self, page: PropertyPage) -> List[Constraint]:
        val_to_relation = {
            'Q21503252': ['P31'],
            'Q21514624': ['P279'],
            'Q30208840': ['P31', 'P279'],
        }

        out = []
        for claim in page.claims.get('P2302', []):
            if claim.rank == 'deprecated':
                continue

            target = claim.getTarget()
            if not target:
                continue

            constraint = None
            if target.getID() in ('Q21510859', 'Q52558054', 'Q21514353') \
               and claim.qualifiers.get('P2305'):
                    values = self._get_values(claim.qualifiers['P2305'])
                    if target.getID() == 'Q21510859':
                        constraint = OneOf(values)
                    elif target.getID() == 'Q52558054':
                        constraint = NoneOf(values)
                    elif target.getID() == 'Q21514353':
                        constraint = Units(values)

            elif target.getID() in ('Q108139345', 'Q111204896'):
                values = set()
                for qual in claim.qualifiers.get('P424', []):
                    if qual.getTarget():
                        values.add(qual.getTarget())
                if values:
                    if target.getID() == 'Q108139345':
                        constraint = LabelInLanguage(values)
                    elif target.getID() == 'Q111204896':
                        constraint = DescriptionInLanguage(values)

            elif target.getID() == 'Q21503247':
                constraint = self._get_pv_constraint(
                    ItemRequires, claim.qualifiers)

            elif target.getID() == 'Q21510864':
                constraint = self._get_pv_constraint(
                    ValueRequires, claim.qualifiers)

            elif target.getID() == 'Q21502838':
                constraint = self._get_pv_constraint(
                    ConflictsWith, claim.qualifiers)

            elif target.getID() == 'Q21502404':
                for qual in claim.qualifiers.get('P1793', []):
                    if qual.getTarget():
                        try:
                            constraint = Format(qual.getTarget())
                        except re.error:
                            pass
                        break

            elif target.getID() == 'Q21510852':
                file_repo = self.repo.image_repository()
                prefix = ''
                for qual in claim.qualifiers.get('P2307', []):
                    prefix = str(qual.getTarget())
                    break
                namespace = file_repo.namespaces.lookup_name(prefix)
                if namespace:
                    constraint = CommonsLink(file_repo, namespace)

            elif target.getID() == 'Q51723761':
                constraint = NoBounds()

            elif target.getID() == 'Q52848401':
                constraint = Integer()

            elif target.getID() == 'Q21510862':
                constraint = Symmetric()

            elif target.getID() == 'Q21510855':
                for qual in claim.qualifiers.get('P2306', []):
                    if qual.getTarget():
                        constraint = Inverse(qual.getTarget().getID())
                        break

            elif target.getID() == 'Q21510860':
                for qual_lower, qual_upper in zip(
                    claim.qualifiers.get('P2313', []),
                    claim.qualifiers.get('P2312', [])
                ):
                    lower = upper = None
                    if qual_lower.getTarget():
                        lower = qual_lower.getTarget().amount
                    if qual_upper.getTarget():
                        upper = qual_upper.getTarget().amount
                    constraint = QuantityRange(lower, upper)
                    break

                for qual_lower, qual_upper in zip(
                    claim.qualifiers.get('P2310', []),
                    claim.qualifiers.get('P2311', [])
                ):
                    if qual_lower.getSnakType() == 'novalue':
                        lower = None
                    elif qual_lower.getSnakType() == 'somevalue':
                        current_ts = pywikibot.Timestamp.now()
                        lower = pywikibot.WbTime.fromTimestamp(current_ts)
                    else:
                        lower = qual_lower.getTarget().normalize()

                    if qual_upper.getSnakType() == 'novalue':
                        upper = None
                    elif qual_upper.getSnakType() == 'somevalue':
                        current_ts = pywikibot.Timestamp.now()
                        upper = pywikibot.WbTime.fromTimestamp(current_ts)
                    else:
                        upper = qual_upper.getTarget().normalize()

                    constraint = TimeRange(lower, upper)
                    break

            elif target.getID() == 'Q21510854':
                for qual_other, qual_lower, qual_upper in zip(
                    claim.qualifiers.get('P2306', []),
                    claim.qualifiers.get('P2313', []),
                    claim.qualifiers.get('P2312', [])
                ):
                    if qual_other.getTarget() \
                       and qual_lower.getSnakType() != 'somevalue' \
                       and qual_upper.getSnakType() != 'somevalue':
                        constraint = DifferenceWithinRange(
                            qual_other.getTarget().getID(),
                            qual_lower.getTarget(),
                            qual_upper.getTarget()
                        )
                    break

            elif target.getID() == 'Q21510865':
                classes = self._get_values(claim.qualifiers.get('P2308', []))
                if classes:
                    for qual in claim.qualifiers.get('P2309', []):
                        if qual.getTarget() \
                           and qual.getTarget().getID() in val_to_relation:
                            constraint = ValueType(
                                self.sparql,
                                val_to_relation[qual.getTarget().getID()],
                                classes
                            )
                            break

            elif target.getID() == 'Q21503250':
                classes = self._get_values(claim.qualifiers.get('P2308', []))
                if classes:
                    for qual in claim.qualifiers.get('P2309', []):
                        if qual.getTarget() \
                           and qual.getTarget().getID() in val_to_relation:
                            constraint = SubjectType(
                                self.sparql,
                                val_to_relation[qual.getTarget().getID()],
                                classes,
                                self._caches['SubjectType']
                            )
                            break

            elif target.getID() in ('Q21510851', 'Q21510856'):
                values = self._get_values(claim.qualifiers.get('P2306', []))
                if values:
                    if target.getID() == 'Q21510851':
                        constraint = Qualifiers(values)
                    elif target.getID() == 'Q21510856':
                        constraint = RequiredQualifiers(values)

            elif target.getID() == 'Q53869507':
                p_scopes = set()
                for qual in claim.qualifiers.get('P5314', []):
                    if qual.getTarget():
                        if qual.getTarget().getID() == 'Q54828448':
                            p_scopes.add(Scope.MAIN)
                        elif qual.getTarget().getID() == 'Q54828449':
                            p_scopes.add(Scope.QUALIFIER)
                        elif qual.getTarget().getID() == 'Q54828450':
                            p_scopes.add(Scope.REFERENCE)

                if p_scopes:
                    constraint = PropertyScope(p_scopes)

            if not constraint:
                continue

            status = Status.REGULAR
            for qual in claim.qualifiers.get('P2316', []):
                if qual.getTarget():
                    if qual.getTarget().getID() == 'Q21502408':
                        status = Status.MANDATORY
                        break
                    if qual.getTarget().getID() == 'Q62026391':
                        status = Status.SUGGESTION
                        break

            scopes = set()
            for qual in claim.qualifiers.get('P4680', []):
                if qual.getTarget():
                    if qual.getTarget().getID() == 'Q46466787':
                        scopes.add(Scope.MAIN)
                    elif qual.getTarget().getID() == 'Q46466783':
                        scopes.add(Scope.QUALIFIER)
                    elif qual.getTarget().getID() == 'Q46466805':
                        scopes.add(Scope.REFERENCE)

            if not scopes:
                scopes.update(Scope)

            out.append(Constraint(
                page.getID(),
                claim.snak,
                constraint,
                status,
                scopes
            ))

        out.append(Constraint(
            page.getID(),
            None,
            HasValidReference(self),
            Status.REGULAR,
            {Scope.MAIN}
        ))
        if page.type == 'wikibase-item':
            out.append(Constraint(
                page.getID(),
                None,
                NoLinksToDisambiguation(),
                Status.REGULAR,
                set(Scope)
            ))
            out.append(Constraint(
                page.getID(),
                None,
                NoSelfLink(),
                Status.REGULAR,
                set(Scope)
            ))
        if page.type == 'quantity':
            out.append(Constraint(
                page.getID(),
                None,
                LargeChange(),
                Status.SUGGESTION,
                set(Scope)
            ))
        self._cache[page.getID()] = out

    @performance_stats
    def get_item_constraints(self, props: Set[str], changed: Set[str]):
        for type_, item_id, require in [
            (ItemRequires, 'Q21503247', None),
            (ConflictsWith, 'Q21502838', None),
            (SubjectType, 'Q21510865', {'P31', 'P279'}),
            (LabelInLanguage, 'Q108139345', None),
            (DescriptionInLanguage, 'Q111204896', None),
        ]:
            if require and not (changed & require):
                continue

            loaded = [prop for prop in props if prop in self._cache]
            left = [prop for prop in props if prop not in self._cache]
            if len(left) < 5:
                loaded += left
                left = []

            for prop in loaded:
                yield from self.get_constraints(prop, type=type_)

            if not left:
                continue

            tmpl = 'SELECT DISTINCT ?prop {'
            tmpl += ' VALUES ?prop { %(local)s } .'
            if require:
                tmpl += ' ?prop wdt:P2302 wd:%(item_id)s }'
            else:
                tmpl += ' VALUES ?changed { %(changed)s } .'
                tmpl += ' ?prop p:P2302 [ ps:P2302 wd:%(item_id)s;'
                tmpl += ' pq:P2306 ?changed ] }'

            query = tmpl % {
                'local': ' '.join(f'wd:{p}' for p in left),
                'changed': ' '.join(f'wd:{p}' for p in changed),
                'item_id': item_id,
            }
            try:
                for prop in self.sparql.get_items(query, 'prop'):
                    yield from self.get_constraints(prop, type=type_)
            except (ConnectionError, ServerError) as exc:
                pywikibot.error(
                    f'{exc.__class__.__name__} occurred in ConstraintsStore '
                    f'when running query:\n{query}')

    def purge(self, prop) -> None:
        key, _ = self._get_input(prop)
        self._cache.pop(key, None)


class ConstraintEvaluator:

    def __init__(self, store: ConstraintsStore) -> None:
        self.store = store

    @staticmethod
    def index_by_id(claims: List[Claim]) -> Dict[str, Claim]:
        return {claim.snak: claim for claim in claims}

    def claim_differences(self, old: WikibaseEntity, new: WikibaseEntity):
        for prop in old.claims.keys() | new.claims.keys():
            old_index = self.index_by_id(old.claims.get(prop, []))
            new_index = self.index_by_id(new.claims.get(prop, []))
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

    def evaluate_atomic_change(self, context: Context, result: Result) -> None:
        if context.new_claim is None:
            for constr in self.store.get_constraints(
                context.prop,
                type=ClaimConstraintType,
                scope=Scope.MAIN
            ):
                constr.handle_removal(context, result)

        elif context.old_claim is None:
            for constr in self.store.get_constraints(
                context.prop,
                type=ClaimConstraintType,
                scope=Scope.MAIN
            ):
                constr.handle_addition(context, result)
            for prop, values in context.new_claim.qualifiers.items():
                for constr in self.store.get_constraints(
                    prop,
                    type=ClaimConstraintType,
                    scope=Scope.QUALIFIER
                ):
                    for qual in values:
                        ctx = Context(context.old_rev, context.new_rev, None, qual)
                        constr.handle_addition(ctx, result)

        else:
            old_claim = context.old_claim
            new_claim = context.new_claim
            for constr in self.store.get_constraints(
                context.prop,
                type=ClaimConstraintType,
                scope=Scope.MAIN
            ):
                if not constr.type.value_change_needed() \
                   or cmp_key(old_claim) != cmp_key(new_claim):
                    constr.handle_update(context, result)

            keys = old_claim.qualifiers.keys() | new_claim.qualifiers.keys()
            for key in keys:
                old_qualifiers = old_claim.qualifiers.get(key)
                new_qualifiers = new_claim.qualifiers.get(key)

                added = []
                removed = []
                if not old_qualifiers:
                    added.extend(new_qualifiers)
                elif not new_qualifiers:
                    removed.extend(old_qualifiers)
                else:
                    old_matched = set()
                    new_matched = set()
                    for i, qual in enumerate(old_qualifiers):
                        for j, other in enumerate(new_qualifiers):
                            if cmp_key(qual) == cmp_key(other):
                                old_matched.add(i)
                                new_matched.add(j)
                                break

                    for i, qual in enumerate(old_qualifiers):
                        if i not in old_matched:
                            removed.append(qual)
                    for i, qual in enumerate(new_qualifiers):
                        if i not in new_matched:
                            added.append(qual)

                if added or removed:
                    for constr in self.store.get_constraints(
                        key,
                        type=ClaimConstraintType,
                        scope=Scope.QUALIFIER
                    ):
                        if len(added) == 1 == len(removed):
                            for qual_r, qual_add in zip(removed, added):
                                ctx = Context(context.old_rev,
                                              context.new_rev,
                                              qual_r, qual_add)
                                constr.handle_update(ctx, result)
                        else:
                            for qual in added:
                                ctx = Context(context.old_rev,
                                              context.new_rev,
                                              None, qual)
                                constr.handle_addition(ctx, result)
                            for qual in removed:
                                ctx = Context(context.old_rev,
                                              context.new_rev,
                                              qual, None)
                                constr.handle_removal(ctx, result)
            # TODO: references

    @performance_stats
    def evaluate_change(
        self,
        old_rev: WikibaseEntity,
        new_rev: WikibaseEntity,
        current: Optional[WikibaseEntity] = None
    ) -> Result:
        result = Result()

        touched = set()
        for old_claim, new_claim in self.claim_differences(old_rev, new_rev):
            # ignore if dealt with (probably)
            if current:
                if old_claim and item_has_claim(current, old_claim):
                    continue
                if new_claim and not old_claim \
                   and new_claim.getID() not in current.claims:
                    continue

            context = Context(old_rev, new_rev, old_claim, new_claim)
            self.evaluate_atomic_change(context, result)
            touched.add(context.prop)

        context = Context(old_rev, new_rev, None, None)
        specifier = (ItemRequires, ConflictsWith, SubjectType)

        added = new_rev.claims.keys() - old_rev.claims.keys()
        removed = old_rev.claims.keys() - new_rev.claims.keys()
        if current:
            added &= current.claims.keys()
            removed -= current.claims.keys()

        for prop in added:
            for constr in self.store.get_constraints(prop, type=specifier):
                constr.handle_addition(context, result)

        for prop in removed:
            for constr in self.store.get_constraints(prop, type=specifier):
                constr.handle_removal(context, result)

        for constr in self.store.get_item_constraints(
            old_rev.claims.keys() & new_rev.claims.keys(),
            touched  # or? touched - added - removed
        ):
            constr.handle_update(context, result)

        return result

    def evaluate_entity(self, entity: WikibaseEntity) -> List[Constraint]:
        violated = []

        for prop in entity.claims:
            for constr in self.store.get_constraints(
                prop,
                type=ClaimConstraintType,
                scope=Scope.MAIN
            ):
                for claim in entity.claims[prop]:
                    if constr.type.violates(claim):
                        violated.append(constr)

                    for qprop, values in claim.qualifiers.items():
                        for constr in self.store.get_constraints(
                            qprop,
                            type=ClaimConstraintType,
                            scope=Scope.QUALIFIER
                        ):
                            for qual in values:
                                if constr.type.violates(qual):
                                    violated.append(constr)

        for constr in self.store.get_item_constraints(
            set(entity.claims),
            set(entity.claims)
        ):
            if not constr.type.satisfied(entity):
                violated.append(constr)

        return violated
