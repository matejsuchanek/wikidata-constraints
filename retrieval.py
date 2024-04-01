import json
import re
from collections import deque
from datetime import timedelta
from typing import Tuple

import pywikibot
from pywikibot import Timestamp
from pywikibot.page import Page, PropertyPage, User, WikibaseEntity


def span_revisions(item, entry) -> Tuple[int, int]:
    base_id = entry['old_revid']
    new_id = entry['revid']
    timestamp = entry['timestamp']
    if not isinstance(timestamp, Timestamp):
        timestamp = Timestamp.fromISOformat(timestamp)

    queue = deque()

    # towards now
    for rev in item.revisions(
        starttime=timestamp.totimestampformat(),
        endtime=(timestamp + timedelta(days=5)).totimestampformat(),
        reverse=True
    ):
        if rev.revid == new_id:  # first pass
            queue.append(rev)
            continue

        last = queue[-1]
        if rev.user == last.user:
            queue.append(rev)
            continue

        delta = rev.timestamp - last.timestamp
        if delta.total_seconds() < 900 and not rev.userhidden:
            the_user = User(item.site, rev.user)
            if not the_user.isRegistered() \
               or 'autoconfirmed' not in the_user.groups():
                queue.append(rev)
                continue

        break

    first_is_base = False

    # towards past
    for rev in item.revisions(
        starttime=timestamp.totimestampformat(),
        endtime=(timestamp - timedelta(days=5)).totimestampformat(),
        reverse=False
    ):
        if rev.revid == new_id:  # first pass
            continue

        last = queue[0]
        queue.appendleft(rev)
        if rev.user == last.user:
            continue

        delta = last.timestamp - rev.timestamp
        if delta.total_seconds() < 900 and not rev.userhidden:
            the_user = User(item.site, rev.user)
            if not the_user.isRegistered() \
               or 'autoconfirmed' not in the_user.groups():
                continue

        first_is_base = True
        break

    # handle deleted revisions
    for rev in reversed(queue):
        if item.getOldVersion(rev.revid):
            new_id = rev.revid
            break

    if not first_is_base and (
        queue[0].parentid == 0
        or item.getOldVersion(queue[0].parentid)
    ):
        return queue[0].parentid, new_id

    for rev in queue:
        if item.getOldVersion(rev.revid):
            base_id = rev.revid
            break

    return base_id, new_id


def get_revision_wrapper(item: WikibaseEntity, rev_id: int):
    cls = type(item)
    repo = item.repo
    entity_id = item.getID()

    rev = cls(repo, entity_id)
    data = json.loads(item.getOldVersion(rev_id))
    for key, val in data.items():
        # handle old serialization
        if val == []:
            data[key] = {}

    rev._content = data
    while True:
        try:
            rev.get()
        except KeyError as exc:
            # handle deleted properties
            key = exc.args[0]
            if key.lower() in data['claims']:
                data['claims'].pop(key.lower())
            elif key.upper() in data['claims']:
                data['claims'].pop(key.upper())
            else:
                raise
        else:
            return rev


def revision_to_entry(revision):
    return {
        'old_revid': revision.parentid,
        'revid': revision.revid,
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
