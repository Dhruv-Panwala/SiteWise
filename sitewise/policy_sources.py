"""Small, reviewed official-source registry; not a UK-wide policy database.

Selectors deliberately fail closed when a council changes a document. Actions
are screening suggestions, not paraphrases of statutory requirements.
"""

WANDSWORTH_PLAN = "https://www.wandsworth.gov.uk/planning/planning-policy/local-plan/the-adopted-local-plan/local-plan-explained/"
WANDSWORTH_APPLY = "https://www.wandsworth.gov.uk/planningpermission"
WANDSWORTH_SPD = "https://www.wandsworth.gov.uk/media/1632/housing_spd_adopted_nov_2016.pdf"
LAMBETH_SPD = "https://www.lambeth.gov.uk/sites/default/files/2023-08/Part%204%20_Building%20Alterations%2C%20Extensions%20and%20Retrofit.pdf"
WESTMINSTER_APPLY = "https://www.westminster.gov.uk/planning-building-control-and-environmental-regulations/planning-applications/make-application/application-types-and-checklists/householder-application"
LONDON_BASE = "https://www.london.gov.uk/programmes-strategies/planning/london-plan/the-london-plan-2021-online/"


def rule(key, title, url, topics, start, end, action, *, status="Council guidance; check the full document and current amendments", pages=None):
    return dict(key=key, title=title, url=url, topics=topics, start=start, end=end,
                action=action, document_status=status, pages=pages)


COUNCIL_SOURCES = {
    "Wandsworth": [
        rule("rear", "Rear-extension scale and neighbour amenity", WANDSWORTH_SPD,
             ["extension"], r"4\.21\s", r"4\.23\s",
             "Test a smaller or stepped-back rear extension, showing retained garden space and effects on neighbouring windows. Submit accurate sections rather than assuming any particular depth will be acceptable.",
             pages=[42, 43], status="Housing SPD (2016), still linked by council. Older policy references must be checked against the 2023 Local Plan and 2026 partial review."),
        rule("housing", "Housing standards: space and daylight (LP27)", WANDSWORTH_PLAN,
             ["new_homes", "extension", "conversion"], r"How will the new Local Plan affect any household", r"Who has been involved",
             "For each proposed home, show internal floor area, daylight and the proposed layout. Check whether subdivision or loss of an existing dwelling raises LP25/LP26 issues."),
        rule("trees", "Trees and biodiversity (LP55 / LP56)", WANDSWORTH_PLAN,
             ["trees", "new_homes", "extension", "demolition"], r"How will the Local Plan protect trees", r"How does the Local Plan promote",
             "Survey trees on and next to the site before fixing the footprint. Explore retaining trees within the scheme and confirm TPO/conservation status with the council; this policy does not prove any specific tree is protected."),
        rule("contributions", "Small-site affordable housing contributions", WANDSWORTH_APPLY,
             ["new_homes", "conversion"], r"Affordable housing contributions for small sites\s+The", r"GLA requirements",
             "Check the current small-site contribution rules, commencement date and any exceptions with the council before budgeting or deciding the number of homes.",
             status="Live council application guidance; verify applicability and transition provisions, not a calculated liability."),
        rule("submission", "Submission documents and validation", WANDSWORTH_APPLY,
             ["any"], r"Prepare your submission\s+The information", r"Affordable housing contributions for small sites",
             "Use the council's local validation checklist to identify the plans and supporting assessments required for this application type."),
    ],
    "Westminster": [
        rule("daylight", "Neighbour daylight assessment", WESTMINSTER_APPLY,
             ["extension", "new_homes", "roof"], r"Daylight/Sunlight Assessment", r"Follow our naming conventions",
             "Check neighbouring windows and daylight before fixing the massing; ask whether a daylight/sunlight assessment is needed. This is householder checklist guidance, not the full checklist for new dwellings."),
        rule("design", "Sustainable design information", WESTMINSTER_APPLY,
             ["extension", "new_homes"], r"Sustainable Design Statement\s+Required", r"Flood Risk Assessment",
             "Explain the environmental design of the added floorspace. If creating additional homes, obtain the full-application checklist rather than using only the householder checklist."),
    ],
    "Lambeth": [
        rule("rear", "Rear and wrap-around extensions", LAMBETH_SPD,
             ["extension"], r"4\.56\s", r"4\.58\s",
             "Compare infill, end and wrap-around options with the council's design diagrams; test neighbour impact and the character of the original building before choosing the footprint.",
             pages=[18, 19, 20, 21, 22], status="Lambeth Design Guide SPD, Part 4 (adopted August 2023); guidance, not permission."),
    ],
}

LONDON_SOURCES = [
    rule("housing_quality", "London Plan D6: housing quality and standards", LONDON_BASE + "chapter-3-design",
         ["new_homes", "conversion"], r"Policy D6 Housing quality and standards\s+A\s+Housing", r"Policy D7 Accessible housing",
         "Check each home's space, outlook, privacy, daylight and ventilation against D6. Provide dimensioned layouts; do not treat the presence of housing nearby as evidence that this layout complies.", status="London-wide development-plan policy, not a borough-specific rule."),
    rule("tree_retention", "London Plan G7: retaining trees of value", LONDON_BASE + "chapter-8-green-infrastructure",
         ["trees", "new_homes", "extension", "demolition"], r"Policy G7 Trees and woodlands", r"Policy G8 Green Belt",
         "Design around valuable existing trees where possible. If removal is proposed, explain the justification and replacement approach; separately establish whether consent is needed.", status="London-wide development-plan policy; does not establish site-specific tree protection."),
]
