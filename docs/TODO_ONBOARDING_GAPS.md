# TODO: onboarding gaps to track down

Things the Runnemede, Black Horse Pike, Bellmawr and Gloucester Township
onboarding could not find. Each is a lookup for a person, not a code bug. Tick
off, then move any lasting finding into `ONBOARDING_CRAWL_GUIDE.md` or the matching `docs/platforms/` file.

## Districts queued for onboarding
Found while looking at the Kids Choice before/after-care operator (`kidschoicewt.com`), which runs programs in these districts. Not onboarded; none are in the local DB. Their Kids Choice pages share one template, so each school's after-care (`sacc`) hours and fees can be filled from `https://www.kidschoicewt.com/<district-page>/` once the district is in.
- [x] Brooklawn (Alice Costello Elementary): onboarded locally (`brooklawn.json`). Its high-school students go to Gloucester City High School, so Gloucester City matters next.
- [x] Clayton (CHS, CMS, Simmons Elementary): onboarded locally (`clayton.json`); staff and lunch are open gaps.
- [x] Monroe Township (Holly Glen, Oak Knoll, Radix, Whitehall, Williamstown MS/HS): onboarded locally (`monroe_township.json`); prod import pending.
- [x] Washington Township, Gloucester County: onboarded locally (`washington_township_gloucester.json`), after-care included; prod import pending.
- [x] Gloucester City (Cold Springs, Middle, High): onboarded locally (`gloucester_city.json`); prod import pending. Kids Choice does not serve it (AlphaBEST does).
- Gateway Regional, Woodbury Heights, Westville, National Park and Wenonah are onboarded and imported locally; prod import is pending. Their lunch menus share Gateway's Nutrislice tenant `grsd`.

## Black Horse Pike Regional (Highland, Timber Creek, Triton)
- [ ] Timber Creek half-day and 2-hour-delay schedules: its bell-schedule page publishes only the regular schedule (a PNG). Ask the school or look for a handbook.
- [ ] Absence reporting method for each school.
- [ ] Lunch: only a district-wide PDF exists. Confirm no SchoolCafé or other vendor shortname.
- [ ] Triton staff roster scan ran very long and stored 0 staff locally. Re-run and check.
- [ ] Newsletters and PTA/booster sites for all three.

## Bellmawr
- [ ] Early Childhood Center: confirm its phone (856-931-1322 is a guess from a shared page) and find a logo.
- [ ] Burke Elementary: logo missing.
- [ ] Absence reporting method for all four schools.
- [ ] Bell Oaks hours: the district footer says 8:30-3:00 but the school page showed 8:00-3:00. Confirm.
- [ ] Newsletters and PTAs. The only Smore link found was for new student registration.

## Gloucester Township
- [ ] School hours for all 10 schools (none found).
- [ ] Absence reporting method for all schools.
- [ ] Preschool Program (Apptegy org 25533) is not tracked. Decide whether to add it and find its address.
- [ ] Gloucester Township Elementary staff roster is small (24). Verify.
- [ ] Blackwood, Gloucester Township Elementary and Loring-Flemming calendar feeds returned 0 events. Re-check.
- [ ] Newsletters and PTAs.

## Runnemede
- [ ] Next year the district calendar nav link points at a new Drive file id. Re-copy it (`District.calendar_pdf_url`).
- [ ] Volz delayed-opening time.
- [ ] Handbooks, newsletters, athletics, transportation page.
