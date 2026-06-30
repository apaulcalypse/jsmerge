"""Tokenize Junos curly-brace configuration text."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Iterator


class TokenKind(Enum):
    LBRACE = auto()
    RBRACE = auto()
    SEMICOLON = auto()
    INACTIVE = auto()
    REPLACE = auto()
    SECRET = auto()
    IDENT = auto()
    STRING = auto()
    COMMENT = auto()
    EOF = auto()


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    value: str
    line: int
    column: int


class LexError(Exception):
    def __init__(self, message: str, line: int, column: int) -> None:
        super().__init__(f"{message} at line {line}, column {column}")
        self.line = line
        self.column = column


def _is_value_atom_char(ch: str) -> bool:
    """Characters allowed inside unquoted value atoms (identifiers, paths, wildcards, etc.).

    This is intentionally broad so that real Junos "show configuration" output
    (with <*>, ::/0, .*FOO.*, /junos/..., prefix-length-range, etc.) parses
    without constant per-character whack-a-mole.
    """
    return not ch.isspace() and ch not in '{ };"'






def tokenize(text: str) -> list[Token]:
    tokens: list[Token] = []
    i = 0
    line = 1
    column = 1
    length = len(text)

    def advance(n: int = 1) -> None:
        nonlocal i, line, column
        for _ in range(n):
            if i < length and text[i] == "\n":
                line += 1
                column = 1
            else:
                column += 1
            i += 1

    def peek(offset: int = 0) -> str:
        pos = i + offset
        return text[pos] if pos < length else ""

    def emit(kind: TokenKind, value: str, start_line: int, start_col: int) -> None:
        tokens.append(Token(kind, value, start_line, start_col))

    while i < length:
        ch = text[i]

        if ch.isspace():
            advance()
            continue

        start_line, start_col = line, column

        if ch == "{":
            emit(TokenKind.LBRACE, "{", start_line, start_col)
            advance()
            continue

        if ch == "}":
            emit(TokenKind.RBRACE, "}", start_line, start_col)
            advance()
            continue

        if ch == ";":
            emit(TokenKind.SEMICOLON, ";", start_line, start_col)
            advance()
            continue

        if ch == "#" and peek(1) == "#":
            # Emit a SECRET token for "## SECRET-DATA" (preserved for round-trip diffs).
            advance(2)
            while i < length and text[i].isspace():
                advance()
            if text[i:].startswith("SECRET-DATA"):
                advance(12)
                while i < length and text[i].isspace():
                    advance()
                if i < length and text[i] == ";":
                    advance()
            emit(TokenKind.SECRET, "SECRET-DATA", start_line, start_col)
            continue

        if ch == "/" and peek(1) == "*":
            advance(2)
            body: list[str] = []
            while i < length:
                if peek() == "*" and peek(1) == "/":
                    advance(2)
                    break
                body.append(text[i])
                advance()
            else:
                raise LexError("Unterminated block comment", start_line, start_col)
            emit(TokenKind.COMMENT, "".join(body).strip(), start_line, start_col)
            continue

        if ch == '"':
            advance()
            body = []
            while i < length:
                if text[i] == "\\" and i + 1 < length:
                    body.append(text[i : i + 2])
                    advance(2)
                    continue
                if text[i] == '"':
                    advance()
                    break
                body.append(text[i])
                advance()
            else:
                raise LexError("Unterminated string", start_line, start_col)
            emit(TokenKind.STRING, "".join(body), start_line, start_col)
            continue

        if _is_value_atom_char(ch):
            start = i
            advance()
            while i < length and _is_value_atom_char(text[i]):
                advance()
            ident = text[start:i]
            if ident in ("inactive:", "inactive") and (ident == "inactive:" or peek() == ":"):
                if ident == "inactive":
                    advance()
                emit(TokenKind.INACTIVE, "inactive:", start_line, start_col)
            elif ident in ("replace:", "replace") and (ident == "replace:" or peek() == ":"):
                if ident == "replace":
                    advance()
                emit(TokenKind.REPLACE, "replace:", start_line, start_col)
            else:
                emit(TokenKind.IDENT, ident, start_line, start_col)
            continue

        raise LexError(f"Unexpected character {ch!r}", start_line, start_col)

    tokens.append(Token(TokenKind.EOF, "", line, column))
    return tokens


def iter_non_comment(tokens: list[Token]) -> Iterator[Token]:
    for token in tokens:
        if token.kind != TokenKind.COMMENT:
            yield token
