"""Parse Junos curly-brace configuration into a ConfigNode tree."""

from __future__ import annotations

from dataclasses import dataclass

from jsmerge.models import ConfigNode
from jsmerge.parser.lexer import Token, TokenKind, tokenize


class ParseError(Exception):
    def __init__(self, message: str, token: Token) -> None:
        super().__init__(f"{message} at line {token.line}, column {token.column}")
        self.token = token


@dataclass
class _Parser:
    tokens: list[Token]
    index: int = 0
    source_counter: int = 0

    def current(self) -> Token:
        return self.tokens[self.index]

    def advance(self) -> Token:
        token = self.tokens[self.index]
        self.index += 1
        return token

    def match(self, kind: TokenKind, value: str | None = None) -> Token:
        token = self.current()
        if token.kind != kind or (value is not None and token.value != value):
            expected = value or kind.name
            raise ParseError(f"Expected {expected}, got {token.kind.name} {token.value!r}", token)
        return self.advance()

    def at(self, kind: TokenKind) -> bool:
        return self.current().kind == kind

    def consume_comments(self) -> list[str]:
        comments: list[str] = []
        while self.at(TokenKind.COMMENT):
            comments.append(self.advance().value)
        return comments

    def next_source_index(self) -> int:
        self.source_counter += 1
        return self.source_counter

    def parse_statements(self, parent: ConfigNode) -> None:
        while not self.at(TokenKind.RBRACE) and not self.at(TokenKind.EOF):
            comments = self.consume_comments()
            inactive = False
            if self.at(TokenKind.INACTIVE):
                self.advance()
                inactive = True
            node = self.parse_statement()
            if comments:
                node.comments = comments
            if inactive:
                node.flags.add("inactive")
            parent.children.append(node)

    def _parse_value(self) -> str | None:
        """Parse one or more value tokens before ``;`` or ``{``."""
        if not (self.at(TokenKind.STRING) or self.at(TokenKind.IDENT)):
            return None
        parts: list[str] = []
        while self.at(TokenKind.STRING) or self.at(TokenKind.IDENT):
            parts.append(self.advance().value)
        return " ".join(parts)

    def parse_statement(self) -> ConfigNode:
        name_token = self.match(TokenKind.IDENT)
        name = name_token.value
        source_index = self.next_source_index()

        value = self._parse_value()
        if value is not None:
            if self.at(TokenKind.LBRACE):
                self.match(TokenKind.LBRACE)
                node = ConfigNode(name=name, value=value, source_index=source_index)
                self.parse_statements(node)
                self.match(TokenKind.RBRACE)
                return node
            self.match(TokenKind.SEMICOLON)
            return ConfigNode(name=name, value=value, source_index=source_index)

        if self.at(TokenKind.LBRACE):
            self.match(TokenKind.LBRACE)
            node = ConfigNode(name=name, source_index=source_index)
            self.parse_statements(node)
            self.match(TokenKind.RBRACE)
            return node

        self.match(TokenKind.SEMICOLON)
        return ConfigNode(name=name, source_index=source_index)


def parse_config(text: str) -> ConfigNode:
    """Parse configuration text into a tree rooted at ``configuration``."""
    stripped = text.strip()
    if not stripped:
        return ConfigNode(name="configuration")

    if not stripped.startswith("configuration") and not stripped.startswith("{"):
        stripped = f"{{\n{stripped}\n}}"

    tokens = tokenize(stripped)
    parser = _Parser(tokens)

    if parser.at(TokenKind.IDENT) and parser.current().value == "configuration":
        parser.advance()
        parser.match(TokenKind.LBRACE)
        root = ConfigNode(name="configuration")
        parser.parse_statements(root)
        parser.match(TokenKind.RBRACE)
        parser.match(TokenKind.EOF)
        return root

    if parser.at(TokenKind.LBRACE):
        parser.match(TokenKind.LBRACE)
        root = ConfigNode(name="configuration")
        parser.parse_statements(root)
        parser.match(TokenKind.RBRACE)
        parser.match(TokenKind.EOF)
        return root

    root = ConfigNode(name="configuration")
    parser.parse_statements(root)
    parser.match(TokenKind.EOF)
    return root
