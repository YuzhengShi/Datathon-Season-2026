"""Invented source documents for the demo dataset (HTML pages, a text PDF, a scanned PDF).

Every document states plainly that it is synthetic. Section ids (``anchor``) become the
``#fragment`` of each opportunity's ``official_url`` so one page can hold many awards.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from html import escape

BANNER = (
    "SYNTHETIC DEMONSTRATION DATA. This page is invented for software testing. "
    "It is not a real funder, award or policy."
)
APPLY_PORTAL = "Apply through the Demo College awards portal."
APPLY_FOUNDATION = "Apply through the Demo Foundation website."
ELIGIBLE_ALL = "Eligibility: First Nations, Inuit or Métis students."


@dataclass(frozen=True)
class Section:
    anchor: str
    heading: str
    paragraphs: tuple[str, ...]


@dataclass(frozen=True)
class Page:
    key: str
    source_id: str
    url: str
    title: str
    modified: str
    sections: tuple[Section, ...]
    role: str = "synthetic_award_page"


def S(anchor: str, heading: str, *paragraphs: str) -> Section:  # noqa: N802 - compact table syntax
    return Section(anchor, heading, tuple(paragraphs))


COLLEGE = Page(
    "college", "demo_college_awards", "https://demo.invalid/college/awards",
    "Demo College Indigenous Awards (synthetic)", "2026-10-01",
    (
        S("supported-award", "Demo Supported Award",
          "The Demo Supported Award recognizes Indigenous undergraduate students at Demo College.",
          "Eligibility: applicants must self-identify as First Nations, Inuit or Métis, be enrolled at "
          "Demo College, and be in an undergraduate program.",
          "Value: $2,500 CAD, awarded once per year.",
          "Applications open September 1, 2026. The deadline is November 15, 2026 at 11:59 p.m. Pacific Time.",
          "Required documents: a short essay and proof of enrolment.",
          APPLY_PORTAL),
        S("clarification-award", "Demo Clarification Award",
          "Eligibility: open to students who self-identify as First Nations, Inuit or Métis and are "
          "enrolled full-time at Demo College.",
          "Value: $1,000 CAD.",
          "Applications open October 1, 2026 and close on December 1, 2026 (Pacific Time).",
          APPLY_PORTAL),
        S("first-nations-registered-award", "Demo First Nations Registration Award",
          "Eligibility: applicants must be registered First Nations persons under the Indian Act. "
          "Self-identification alone is not enough.",
          "Value: $1,500 CAD.",
          "The application deadline is January 31, 2027 (Pacific Time).",
          APPLY_PORTAL),
        S("metis-citizen-award", "Demo Métis Citizenship Award",
          "Eligibility: applicants must be citizens of the Demo Métis Authority.",
          "Value: $1,200 CAD.",
          "The application deadline is February 15, 2027 (Pacific Time).",
          APPLY_PORTAL),
        S("inuit-beneficiary-award", "Demo Inuit Beneficiary Award",
          "Eligibility: applicants must be beneficiaries of the Demo Inuit Land Claim Agreement.",
          "Value: $1,800 CAD.",
          "The application deadline is February 28, 2027 (Pacific Time).",
          APPLY_PORTAL),
        S("residence-community-award", "Demo Residence and Community Award",
          "Eligibility: applicants must belong to Demo First Nation, currently live in British Columbia, "
          "and attend a school located in Alberta.",
          "Value: $900 CAD.",
          "The application deadline is March 15, 2027 (Pacific Time).",
          APPLY_PORTAL),
        S("preference-award", "Demo Environmental Preference Award",
          "Eligibility: open to First Nations, Inuit and Métis undergraduate students.",
          "Preference is given to applicants studying environmental science.",
          "Value: $2,000 CAD.",
          "The application deadline is April 1, 2027 (Pacific Time).",
          APPLY_PORTAL),
        S("or-rule-award", "Demo Either-Or Award",
          "Eligibility: applicants must self-identify as First Nations, Inuit or Métis and either belong "
          "to Demo First Nation or attend Demo College.",
          "Value: $1,100 CAD.",
          "The application deadline is April 15, 2027 (Pacific Time).",
          APPLY_PORTAL),
        S("or-unknown-branch-award", "Demo Either-Or Local Award",
          "Eligibility: applicants must self-identify as First Nations, Inuit or Métis and either attend "
          "Demo College or meet another requirement that the local band office decides.",
          "Value: $700 CAD.",
          "The application deadline is April 30, 2027 (Pacific Time).",
          APPLY_PORTAL),
        S("multi-cycle-award", "Demo Two-Cycle Award",
          "The 2019-20 intake closed on March 1, 2020 (Pacific Time).",
          "The 2026-27 intake opens September 15, 2026 and closes on May 1, 2027 (Pacific Time).",
          "Eligibility for both intakes: self-identified First Nations, Inuit or Métis students at Demo College.",
          "Value: $800 CAD in each intake.",
          APPLY_PORTAL),
        S("college-directory", "Demo College Awards Directory",
          "This directory lists the Demo College awards described on this page."),
    ),
)

FOUNDATION = Page(
    "foundation", "demo_foundation_awards", "https://demo.invalid/foundation/awards",
    "Demo Foundation Awards (synthetic)", "2026-10-02",
    (
        S("shared-application", "Demo Foundation Shared Application",
          "The Demo Foundation Shared Application Form covers both the Demo Northern Scholarship and "
          "the Demo Coastal Bursary.",
          "Submit one form for both awards. Each award has its own eligibility rules.",
          "The shared form is due November 30, 2026 (Pacific Time). Applications open October 1, 2026."),
        S("northern-scholarship", "Demo Northern Scholarship",
          "Eligibility: First Nations, Inuit or Métis students who live in British Columbia or Yukon.",
          "Value: $3,000 CAD.",
          "Apply with the Demo Foundation Shared Application Form."),
        S("coastal-bursary", "Demo Coastal Bursary",
          "Eligibility: First Nations, Inuit or Métis students in a college or trades program.",
          "Value: $1,500 CAD.",
          "Apply with the Demo Foundation Shared Application Form."),
        S("leadership-award", "Demo Leadership Award",
          "The Demo Leadership Award is not part of the shared application. Apply separately.",
          "Eligibility: First Nations, Inuit or Métis students with a GPA of at least 3.0 on a 4.0 scale.",
          "Value: $2,200 CAD.",
          "The separate application is due December 10, 2026 (Pacific Time). Applications open October 1, 2026."),
        S("discretionary-award", "Demo Discretionary Award",
          ELIGIBLE_ALL,
          "The value of this award is set each year by the selection committee and is not published.",
          "The application deadline is March 1, 2027 (Pacific Time). Applications open October 1, 2026.",
          APPLY_FOUNDATION),
        S("community-pool-award", "Demo Community Pool Award",
          ELIGIBLE_ALL,
          "The Demo Foundation distributes a combined total of $50,000 CAD each year among all recipients.",
          "The application deadline is March 1, 2027 (Pacific Time). Applications open October 1, 2026.",
          APPLY_FOUNDATION),
        S("need-based-award", "Demo Need-Based Maximum Award",
          ELIGIBLE_ALL,
          "Applicants must show demonstrated financial need.",
          "Awards of up to $5,000 CAD are available. The actual amount depends on financial need.",
          "The application deadline is March 1, 2027 (Pacific Time). Applications open October 1, 2026.",
          APPLY_FOUNDATION),
    ),
)

REGIONAL = Page(
    "regional", "demo_regional_funding", "https://demo.invalid/regional/funding",
    "Demo Regional Authority Funding (synthetic)", "2026-10-03",
    (
        S("heritage-award", "Demo Heritage Award (historical)",
          ELIGIBLE_ALL,
          "Value: $600 CAD.",
          "The deadline was March 1, 2020 (Pacific Time). No later call has been announced."),
        S("annual-march-award", "Demo Annual March Award",
          ELIGIBLE_ALL,
          "Value: $750 CAD.",
          "Applications are due every year on March 1. The next call has not been published."),
        S("two-round-award", "Demo Two-Round Award",
          ELIGIBLE_ALL,
          "Value: $950 CAD.",
          "Applications open October 1, 2026 and are considered in two rounds: January 15, 2027 and "
          "June 15, 2027 (Pacific Time).",
          "This is one application; the two dates are consideration rounds, not separate applications."),
        S("community-administered-award", "Demo Community Administered Award",
          "Eligibility: determined by each community education administrator.",
          "Deadlines are set by each community education administrator. Contact your local education office."),
        S("no-timezone-award", "Demo No-Timezone Award",
          ELIGIBLE_ALL,
          "Value: $400 CAD.",
          "Applications open September 1, 2026 and close October 9, 2026 at 5:00 p.m."),
        S("eastern-time-award", "Demo Eastern Time Award",
          ELIGIBLE_ALL,
          "Value: $450 CAD.",
          "Applications open September 1, 2026 and close November 1, 2026 at 1:30 a.m. Eastern Time."),
        S("date-only-award", "Demo Date-Only Award",
          ELIGIBLE_ALL,
          "Value: $350 CAD.",
          "Applications open September 1, 2026 and close October 7, 2026 (Pacific Time)."),
        S("regional-funding", "Demo Regional Education Funding",
          "Post-secondary education funding is administered by the Demo Regional Authority education office.",
          "Funding is provided to First Nations education authorities that submit an annual education plan to the "
          "Demo Regional Authority.",
          "Funding decisions and eligibility are made locally. Contact the education office to apply."),
    ),
)

PAGES = (COLLEGE, FOUNDATION, REGIONAL)

GUIDE_URL = "https://demo.invalid/foundation/guide.pdf"
GUIDE_SOURCE_ID = "demo_foundation_guide"
GUIDE_PAGES = (
    (
        "Demo Foundation Applicant Guide (SYNTHETIC)",
        "Shared Application Form: required documents",
        "Applicants must submit an official transcript and a community support letter.",
    ),
    (
        "Demo Foundation review process (SYNTHETIC)",
        "Only one shared form is needed for the Northern Scholarship and the Coastal Bursary.",
    ),
)
SCANNED_URL = "https://demo.invalid/foundation/scanned-notice.pdf"
SCANNED_SOURCE_ID = "demo_foundation_scanned_notice"


def render_html(page: Page) -> bytes:
    parts = [
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        f"<title>{escape(page.title)}</title>",
        f'<meta name="dcterms.modified" content="{page.modified}"></head><body>',
        '<header><a href="/">Synthetic site header</a></header>',
        '<nav><ul><li><a href="/home">Home</a></li><li><a href="/contact">Contact</a></li></ul></nav>',
        f"<main><h1>{escape(page.title)}</h1><p>{escape(BANNER)}</p>",
    ]
    for section in page.sections:
        parts.append(f'<h2 id="{section.anchor}">{escape(section.heading)}</h2>')
        parts.extend(f"<p>{escape(p)}</p>" for p in section.paragraphs)
    parts.append("</main><footer>Synthetic footer text that must not be extracted.</footer></body></html>")
    return "".join(parts).encode("utf-8")


def render_guide_pdf() -> bytes:
    from reportlab.pdfgen import canvas

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pageCompression=0, invariant=1)
    for lines in GUIDE_PAGES:
        y = 760
        for line in lines:
            pdf.drawString(72, y, line)
            y -= 32  # a gap wider than line height keeps pypdf paragraphs separate
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def render_scanned_pdf() -> bytes:
    """An image-only PDF (no text layer): the extractor must report ``ocr_required``."""
    from PIL import Image, ImageDraw
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    image = Image.new("RGB", (600, 200), "white")
    ImageDraw.Draw(image).text((20, 90), "SYNTHETIC SCANNED NOTICE - image only", fill="black")
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pageCompression=0, invariant=1)
    pdf.drawImage(ImageReader(image), 72, 500, 450, 150)
    pdf.save()
    return buffer.getvalue()
