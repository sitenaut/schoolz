"""The kinds of service a provider can pick in the portal, each mapped to
the Inform USA taxonomy code NJ 211 uses for it - so a provider-entered
listing lands under the same Localz category (categories.py) as a scraped
one, and free text alone is never a category.

`normally_free` marks the kinds where a fee is a review flag: people in need
are targeted by "application fee" scams, and a pantry or shelter charging
is worth a human look. `confidential_hint` suggests the confidential
address option in the form.
"""
from __future__ import annotations

from dataclasses import dataclass

from .categories import categories_for_code


@dataclass(frozen=True)
class ProviderType:
    key: str
    label: str
    code: str
    code_name: str
    normally_free: bool = False
    confidential_hint: bool = False

    @property
    def category(self) -> str:
        return categories_for_code(self.code)[0]


PROVIDER_TYPES: tuple[ProviderType, ...] = (
    ProviderType("food_pantry", "Food pantry", "BD-1800.2000", "Food Pantries", normally_free=True),
    ProviderType("free_meals", "Free meals / soup kitchen", "BD-5000.8300", "Soup Kitchens", normally_free=True),
    ProviderType("home_meals", "Home-delivered meals", "BD-5000.3500", "Home Delivered Meals"),
    ProviderType("shelter", "Shelter", "BH-1800.8500-150", "Community Shelters", normally_free=True),
    ProviderType(
        "dv_shelter", "Domestic violence shelter", "BH-1800.1500-100", "Domestic Violence Shelters",
        normally_free=True, confidential_hint=True,
    ),
    ProviderType("youth_shelter", "Youth shelter", "BH-1800.1500-960", "Youth Shelters", normally_free=True, confidential_hint=True),
    ProviderType("rent_help", "Help with rent", "BH-3800.7000", "Rent Payment Assistance", normally_free=True),
    ProviderType("utility_help", "Help with utility bills", "BV-8900.9300-180", "Electric Service Payment Assistance", normally_free=True),
    ProviderType("clothing", "Clothing", "BM-6500.1500-250", "General Clothing Provision", normally_free=True),
    ProviderType("diapers", "Diapers and baby supplies", "BM-6500.1500-150", "Diapers", normally_free=True),
    ProviderType("rides", "Rides", "BT-4500.6500-280", "General Paratransit/Community Ride Programs"),
    ProviderType("clinic", "Health clinic", "LN-1500", "Community Clinics"),
    ProviderType("counseling", "Counseling", "RP-1400.2500", "General Counseling Services"),
    ProviderType("recovery", "Substance use counseling", "RX-8450.8000", "Substance Use Disorder Counseling"),
    ProviderType("support_group", "Support group", "PN-8100.5000", "Mental Health Related Support Groups", normally_free=True),
    ProviderType("child_care", "Child care", "PH-1250.1400", "Child Care Centers"),
    ProviderType("english", "English classes", "HH-0500.8000-150", "English as a Second Language"),
    ProviderType("parenting", "Parenting classes", "PH-6100.6800", "Parenting Skills Classes"),
    ProviderType("job_help", "Help finding a job", "ND-3500.3600", "Job Search/Placement", normally_free=True),
    ProviderType("money_help", "Money and budgeting help", "DM-6500", "Personal Financial Counseling"),
    ProviderType("legal_aid", "Free legal help", "FT-3200", "General Legal Aid", normally_free=True),
    # Immigration help is where "notario" fraud lives, so a fee is a flag.
    ProviderType(
        "immigration", "Immigration help", "FT-3600.1500", "Comprehensive Immigration/Naturalization Services", normally_free=True,
    ),
    ProviderType("benefits_help", "Help applying for benefits", "PH-0700", "Benefits Screening", normally_free=True),
    ProviderType("notary", "Notary", "FT-6100", "Notary Public Services"),
    ProviderType("adult_education", "Reading, writing and GED classes", "HH-0500", "Adult Basic Education"),
    ProviderType("computer_access", "Computers and internet to use", "TJ-1800.6700", "Public Internet Access Sites", normally_free=True),
    ProviderType("vision", "Eye screening and glasses", "LF-4900.2000", "Eye Screening"),
    ProviderType("garden", "Community garden", "BD-2600.1500", "Community Gardening", normally_free=True),
    ProviderType("activities", "Social groups and activities", "PL-7000.4360", "General Recreational Activities/Sports"),
)

BY_KEY: dict[str, ProviderType] = {t.key: t for t in PROVIDER_TYPES}
BY_CODE: dict[str, ProviderType] = {t.code: t for t in PROVIDER_TYPES}
