"""
School section and class constants — the single source of truth.

WHY HERE:
  Sections and classes are stored as plain strings in the database (no foreign
  keys to a Section or Class table). This constant is the authoritative list
  of which classes belong to which section, used by:
    - Pydantic schemas (validation)
    - API endpoints (filtering, enumeration)
    - The frontend mirrors this in SECTION_CLASSES (app.js)

ADDING A NEW SECTION OR CLASS:
  Edit SECTION_CLASSES below.  That's it — schemas, validation, and the
  new-/edit-student dropdowns pick up the change automatically.
"""

# Maps each section name → ordered list of classes within it.
SECTION_CLASSES: dict[str, list[str]] = {
    "Preschool": [
        "Preschool 1",
        "Preschool 2",
        "Preschool 3",
        "Reception",
    ],
    "Primary": [
        "Primary 1",
        "Primary 2",
        "Primary 3",
        "Primary 4",
        "Primary 5",
        "Primary 6",
    ],
    "Smart Skills High School": [
        "JSS1",
        "JSS2",
        "JSS3",
        "SS1",
        "SS2",
        "SS3",
    ],
}

# Flat list of valid section names, in display order.
SECTIONS: list[str] = list(SECTION_CLASSES.keys())

# Flat list of every valid class name across all sections.
ALL_CLASSES: list[str] = [
    cls
    for classes in SECTION_CLASSES.values()
    for cls in classes
]

# --------------------------------------------------------------------------
# Expense categories — the fixed list of what school spending is bucketed into.
# The single source of truth for the Expenses page (Part C): used by the create
# schema (validation), the /expenses/categories endpoint, and the frontend
# category dropdown. Ordered for display.
# --------------------------------------------------------------------------
EXPENSE_CATEGORIES: list[str] = [
    "Textbooks",
    "Repairs",
    "Stationery",
    "Transport",
    "Fuel",
    "Nepa Light",
    "Events",
    "Miscellaneous",
]
