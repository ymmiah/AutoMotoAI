"""Document Assistant professional publishing: source-owned templates and citations.

No external lookups, generated bibliographies or untrusted network sources.
References are supplied by the author, stored with their native document and
resolved deterministically at export. All user input is data, not executable.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from automoto import office_build

CITE_RE = re.compile(r"\[@([a-z][a-z0-9_-]{0,31})\]")
CITE_ANY = re.compile(r"\[@([^\]]*)\]")
MAX_REFERENCES = 60
MAX_ENTRIES = 120
TEMPLATES: dict[str, dict[str, str]] = {
    "academic-report": {
        "name": "Academic report",
        "description": "Evidence-based university report with introduction, methodology, analysis and conclusion.",
        "source": "# [Report title]\n\n## Executive summary\n\n[Summarise the purpose and findings.]\n\n## Introduction\n\n[Define the question and scope.]\n\n## Methodology\n\n[Describe evidence sources and any limitations.]\n\n## Findings and analysis\n\n[Support each factual claim with a verified source.]\n\n## Conclusion\n\n[Draw only conclusions supported by the analysis.]\n",
    },
    "business-proposal": {
        "name": "Business proposal",
        "description": "Structured commercial proposal with value, delivery, risks and next steps.",
        "source": "# [Proposal title]\n\n## Executive summary\n\n[Describe the customer's problem and proposed outcome.]\n\n## Objectives\n\n[Define measurable objectives.]\n\n## Recommended approach\n\n[Explain scope and delivery.]\n\n## Budget and assumptions\n\n[Enter verified costs, terms and assumptions.]\n\n## Risks and dependencies\n\n[Identify realistic risks.]\n\n## Next steps\n\n[Identify actions and responsible owners.]\n",
    },
    "meeting-minutes": {
        "name": "Meeting minutes",
        "description": "Clear record of attendees, agenda, decisions, actions and owners.",
        "source": "# [Meeting name]\n\nDate: [Date]\nLocation: [Location or meeting link]\nChair: [Name]\nAttendees: [Names]\n\n## Agenda\n\n- [Agenda item]\n\n## Discussion\n\n[Record verified discussion points.]\n\n## Decisions\n\n- [Decision and rationale]\n\n## Actions\n\n| Action | Owner | Deadline |\n| --- | --- | --- |\n| [Task] | [Person] | [Date] |\n\n## Next meeting\n\n[Agreed details]\n",
    },
    "formal-letter": {
        "name": "Formal letter",
        "description": "British-English letter with reference, subject, message and signature.",
        "source": "# [Subject of the letter]\n\n[Sender's address]\n\n[Date]\n\n[Recipient's name and address]\n\nDear [Title and surname],\n\n[State the purpose of the letter clearly.]\n\n[Include supporting information and the requested action.]\n\nYours sincerely,\n\n[Full name]\n[Position, if relevant]\n",
    },
}


class Reference(BaseModel):
    """Entirely user-entered source details; this is not a scholarly database."""
    model_config = ConfigDict(extra="forbid")
    id: str = Field(..., pattern=r"^[a-z][a-z0-9_-]{0,31}$")
    authors: str = Field(..., min_length=1, max_length=200)
    author_label: str | None = Field(None, max_length=100)
    year: str = Field(..., pattern=r"^(?:[12][0-9]{3}[a-z]?|n\.d\.)$")
    title: str = Field(..., min_length=1, max_length=320)
    type: Literal["book", "journal", "web", "report"] = "web"
    journal: str | None = Field(None, max_length=200)
    publisher: str | None = Field(None, max_length=200)
    volume: str | None = Field(None, max_length=25)
    issue: str | None = Field(None, max_length=25)
    pages: str | None = Field(None, max_length=35)
    url: str | None = Field(None, max_length=600)
    doi: str | None = Field(None, max_length=120)
    accessed: str | None = Field(None, max_length=60)

    def format(self, style: str, number: int | None = None) -> str:
        if style == "harvard":
            fields = self.model_dump(exclude_none=True)
            return office_build.harvard(fields)
        if style != "ieee" or number is None:
            raise ValueError("unsupported reference style")
        # IEEE numbering follows the order of first appearance in the text.
        title = self.title.replace('"', "'")
        parts = [f'[{number}] {self.authors}, "{title},"']
        if self.type == "journal" and self.journal:
            parts.append(self.journal + ",")
        elif self.publisher:
            parts.append(self.publisher + ",")
        if self.volume:
            parts.append("vol. " + self.volume + ",")
        if self.issue:
            parts.append("no. " + self.issue + ",")
        if self.pages:
            parts.append("pp. " + self.pages + ",")
        parts.append(self.year + ".")
        if self.doi:
            parts.append("doi: " + self.doi + ".")
        if self.url:
            parts.append("Available: " + self.url + ".")
        if self.accessed:
            parts.append("Accessed: " + self.accessed + ".")
        return " ".join(parts)


class PublicationOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference_style: Literal["harvard", "ieee"] = "harvard"
    author: str = Field("", max_length=150)
    institution: str = Field("", max_length=150)
    document_date: str = Field("", max_length=70)
    header: str = Field("", max_length=150)
    footer: str = Field("", max_length=150)
    cover_page: bool = False
    contents_page: bool = False
    template: Literal["", "academic-report", "business-proposal", "meeting-minutes", "formal-letter"] = ""
    references: list[Reference] = Field(default_factory=list, max_length=MAX_REFERENCES)


def _label(reference: Reference) -> str:
    if reference.author_label and reference.author_label.strip():
        return reference.author_label.strip()
    # Preserve the literal user-entered author surname when supplied as
    # 'Surname, Initial'. For other names use the unmodified user entry.
    return reference.authors.split(",")[0].strip() if "," in reference.authors else reference.authors.strip()


def compile_publication(markdown: str, publication: PublicationOptions) -> tuple[str, list[dict[str, Any]], list[str]]:
    """Resolve source-reference markers; never create bibliographic facts."""
    refs: dict[str, Reference] = {}
    for ref in publication.references:
        if ref.id in refs:
            raise ValueError("duplicate source reference identifier: " + ref.id)
        if ref.url and not re.fullmatch(r"https://[^\s@<>]+", ref.url):
            raise ValueError("reference URLs must be HTTPS and have no credentials")
        if ref.doi and not re.fullmatch(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", ref.doi):
            raise ValueError("invalid DOI format")
        refs[ref.id] = ref
    identifiers = CITE_RE.findall(markdown)
    if len(identifiers) > 250:
        raise ValueError("document contains too many source citations")
    if len(CITE_ANY.findall(markdown)) != len(identifiers):
        raise ValueError("one or more source citations use an invalid identifier")
    unknown = sorted(set(identifiers) - set(refs))
    if unknown:
        raise ValueError("unknown source reference: " + ", ".join(unknown[:5]))
    used_ids = list(dict.fromkeys(identifiers))
    all_ids = used_ids + [key for key in refs if key not in used_ids]
    numbers = {key: index + 1 for index, key in enumerate(all_ids)}
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if publication.reference_style == "ieee":
            return f"[{numbers[key]}]"
        ref = refs[key]
        return f"({_label(ref)}, {ref.year})"
    final_markdown = CITE_RE.sub(replace, markdown)
    if publication.reference_style == "harvard":
        ordered = sorted(refs.values(), key=lambda r: (r.authors.casefold(), r.year, r.title.casefold()))
        entries = [r.format("harvard") for r in ordered]
    else:
        entries = [refs[key].format("ieee", numbers[key]) for key in all_ids]
    refs_block = [{"type": "references", "title": "References",
                   "items": entries, "sort": False}] if entries else []
    warnings = []
    if refs and not used_ids:
        warnings.append("No source-reference markers are used in the body; all references will be listed as uncited.")
    elif len(refs) > len(used_ids):
        warnings.append(f"{len(refs) - len(used_ids)} reference(s) are not cited in the body.")
    if len(markdown) > 10_000 and not used_ids and publication.template == "academic-report":
        warnings.append("Long academic report has no cited sources; verify that evidence is documented.")
    return final_markdown, refs_block, warnings


def publishing_spec(name: str, markdown: str, spec: dict[str, Any],
                    publication: PublicationOptions) -> tuple[dict[str, Any], list[str]]:
    """Adds cover, TOC, formatted references to the existing Office DOCX spec."""
    compiled, refs, warnings = compile_publication(markdown, publication)
    native = office_build.markdown_to_spec(compiled)
    blocks = native["blocks"]
    if publication.contents_page:
        blocks.insert(0, {"type": "toc", "title": "Contents", "levels": 3, "page_break": True})
    if publication.cover_page:
        blocks.insert(0, {"type": "title_page", "title": name,
                          "author": publication.author,
                          "institution": publication.institution,
                          "date": publication.document_date})
    if refs:
        blocks.extend(refs)
    if len(blocks) > 1000:
        raise ValueError("document exceeds the 1000-block publishing limit")
    output = dict(spec)
    output["blocks"] = blocks
    output["header"] = publication.header
    output["footer"] = publication.footer
    output["properties"] = {**spec.get("properties", {}), "author": publication.author}
    if publication.contents_page and not any(b.get("type") == "heading" for b in blocks):
        warnings.append("Contents requested without headings.")
    if publication.contents_page and not office_build.lo_available():
        warnings.append("Contents page numbers require a Word field update or local LibreOffice.")
    if re.search(r"\[[^\]\n]{2,70}\]", markdown):
        warnings.append("Bracketed template placeholders remain; check them before publishing.")
    return output, warnings
