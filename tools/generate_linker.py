#!/usr/bin/env python3
"""Generate GNU ld or Arm Compiler scatter inputs from C layout structures."""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path


TOKEN_PATTERN = re.compile(
    r"(?P<space>\s+)|(?P<comment>//[^\n]*|/\*[\s\S]*?\*/)|"
    r"(?P<string>\"(?:\\.|[^\"\\])*\")|(?P<number>0[xX][0-9a-fA-F]+|[0-9]+)|"
    r"(?P<identifier>[A-Za-z_][A-Za-z0-9_]*)|(?P<punct><<|>>|[{}()\[\],;.=|+\-*])"
)
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    line: int
    column: int


@dataclass(frozen=True)
class Memory:
    name: str
    origin: int
    size: int
    attributes: int


@dataclass(frozen=True)
class Region:
    name: str
    kind: str
    memory: str
    load_memory: str | None
    address: int | None
    size: int | None
    alignment: int
    start_symbol: str
    end_symbol: str
    load_symbol: str | None


class LayoutError(ValueError):
    def __init__(self, token: Token, message: str):
        super().__init__(f"line {token.line}, column {token.column}: {message}")


def filter_conditionals(source: str, toolchain: str) -> str:
    """Apply the small #if subset needed by layouts before regular-expression lexing."""
    defines = {"PL_TOOLCHAIN_GNU" if toolchain == "gnu" else "PL_TOOLCHAIN_ARMCLANG"}
    frames: list[dict[str, bool]] = []
    output: list[str] = []

    def enabled() -> bool:
        return all(frame["active"] for frame in frames)

    def evaluate(condition: str) -> bool:
        match = re.fullmatch(r"defined\s*(?:\(\s*([A-Za-z_]\w*)\s*\)|\s+([A-Za-z_]\w*))", condition.strip())
        if match:
            return (match.group(1) or match.group(2)) in defines
        match = re.fullmatch(r"!\s*defined\s*(?:\(\s*([A-Za-z_]\w*)\s*\)|\s+([A-Za-z_]\w*))", condition.strip())
        if match:
            return (match.group(1) or match.group(2)) not in defines
        if condition.strip() in {"0", "1"}:
            return condition.strip() == "1"
        raise ValueError(f"unsupported #if condition: {condition.strip()!r}")

    for line_number, line in enumerate(source.splitlines(keepends=True), start=1):
        directive = re.match(r"\s*#\s*(\w+)(?:\s+(.*?))?\s*(?:\n|$)", line)
        if not directive:
            output.append(line if enabled() else "\n")
            continue
        command, argument = directive.group(1), directive.group(2) or ""
        parent = enabled()
        if command in {"if", "ifdef", "ifndef"}:
            expression = argument if command == "if" else f"{'!' if command == 'ifndef' else ''}defined({argument})"
            selected = parent and evaluate(expression)
            frames.append({"parent": parent, "taken": selected, "active": selected})
        elif command == "elif":
            if not frames:
                raise ValueError(f"line {line_number}: #elif without #if")
            frame = frames[-1]
            selected = frame["parent"] and not frame["taken"] and evaluate(argument)
            frame["active"] = selected
            frame["taken"] = frame["taken"] or selected
        elif command == "else":
            if not frames:
                raise ValueError(f"line {line_number}: #else without #if")
            frame = frames[-1]
            frame["active"] = frame["parent"] and not frame["taken"]
            frame["taken"] = True
        elif command == "endif":
            if not frames:
                raise ValueError(f"line {line_number}: #endif without #if")
            frames.pop()
        elif command == "error" and enabled():
            raise ValueError(f"line {line_number}: #error {argument}")
        elif command not in {"include", "define", "pragma", "error"}:
            raise ValueError(f"line {line_number}: unsupported preprocessor directive #{command}")
        output.append("\n")
    if frames:
        raise ValueError("unterminated conditional compilation block")
    return "".join(output)


def lex(source: str) -> list[Token]:
    tokens: list[Token] = []
    position = 0
    line = 1
    column = 1
    while position < len(source):
        match = TOKEN_PATTERN.match(source, position)
        if not match:
            raise ValueError(f"line {line}, column {column}: unsupported character {source[position]!r}")
        text = match.group(0)
        if match.lastgroup not in {"space", "comment"}:
            tokens.append(Token(match.lastgroup or "", text, line, column))
        breaks = text.count("\n")
        line += breaks
        column = len(text) - text.rfind("\n") if breaks else column + len(text)
        position = match.end()
    tokens.append(Token("eof", "", line, column))
    return tokens


class Parser:
    def __init__(self, tokens: list[Token]):
        self.tokens = tokens
        self.index = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def accept(self, text: str) -> bool:
        if self.current.text == text:
            self.index += 1
            return True
        return False

    def expect(self, text: str) -> Token:
        if not self.accept(text):
            raise LayoutError(self.current, f"expected {text!r}, found {self.current.text!r}")
        return self.tokens[self.index - 1]

    def identifier(self) -> Token:
        if self.current.kind != "identifier":
            raise LayoutError(self.current, f"expected identifier, found {self.current.text!r}")
        token = self.current
        self.index += 1
        return token

    def parse_layout(self) -> tuple[list[dict], list[dict]]:
        memories: list[dict] = []
        regions: list[dict] = []
        while self.current.kind != "eof":
            found = self.find_layout_array()
            if found is None:
                self.index += 1
                continue
            type_name, name_index = found
            self.index = name_index
            self.identifier()
            self.expect("[")
            self.expect("]")
            self.expect("=")
            values = self.initializer()
            self.expect(";")
            if not isinstance(values, list):
                raise LayoutError(self.current, f"{type_name} must use a braced array initializer")
            (memories if type_name == "pl_memory_t" else regions).extend(values)
        return memories, regions

    def find_layout_array(self) -> tuple[str, int] | None:
        for offset in range(4):
            token = self.tokens[self.index + offset]
            if token.kind == "eof" or token.text == ";":
                return None
            if token.text in {"pl_memory_t", "pl_link_region_t"} and self.tokens[self.index + offset + 1].kind == "identifier":
                return token.text, self.index + offset + 1
        return None

    def initializer(self):
        self.expect("{")
        positional: list[object] = []
        fields: dict[str, object] = {}
        designated = False
        while not self.accept("}"):
            if self.accept("."):
                designated = True
                field = self.identifier().text
                self.expect("=")
                fields[field] = self.value()
            else:
                positional.append(self.value())
            if not self.accept(","):
                self.expect("}")
                break
        if designated:
            if positional:
                raise LayoutError(self.current, "cannot mix positional and designated initializers")
            return fields
        return positional

    def value(self):
        return self.initializer() if self.current.text == "{" else self.expression()

    def expression(self):
        value = self.primary()
        while self.current.text in {"|", "+", "-", "<<", ">>"}:
            operator = self.current.text
            self.index += 1
            value = (operator, value, self.primary())
        return value

    def primary(self):
        token = self.current
        if token.kind == "number":
            self.index += 1
            return int(token.text, 0)
        if token.kind == "string":
            self.index += 1
            return ast.literal_eval(token.text)
        if token.kind == "identifier":
            self.index += 1
            if self.accept("("):
                arguments = []
                if not self.accept(")"):
                    while True:
                        arguments.append(self.expression())
                        if self.accept(")"):
                            break
                        self.expect(",")
                return ("call", token.text, arguments)
            return ("identifier", token.text)
        if self.accept("("):
            result = self.expression()
            self.expect(")")
            return result
        raise LayoutError(token, f"unsupported expression beginning with {token.text!r}")


def numeric(value, constants: dict[str, int]) -> int | str:
    if isinstance(value, int):
        return value
    if isinstance(value, tuple) and value[0] == "identifier":
        name = value[1]
        if name in constants:
            return constants[name]
        if name in {"PL_AUTO", "PL_LINKER_SIZE"}:
            return name
        raise ValueError(f"unknown numeric identifier {name}")
    if isinstance(value, tuple) and value[0] == "call":
        _, name, arguments = value
        if name in {"PL_KIB", "PL_MIB"} and len(arguments) == 1:
            return numeric(arguments[0], constants) * (1024 if name == "PL_KIB" else 1024 * 1024)
        raise ValueError(f"unsupported numeric macro {name}")
    if isinstance(value, tuple) and value[0] in {"|", "+", "-", "<<", ">>"}:
        operator, left, right = value
        a, b = numeric(left, constants), numeric(right, constants)
        if not isinstance(a, int) or not isinstance(b, int):
            raise ValueError("PL_AUTO cannot participate in arithmetic")
        return {"|": a | b, "+": a + b, "-": a - b, "<<": a << b, ">>": a >> b}[operator]
    raise ValueError("expected numeric expression")


def macro_name(value, macro: str, null_macro: str | None = None) -> str | None:
    if isinstance(value, tuple) and value[0] == "call" and value[1] == macro and len(value[2]) == 1:
        argument = value[2][0]
        if isinstance(argument, tuple) and argument[0] == "identifier":
            return argument[1]
    if null_macro and isinstance(value, tuple) and value == ("identifier", null_macro):
        return None
    raise ValueError(f"expected {macro}(name)" + (f" or {null_macro}" if null_macro else ""))


def enum_name(value) -> str:
    if isinstance(value, tuple) and value[0] == "identifier":
        return value[1]
    raise ValueError("expected enum identifier")


def parse_layout(path: Path, toolchain: str) -> tuple[list[Memory], list[Region]]:
    source = filter_conditionals(path.read_text(encoding="utf-8"), toolchain)
    raw_memories, raw_regions = Parser(lex(source)).parse_layout()
    constants = {"PL_MEMORY_RX": 1, "PL_MEMORY_RW": 2, "PL_MEMORY_RWX": 3}
    try:
        memories = [Memory(item["name"], numeric(item["origin"], constants), numeric(item["size"], constants), numeric(item["attributes"], constants)) for item in raw_memories]
        regions = [
            Region(
                item["name"], enum_name(item["type"]), macro_name(item["memory"], "PL_REF"), macro_name(item["load_memory"], "PL_REF", "PL_NO_MEMORY"),
                None if numeric(item["address"], constants) == "PL_AUTO" else numeric(item["address"], constants),
                None if numeric(item["size"], constants) == "PL_LINKER_SIZE" else numeric(item["size"], constants), numeric(item["alignment"], constants),
                macro_name(item["start_symbol"], "PL_SYMBOL"), macro_name(item["end_symbol"], "PL_SYMBOL"), macro_name(item["load_symbol"], "PL_SYMBOL", "PL_NO_SYMBOL"),
            )
            for item in raw_regions
        ]
    except (KeyError, ValueError) as error:
        raise ValueError(f"{path}: invalid layout field: {error}") from error
    validate(memories, regions)
    return memories, regions


def validate(memories: list[Memory], regions: list[Region]) -> None:
    if not memories or not regions:
        raise ValueError("layout requires pl_memory_t and pl_link_region_t entries")
    memory_names = set()
    for memory in memories:
        if not IDENTIFIER.fullmatch(memory.name) or memory.name in memory_names or not isinstance(memory.size, int) or memory.size <= 0:
            raise ValueError(f"invalid or duplicate memory {memory.name}")
        memory_names.add(memory.name)
    ordered = sorted(memories, key=lambda item: item.origin)
    for first, second in zip(ordered, ordered[1:]):
        if first.origin + first.size > second.origin:
            raise ValueError(f"memory regions overlap: {first.name} and {second.name}")
    region_names = set()
    for region in regions:
        if not IDENTIFIER.fullmatch(region.name) or region.name in region_names:
            raise ValueError(f"invalid or duplicate region {region.name}")
        if region.kind not in {"PL_LINK_INIT", "PL_LINK_RAM_CODE", "PL_LINK_RESERVED"}:
            raise ValueError(f"unsupported region type {region.kind}")
        if region.memory not in memory_names or (region.load_memory and region.load_memory not in memory_names):
            raise ValueError(f"region {region.name} references undefined memory")
        if not isinstance(region.alignment, int) or region.alignment <= 0 or region.alignment & (region.alignment - 1):
            raise ValueError(f"region {region.name} alignment must be a non-zero power of two")
        if region.kind == "PL_LINK_RESERVED" and not isinstance(region.size, int):
            raise ValueError(f"reserved region {region.name} requires fixed size")
        if region.kind == "PL_LINK_RAM_CODE" and not region.load_memory:
            raise ValueError(f"RAM code region {region.name} requires load memory")
        region_names.add(region.name)


def section_name(region: Region) -> str:
    return f".pl.{region.name}"


def selector(region: Region) -> str | None:
    return {"PL_LINK_INIT": f".pl.init.{region.name}.*", "PL_LINK_RAM_CODE": f".pl.ram_code.{region.name}"}.get(region.kind)


def gnu_linker(memories: list[Memory], regions: list[Region]) -> str:
    attributes = {1: "rx", 2: "rw", 3: "rwx"}
    lines = ["/* Generated by tools/generate_linker.py. Do not edit. */", "MEMORY", "{"]
    lines.extend(f"  {memory.name} ({attributes[memory.attributes]}) : ORIGIN = 0x{memory.origin:08X}, LENGTH = 0x{memory.size:X}" for memory in memories)
    lines.extend(["}", "", "SECTIONS", "{"])
    for region in regions:
        address = f" 0x{region.address:08X}" if region.address is not None else ""
        no_load = " (NOLOAD)" if region.kind == "PL_LINK_RESERVED" else ""
        lines.extend([f"  {section_name(region)}{address}{no_load} : ALIGN({region.alignment})", "  {", f"    {region.start_symbol} = .;"])
        if region.kind == "PL_LINK_RESERVED":
            lines.append(f"    . += 0x{region.size:X};")
        elif region.kind == "PL_LINK_INIT":
            lines.append(f"    KEEP(*(SORT_BY_NAME({selector(region)})))")
        else:
            lines.append(f"    *({selector(region)})")
        lines.extend([f"    {region.end_symbol} = .;", f"  }} > {region.memory}" + (f" AT > {region.load_memory}" if region.load_memory and region.memory != region.load_memory else "")])
        if region.load_symbol:
            lines.append(f"  {region.load_symbol} = LOADADDR({section_name(region)});")
        lines.append("")
    return "\n".join(lines + ["}", ""])


def scatter_file(memories: list[Memory], regions: list[Region]) -> str:
    """Generate Arm Compiler scatter syntax from the backend-neutral region model."""
    memory_by_name = {memory.name: memory for memory in memories}
    grouped: dict[str, list[Region]] = {}
    for region in regions:
        grouped.setdefault(region.load_memory or region.memory, []).append(region)
    lines = ["; Generated by tools/generate_linker.py. Do not edit."]
    fallback_ro_added = False
    for load_name, group in grouped.items():
        load_memory = memory_by_name[load_name]
        lines.extend([f"LR_{load_name} 0x{load_memory.origin:08X} 0x{load_memory.size:X}", "{"])
        local_regions = [region for region in group if region.memory == load_name]
        relocated_regions = [region for region in group if region.memory != load_name]
        for region in local_regions:
            runtime = memory_by_name[region.memory]
            address = region.address if region.address is not None else runtime.origin
            if region.kind == "PL_LINK_RESERVED":
                lines.append(f"  ER_{region.name.upper()} 0x{address:08X} EMPTY 0x{region.size:X} {{ }}")
                continue
            lines.extend([f"  ER_{region.name.upper()} 0x{address:08X} ALIGN {region.alignment}", "  {"])
            if selector(region):
                lines.append(f"    *({selector(region)})")
            lines.append("  }")
        if not fallback_ro_added and load_memory.attributes & 0x1:
            lines.extend(["  ER_DEFAULT_RO +0", "  {", "    .ANY (+RO)", "  }"])
            fallback_ro_added = True
        for region in relocated_regions:
            runtime = memory_by_name[region.memory]
            address = region.address if region.address is not None else runtime.origin
            if region.kind == "PL_LINK_RESERVED":
                lines.append(f"  ER_{region.name.upper()} 0x{address:08X} EMPTY 0x{region.size:X} {{ }}")
                continue
            lines.extend([f"  ER_{region.name.upper()} 0x{address:08X} ALIGN {region.alignment}", "  {"])
            if selector(region):
                lines.append(f"    *({selector(region)})")
            lines.append("  }")
        lines.extend(["}", ""])
    return "\n".join(lines)


def symbols_header(regions: list[Region], toolchain: str) -> str:
    lines = ["/* Generated by tools/generate_linker.py. Do not edit. */", "#ifndef PL_LINKER_SYMBOLS_H", "#define PL_LINKER_SYMBOLS_H", "", "#include <stdint.h>", "#include \"pl_linker.h\"", ""]
    for region in regions:
        entry_type = "pl_init_entry_t" if region.kind == "PL_LINK_INIT" else "uint8_t"
        if toolchain == "armclang":
            execution_region = f"ER_{region.name.upper()}"
            lines.extend([
                f"extern {entry_type} {region.start_symbol}[] __asm(\"Image$${execution_region}$$Base\");",
                f"extern {entry_type} {region.end_symbol}[] __asm(\"Image$${execution_region}$$Limit\");",
            ])
        else:
            lines.extend([f"extern {entry_type} {region.start_symbol}[];", f"extern {entry_type} {region.end_symbol}[];"])
        if region.load_symbol:
            if toolchain == "armclang":
                execution_region = f"ER_{region.name.upper()}"
                lines.append(f"extern const uint8_t {region.load_symbol}[] __asm(\"Load$${execution_region}$$Base\");")
            else:
                lines.append(f"extern const uint8_t {region.load_symbol}[];")
        lines.append("")
    return "\n".join(lines + ["#endif", ""])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("layout", type=Path, help="C source containing pl_memory_t and pl_link_region_t arrays")
    parser.add_argument("--toolchain", choices=("gnu", "armclang"), required=True)
    parser.add_argument("--linker-out", type=Path, required=True)
    parser.add_argument("--header-out", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        memories, regions = parse_layout(arguments.layout, arguments.toolchain)
        linker = gnu_linker(memories, regions) if arguments.toolchain == "gnu" else scatter_file(memories, regions)
    except (OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    for output, content in ((arguments.linker_out, linker), (arguments.header_out, symbols_header(regions, arguments.toolchain))):
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content, encoding="utf-8")
        print(f"generated {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())