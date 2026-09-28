"""Anti-flood: не больше N событий от одного пользователя за окно; превышение молча игнорируется.

Бот отвечает на каждое сообщение — без троттлинга шквал от одного чата даёт шторм
запросов к MAX API (риск 429, который клиент не ретраит) и забивает очередь апдейтов.
"""

import functools
import inspect
import time
from collections.abc import Awaitable, Callable

WINDOW = 10.0  # секунд
LIMIT = 6      # событий от одного пользователя за окно

_hits: dict[int, list[float]] = {}


def _event_user_id(event) -> int | None:
    msg = getattr(event, "message", None)
    if msg is not None:
        sender = getattr(msg, "sender", None)
        uid = getattr(sender, "user_id", None)
        if uid is not None:
            return uid
        recipient = getattr(msg, "recipient", None)
        return getattr(recipient, "user_id", None)
    cb = getattr(event, "callback", None)
    user = getattr(cb, "user", None) if cb is not None else None
    return getattr(user, "user_id", None)


def throttled(fn: Callable[..., Awaitable]) -> Callable[..., Awaitable]:
    # Диспетчер передаёт свои контекстные kwargs (args, data, state…), а обработчики
    # принимают только event: фильтруем по сигнатуре оригинала, иначе TypeError
    # у каждого обработчика. wraps нужен, чтобы сигнатура обёртки выглядела как fn.
    fn_params = set(inspect.signature(fn).parameters)
    fn_var_kw = any(
        p.kind is inspect.Parameter.VAR_KEYWORD
        for p in inspect.signature(fn).parameters.values()
    )

    @functools.wraps(fn)
    async def inner(event, *args, **kwargs):
        if not fn_var_kw:
            kwargs = {k: v for k, v in kwargs.items() if k in fn_params}
        uid = _event_user_id(event)
        now = time.monotonic()
        if uid is not None:
            recent = [t for t in _hits.get(uid, []) if now - t < WINDOW]
            if len(recent) >= LIMIT:
                return  # флуд: тихо пропускаем
            recent.append(now)
            _hits[uid] = recent
            if len(_hits) > 1000:  # чистим чаты, которые замолчали
                for u in [k for k, ts in _hits.items() if now - ts[-1] >= WINDOW]:
                    _hits.pop(u, None)
        return await fn(event, *args, **kwargs)

    return inner
