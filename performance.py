import time

from functools import wraps
from tabulate import tabulate

_registry = []

def performance_stats(func, /):
    @wraps(func)
    def wrapper(self, *args, **kwargs):
        start_time = time.time()
        result = func(self, *args, **kwargs)
        end_time = time.time()
        elapsed_time = end_time - start_time

        if not hasattr(self, '_performance_stats'):
            self._performance_stats = {}
            _registry.append(self)

        memo = self._performance_stats
        if func.__name__ not in memo:
            memo[func.__name__] = {'count': 1, 'total_time': elapsed_time}
        else:
            memo[func.__name__]['count'] += 1
            memo[func.__name__]['total_time'] += elapsed_time

        return result

    return wrapper


def print_stats(sort='average', *, descending=True) -> None:
    table = []
    keys = ['count', 'total_time', 'average']
    idx = keys.index(sort) + 1
    for inst in _registry:
        for name, data in inst._performance_stats.items():
            row = [f'{inst}.{name}']
            row.append(data['count'])
            row.append(data['total_time'])
            row.append(data['total_time'] / data['count'])
            table.append(row)

    table.sort(key=lambda row: row[idx], reverse=descending)
    print(tabulate(table, headers=['Method', 'Calls', 'Total time', 'Average']))
