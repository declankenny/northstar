"""Generate the ref_locales rows (and the migration that loads them) from CLDR. A developer tool: run by a person, never at run time.

    python scripts/generate_locales.py            # print the rows it would write, after probing Node's Intl
    python scripts/generate_locales.py --write    # write northstar/migrations/0011_locales.sql

It needs Babel (pinned in the `dev` extra) and, to probe, Node. See docs/design/locale.md, "The generator".

The application never reads CLDR: it reads the table the migration creates. A locale is added to SUPPORTED, run through this
tool, and the migration it writes is reviewed. The tool refuses a locale whose conventions go beyond the rules Northstar
applies (groups of three digits, grouping from four digits, an ASCII minus, a date pattern made of the template pieces below),
so that nothing is silently flattened into the model.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

from babel import Locale
from babel.core import get_cldr_version
from babel.numbers import parse_pattern

# The hand-checked allowlist. A locale must be here before the tool will generate it.
SUPPORTED = {
    "en-US": "English (United States)",
    "en-GB": "English (United Kingdom)",
    "de-DE": "German (Germany)",
    "fr-FR": "French (France)",
    "de-CH": "German (Switzerland)",
    "ja-JP": "Japanese (Japan)",
}

# The pieces of a Northstar date template, and the CLDR pattern letters that become them. Anything else is refused.
DATE_TOKENS = {"y": "{year}", "M": "{month}", "MM": "{month2}", "MMM": "{month_short}", "d": "{day}", "dd": "{day2}"}

# CLDR's currency spacing for an alphabetic currency code next to a digit is a no-break space (the root locale's
# currencySpacing), unless the locale's own pattern already puts a literal between them. Babel does not expose it, so the probe
# below confirms it through Node's Intl for every locale.
NO_BREAK_SPACE = "\u00a0"

# Marks that look alike and are read as the same group mark when typed (see docs/design/locale.md, "The parser").
ALIASES = [set(" \u00a0\u202f"), set("'\u2019\u02bc")]

MIGRATION = Path(__file__).resolve().parent.parent / "northstar" / "migrations" / "0011_locales.sql"
TEMPLATE = Path(__file__).resolve().parent / "0011_locales.sql.tpl"


class Unsupported(Exception):
    """A locale's conventions go beyond what Northstar applies."""


def date_template(pattern: str, tag: str) -> str:
    """CLDR's medium date pattern, such as 'dd.MM.y', as a Northstar template, such as '{day2}.{month2}.{year}'."""
    out = []
    for run, literal in re.findall(r"([A-Za-z]+)|([^A-Za-z]+)", pattern):
        if literal:
            if "'" in literal:
                raise Unsupported(f"{tag}: the date pattern {pattern!r} has quoted text")
            out.append(literal)
        elif run in DATE_TOKENS:
            out.append(DATE_TOKENS[run])
        else:
            raise Unsupported(f"{tag}: the date pattern {pattern!r} uses {run!r}, which the template does not have")
    return "".join(out)


def currency_layout(pattern: str, tag: str) -> tuple[str, str]:
    """('prefix' or 'suffix', the text between a currency code and the number) from CLDR's currency pattern."""
    positive = pattern.split(";")[0]
    if positive.count("\u00a4") != 1:
        raise Unsupported(f"{tag}: the currency pattern {positive!r} does not have exactly one currency sign")
    match = re.fullmatch(r"(\u00a4)([^#0]*)([#0,.]+)", positive)
    if match:
        return "prefix", match.group(2) or NO_BREAK_SPACE
    match = re.fullmatch(r"([#0,.]+)([^#0\u00a4]*)(\u00a4)", positive)
    if match:
        return "suffix", match.group(2) or NO_BREAK_SPACE
    raise Unsupported(f"{tag}: the currency pattern {positive!r} puts text around the number")


def babel_row(tag: str) -> dict:
    locale = Locale.parse(tag.replace("-", "_"))
    symbols = locale.number_symbols["latn"]
    if symbols["minusSign"] != "-":
        raise Unsupported(f"{tag}: the minus sign is {symbols['minusSign']!r}, and Northstar applies an ASCII minus")
    grouping = parse_pattern(locale.decimal_formats[None]).grouping
    if grouping != (3, 3):
        raise Unsupported(f"{tag}: the grouping is {grouping}, and Northstar applies groups of three")
    position, spacing = currency_layout(locale.currency_formats["standard"].pattern, tag)
    return {
        "tag": tag,
        "label": SUPPORTED[tag],
        "decimal_mark": symbols["decimal"],
        "group_mark": symbols["group"],
        "date_template": date_template(locale.date_formats["medium"].pattern, tag),
        "currency_position": position,
        "currency_code_spacing": spacing,
        "cldr_version": str(get_cldr_version()),
    }


def rows() -> list[dict]:
    """The rows Babel gives, in tag order. Used by the generator and by the test that the migrated table matches it."""
    return [babel_row(tag) for tag in sorted(SUPPORTED)]


PROBE = """
const tag = process.argv[1];
const parts = new Intl.NumberFormat(tag).formatToParts(1234567.5);
const find = (type, list = parts) => (list.find((p) => p.type === type) || {}).value;
const four = new Intl.NumberFormat(tag).formatToParts(1234);
const minus = (new Intl.NumberFormat(tag).formatToParts(-1).find((p) => p.type === 'minusSign') || {}).value;
const cur = new Intl.NumberFormat(tag, { style: 'currency', currency: 'JPY', currencyDisplay: 'code', minimumFractionDigits: 0 })
  .formatToParts(1234);
const idx = (type) => cur.findIndex((p) => p.type === type);
const between = idx('currency') < idx('integer')
  ? cur.slice(idx('currency') + 1, idx('integer')).filter((p) => p.type === 'literal').map((p) => p.value).join('')
  : cur.slice(idx('integer') + 1, idx('currency')).filter((p) => p.type === 'literal').map((p) => p.value).join('');
console.log(JSON.stringify({ group: find('group'), decimal: find('decimal'), minus, groupsAtFour: four.some((p) => p.type === 'group'),
  groupSizes: parts.filter((p) => p.type === 'integer').map((p) => p.value.length), position: idx('currency') < idx('integer') ? 'prefix' : 'suffix', between }));
"""


def same_mark(a: str, b: str) -> bool:
    return a == b or any(a in group and b in group for group in ALIASES)


def probe(row: dict) -> None:
    """Check the row against what Node's Intl does for the same locale, which also shows the rules Babel cannot see."""
    result = subprocess.run(["node", "-e", PROBE, row["tag"]], capture_output=True, encoding="utf-8", check=True)
    seen = json.loads(result.stdout)
    problems = []
    if seen["decimal"] != row["decimal_mark"]:
        problems.append(f"decimal mark {row['decimal_mark']!r} against {seen['decimal']!r}")
    if not same_mark(seen["group"], row["group_mark"]):
        problems.append(f"group mark {row['group_mark']!r} against {seen['group']!r}")
    if not seen["groupsAtFour"]:
        problems.append("Intl does not group a four-digit number, and Northstar applies grouping from four digits")
    if seen["groupSizes"][1:] and any(size != 3 for size in seen["groupSizes"][1:]):
        problems.append("Intl does not group by three")
    if seen["minus"] not in (None, "-"):
        problems.append(f"minus sign {seen['minus']!r}")
    if seen["position"] != row["currency_position"]:
        problems.append(f"currency position {row['currency_position']} against {seen['position']}")
    if seen["between"] != row["currency_code_spacing"]:
        problems.append(f"currency spacing {row['currency_code_spacing']!r} against {seen['between']!r}")
    if problems:
        raise Unsupported(f"{row['tag']}: Node's Intl disagrees: " + "; ".join(problems))


def sql_text(text: str) -> str:
    """A SQL expression for the text, with every character outside printable ASCII written as char(n), so the migration can be
    read without invisible characters."""
    pieces, run = [], ""
    for ch in text:
        if 32 <= ord(ch) < 127:
            run += ch.replace("'", "''")
        else:
            if run:
                pieces.append(f"'{run}'")
                run = ""
            pieces.append(f"char({ord(ch)})")
    if run or not pieces:
        pieces.append(f"'{run}'")
    return " || ".join(pieces)


def comment_for(text: str) -> str:
    names = {0xA0: "no-break space", 0x202F: "narrow no-break space", 0x2019: "right single quotation mark", 0x20: "space"}
    odd = [f"{ord(c)} = U+{ord(c):04X} {names.get(ord(c), 'character')}" for c in dict.fromkeys(text) if not 32 < ord(c) < 127]
    return ", ".join(odd)


def migration_text(generated: list[dict]) -> str:
    lines, notes = [], []
    for r in generated:
        fields = ", ".join(sql_text(r[k]) for k in (
            "tag", "label", "decimal_mark", "group_mark", "date_template", "currency_position", "currency_code_spacing",
            "cldr_version"))
        lines.append(f"    ({fields})")
        for key in ("group_mark", "currency_code_spacing"):
            odd = comment_for(r[key])
            if odd:
                notes.append(f"--   {r['tag']} {key}: {odd}")
    template = TEMPLATE.read_text(encoding="utf-8")
    return (template.replace("@@CLDR@@", generated[0]["cldr_version"])
            .replace("@@NOTES@@", "\n".join(dict.fromkeys(notes)))
            .replace("@@ROWS@@", ",\n".join(lines)))


def main(argv: list[str]) -> int:
    generated = rows()
    for row in generated:
        probe(row)
    if "--write" in argv:
        MIGRATION.write_text(migration_text(generated), encoding="utf-8", newline="\n")
        print(f"Wrote {MIGRATION} with {len(generated)} locales from CLDR {generated[0]['cldr_version']}.")
    else:
        for row in generated:
            print(json.dumps(row, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
