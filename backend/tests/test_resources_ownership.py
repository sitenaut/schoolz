from datetime import date

import pytest

from models import ResourceService
from resources.ownership import apply_source_fields


@pytest.mark.anyio
async def test_a_refresh_never_moves_last_confirmed_back_or_blanks_it():
    for owned in ([], ["phone"]):  # unclaimed, and claimed by a provider
        row = ResourceService(provider_owned_fields=owned, address_kind=None, last_assured_on=date(2026, 10, 20), phone="1")
        # NJ 211's own older date, then ChildCareNJ's none.
        await apply_source_fields(None, row, {"last_assured_on": date(2026, 3, 1), "transportation": "Bus 404"}, "nj211")
        await apply_source_fields(None, row, {"last_assured_on": None}, "childcarenj")
        assert row.last_assured_on == date(2026, 10, 20) and row.transportation == "Bus 404"
        # A newer confirmation at the source still lands.
        await apply_source_fields(None, row, {"last_assured_on": date(2026, 11, 2)}, "nj211")
        assert row.last_assured_on == date(2026, 11, 2)
