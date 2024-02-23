# Usage

## Initialize
```
import pywikibot
from pywikibot.data.sparql import SparqlQuery
from constraints import *

repo = pywikibot.Site('wikidata')
sparql = SparqlQuery(repo=repo)
store = ConstraintsStore(repo, sparql)
evaluator = ConstraintEvaluator(store)
```

## Evaluate a recent change
```
entry = next(repo.recentchanges(tag='new editor changing statement', total=1))
item = repo.get_entity_for_entity_id(entry['title'])
new_rev = get_revision_wrapper(item, entry['revid'])
base_rev = get_revision_wrapper(item, entry['old_revid'])

result = evaluator.evaluate_change(base_rev, new_rev)
```

## Evaluate a sequence of changes
```
entry = next(repo.recentchanges(tag='new editor changing statement', total=1))
item = repo.get_entity_for_entity_id(entry['title'])
base_id, new_id = span_revisions(item, entry)
new_rev = get_revision_wrapper(item, new_id)
base_rev = get_revision_wrapper(item, base_id)

result = evaluator.evaluate_change(base_rev, new_rev)
```

## Evaluate a revision difference
```
page = next(repo.randompages(namespaces=0, total=1, redirects=False))
item = repo.get_entity_for_entity_id(page.title())
entry = revision_to_entry(item.latest_revision)
new_rev = get_revision_wrapper(item, entry['revid'])
base_rev = get_revision_wrapper(item, entry['old_revid'])

result = evaluator.evaluate_change(base_rev, new_rev)
```

## Evaluate an entity
```
entry = next(repo.recentchanges(changetype='new', namespaces=[0], total=1))
item = repo.get_entity_for_entity_id(entry['title'])

result = evaluator.evaluate_entity(item)
```