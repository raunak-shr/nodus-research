"""Split a SQL script into individual statements.

asyncpg refuses multi-statement strings ("cannot insert multiple commands into
a prepared statement"), so migrations that ship raw SQL have to execute one
statement at a time. Dollar-quoted bodies (``$$ … $$``, ``$tag$ … $tag$``) are
treated as opaque, keeping semicolons inside PL/pgSQL functions intact.
"""

from __future__ import annotations

import re

_DOLLAR_TAG = re.compile(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$")


def split_statements(sql: str) -> list[str]:
    statements: list[str] = []
    buffer: list[str] = []
    index = 0
    length = len(sql)
    active_tag: str | None = None

    while index < length:
        char = sql[index]

        if active_tag:
            buffer.append(char)
            if sql.startswith(active_tag, index):
                buffer.append(sql[index + 1 : index + len(active_tag)])
                index += len(active_tag)
                active_tag = None
                continue
            index += 1
            continue

        match = _DOLLAR_TAG.match(sql, index)
        if match:
            active_tag = match.group(0)
            buffer.append(active_tag)
            index += len(active_tag)
            continue

        if char == "-" and sql.startswith("--", index):
            end = sql.find("\n", index)
            index = length if end == -1 else end + 1
            continue

        if char == "'":
            end = index + 1
            while end < length:
                if sql[end] == "'":
                    if end + 1 < length and sql[end + 1] == "'":
                        end += 2
                        continue
                    break
                end += 1
            buffer.append(sql[index : end + 1])
            index = end + 1
            continue

        if char == ";":
            statement = "".join(buffer).strip()
            if statement:
                statements.append(statement)
            buffer = []
            index += 1
            continue

        buffer.append(char)
        index += 1

    tail = "".join(buffer).strip()
    if tail:
        statements.append(tail)
    return statements
