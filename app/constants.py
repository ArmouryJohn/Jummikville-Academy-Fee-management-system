"""Constants for school sections, classes, and expense categories."""

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

# Expense categories for school operations
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
