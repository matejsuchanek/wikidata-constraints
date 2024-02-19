import json
import re
from datetime import timedelta
from typing import Tuple

import pywikibot
from pywikibot import Timestamp
from pywikibot.page import Page, PropertyPage, User, WikibaseEntity


def span_revisions(item, entry) -> Tuple[int, int]:
    base_id = entry['old_revid']
    new_id = entry['revid']
    last_user = user = entry['user']
    timestamp = entry['timestamp']
    if not isinstance(timestamp, Timestamp):
        timestamp = Timestamp.fromISOformat(timestamp)
    last_timestamp = timestamp

    # towards now
    for rev in item.revisions(
        starttime=timestamp.totimestampformat(),
        endtime=(timestamp + timedelta(days=5)).totimestampformat(),
        reverse=True
    ):
        if rev['revid'] == new_id:
            continue
        if rev.user == last_user:
            new_id = rev['revid']
            last_timestamp = rev.timestamp
            continue

        delta = rev.timestamp - last_timestamp
        if delta.total_seconds() < 900:
            the_user = User(item.site, rev.user)
            if not the_user.isRegistered() \
               or 'autoconfirmed' not in the_user.groups():
                new_id = rev['revid']
                last_timestamp = rev.timestamp
                last_user = rev.user
                continue

        break

    # towards past
    for rev in item.revisions(
        starttime=timestamp.totimestampformat(),
        endtime=(timestamp - timedelta(days=5)).totimestampformat(),
        reverse=False
    ):
        if rev['revid'] == new_id:
            continue
        if rev.user == last_user:
            base_id = rev.parentid
            last_timestamp = rev.timestamp
            continue

        delta = last_timestamp - rev.timestamp
        if delta.total_seconds() < 900:
            the_user = User(item.site, rev.user)
            if not the_user.isRegistered() \
               or 'autoconfirmed' not in the_user.groups():
                new_id = rev['revid']
                last_timestamp = rev.timestamp
                last_user = rev.user
                continue

        break

    return base_id, new_id


def get_revision_wrapper(item: WikibaseEntity, rev_id: int):
    cls = type(item)
    repo = item.repo
    entity_id = item.getID()

    rev = cls(repo, entity_id)
    data = json.loads(item.getOldVersion(rev_id))
    for key, val in data.items():
        if val == []:
            data[key] = {}
    rev._content = data
    rev.get()
    return rev


def revision_to_entry(revision):
    return {
        'old_revid': revision.parentid,
        'revid': revision.revid,
        'user': revision.user,
        'timestamp': revision.timestamp,
    }


def preload_constraints(store, limit: int = 1000, *, verbose=False) -> None:
    page = Page(store.repo, 'Template:Number of main statements by property')

    counts = []
    for match in re.finditer(r'\b(\d+)=(\d+)\b', page.text):
        pid, count = map(int, match.groups())
        counts.append((count, pid))
    counts.sort(reverse=True)

    preload = [PropertyPage(store.repo, f'P{pid}') for _, pid in counts[:limit]]

    for ppage in store.repo.preload_entities(preload):
        store.load_constraints(ppage)
