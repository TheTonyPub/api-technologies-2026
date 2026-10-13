"""«База данных» — словарь в памяти."""

from itertools import count

from schemas import TaskResponse

tasks: dict[int, TaskResponse] = {}
task_ids = count(start=1)
