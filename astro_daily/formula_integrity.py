from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

FORMULA_HEADING = "#### 公式与推导"
FORMULA_BOUNDARY_RE = re.compile(r"^####\s+")
LATEX_COMMAND_RE = re.compile(r"\\[A-Za-z]+")


@dataclass(frozen=True)
class FormulaIntegrityIssue:
    section_title: str
    line_number: int
    kind: str
    message: str
    repaired: bool
    snippet: str


@dataclass
class FormulaIntegrityResult:
    checked_sections: int = 0
    issues: list[FormulaIntegrityIssue] = field(default_factory=list)

    @property
    def issue_count(self) -> int:
        return len(self.issues)

    @property
    def repaired_count(self) -> int:
        return sum(1 for issue in self.issues if issue.repaired)

    @property
    def unresolved_count(self) -> int:
        return sum(1 for issue in self.issues if not issue.repaired)


def repair_report_latex_formulas(md_path: Path, *, repair: bool = True) -> FormulaIntegrityResult:
    original = md_path.read_text(encoding="utf-8")
    repaired_text, result = repair_formula_sections(original, repair=repair)
    if repair and repaired_text != original:
        md_path.write_text(repaired_text, encoding="utf-8")
    for issue in result.issues:
        message = (
            "Formula integrity repaired %s at line %s in %s: %s"
            if issue.repaired
            else "Formula integrity unresolved %s at line %s in %s: %s"
        )
        log = logger.info if issue.repaired else logger.warning
        log(message, issue.kind, issue.line_number, issue.section_title, issue.snippet)
    return result


def repair_formula_sections(markdown_text: str, *, repair: bool = True) -> tuple[str, FormulaIntegrityResult]:
    lines = markdown_text.split("\n")
    output: list[str] = []
    result = FormulaIntegrityResult()
    index = 0
    while index < len(lines):
        line = lines[index]
        output.append(line)
        if line.strip() != FORMULA_HEADING:
            index += 1
            continue

        section_start = index + 1
        section_end = section_start
        while section_end < len(lines) and not _is_section_boundary(lines[section_end]):
            section_end += 1

        section_lines = lines[section_start:section_end]
        repaired_lines, issues = _repair_section(section_lines, section_start + 1, repair=repair)
        output.extend(repaired_lines)
        result.checked_sections += 1
        result.issues.extend(issues)
        index = section_end

    return "\n".join(output), result


def _is_section_boundary(line: str) -> bool:
    stripped = line.strip()
    return stripped == "</details>" or bool(FORMULA_BOUNDARY_RE.match(stripped))


def _repair_section(lines: list[str], start_line_number: int, *, repair: bool) -> tuple[list[str], list[FormulaIntegrityIssue]]:
    repaired = list(lines)
    issues: list[FormulaIntegrityIssue] = []

    display_positions = _token_positions("\n".join(repaired), "$$")
    if len(display_positions) % 2 == 1 and _looks_formula_like("\n".join(repaired)[display_positions[-1] + 2 :]):
        issues.append(_issue(start_line_number, "missing_display_dollar", "missing closing $$", repair, repaired[-1] if repaired else "$$"))
        if repair:
            repaired.append("$$")
    elif len(display_positions) % 2 == 1:
        issues.append(_issue(start_line_number, "ambiguous_display_dollar", "unmatched $$ left unchanged", False, repaired[-1] if repaired else "$$"))

    bracket_open = "\n".join(repaired).count("\\[")
    bracket_close = "\n".join(repaired).count("\\]")
    if bracket_open == bracket_close + 1:
        issues.append(_issue(start_line_number, "missing_display_bracket", "missing closing \\]", repair, repaired[-1] if repaired else "\\["))
        if repair:
            repaired.append("\\]")
    elif bracket_open > bracket_close:
        issues.append(_issue(start_line_number, "ambiguous_display_bracket", "unmatched \\[ left unchanged", False, repaired[-1] if repaired else "\\["))

    for offset, line in enumerate(list(repaired)):
        line_number = start_line_number + offset
        new_line, line_issues = _repair_line(line, line_number, repair=repair)
        repaired[offset] = new_line
        issues.extend(line_issues)

    return repaired, issues


def _repair_line(line: str, line_number: int, *, repair: bool) -> tuple[str, list[FormulaIntegrityIssue]]:
    if _is_markdown_link_or_image(line):
        return line, []

    issues: list[FormulaIntegrityIssue] = []
    current = line

    paren_opens = current.count("\\(")
    paren_closes = current.count("\\)")
    if paren_opens == paren_closes + 1 and _looks_formula_like(current.rsplit("\\(", 1)[-1]):
        issues.append(_issue(line_number, "missing_inline_paren", "missing closing \\)", repair, current))
        if repair:
            current += "\\)"
    elif paren_opens > paren_closes:
        issues.append(_issue(line_number, "ambiguous_inline_paren", "unmatched \\( left unchanged", False, current))

    dollar_positions = _single_dollar_positions(current)
    if len(dollar_positions) == 1 and _looks_formula_like(current[dollar_positions[0] + 1 :]) and not _inside_markdown_url(current, dollar_positions[0]):
        issues.append(_issue(line_number, "missing_inline_dollar", "missing closing $", repair, current))
        if repair:
            current += "$"
    elif len(dollar_positions) % 2 == 1:
        issues.append(_issue(line_number, "ambiguous_inline_dollar", "unmatched $ left unchanged", False, current))

    current, span_issues = _repair_math_spans(current, line_number, repair=repair)
    issues.extend(span_issues)

    if not _has_math_delimiter(current) and _looks_bare_latex(current):
        issues.append(_issue(line_number, "bare_latex", "possible bare LaTeX left unchanged", False, current))

    return current, issues


def _repair_math_spans(line: str, line_number: int, *, repair: bool) -> tuple[str, list[FormulaIntegrityIssue]]:
    issues: list[FormulaIntegrityIssue] = []
    current = line
    for pattern in [r"\$\$([\s\S]*?)\$\$", r"(?<!\$)\$(?!\$)(.*?)(?<!\$)\$(?!\$)", r"\\\((.*?)\\\)", r"\\\[(.*?)\\\]"]:
        current = re.sub(pattern, lambda match: _repair_span_match(match, line_number, repair, issues), current)
    return current, issues


def _repair_span_match(match: re.Match[str], line_number: int, repair: bool, issues: list[FormulaIntegrityIssue]) -> str:
    content = match.group(1)
    fixed = _append_missing_closers(content)
    if fixed == content:
        return match.group(0)
    issues.append(_issue(line_number, "missing_group_closer", "missing closing group delimiter", repair, match.group(0)))
    if not repair:
        return match.group(0)
    start = match.group(0)[: match.start(1) - match.start(0)]
    end = match.group(0)[match.end(1) - match.start(0) :]
    return f"{start}{fixed}{end}"


def _append_missing_closers(content: str) -> str:
    pairs = {"{": "}", "(": ")", "[": "]"}
    closers = {value: key for key, value in pairs.items()}
    stack: list[str] = []
    index = 0
    while index < len(content):
        char = content[index]
        if char == "\\":
            index += 2
            continue
        if char in pairs:
            stack.append(char)
        elif char in closers:
            if not stack or stack[-1] != closers[char]:
                return content
            stack.pop()
        index += 1
    if not stack or len(stack) > 2:
        return content
    return content + "".join(pairs[char] for char in reversed(stack))


def _single_dollar_positions(text: str) -> list[int]:
    positions: list[int] = []
    index = 0
    while index < len(text):
        if text[index] == "$" and (index == 0 or text[index - 1] != "\\"):
            previous_is_dollar = index > 0 and text[index - 1] == "$"
            next_is_dollar = index + 1 < len(text) and text[index + 1] == "$"
            if not previous_is_dollar and not next_is_dollar:
                positions.append(index)
        index += 1
    return positions


def _token_positions(text: str, token: str) -> list[int]:
    positions: list[int] = []
    index = 0
    while True:
        index = text.find(token, index)
        if index == -1:
            return positions
        if index == 0 or text[index - 1] != "\\":
            positions.append(index)
        index += len(token)


def _looks_formula_like(text: str) -> bool:
    return bool(LATEX_COMMAND_RE.search(text) or any(marker in text for marker in ["_", "^", "=", "\\sim", "\\propto", "\\approx", "\\frac"]))


def _looks_bare_latex(text: str) -> bool:
    return bool(LATEX_COMMAND_RE.search(text) and any(marker in text for marker in ["_", "^", "=", "\\sim", "\\propto", "\\approx", "\\frac"]))


def _has_math_delimiter(text: str) -> bool:
    return any(token in text for token in ["$", "\\(", "\\)", "\\[", "\\]"])


def _is_markdown_link_or_image(text: str) -> bool:
    stripped = text.strip()
    return stripped.startswith("[") or stripped.startswith("![")


def _inside_markdown_url(text: str, position: int) -> bool:
    open_paren = text.rfind("](", 0, position)
    close_paren = text.find(")", position)
    return open_paren != -1 and close_paren != -1


def _issue(line_number: int, kind: str, message: str, repaired: bool, snippet: str) -> FormulaIntegrityIssue:
    return FormulaIntegrityIssue(
        section_title=FORMULA_HEADING.removeprefix("#### "),
        line_number=line_number,
        kind=kind,
        message=message,
        repaired=repaired,
        snippet=snippet.strip()[:160],
    )
