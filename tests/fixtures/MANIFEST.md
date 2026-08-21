# Uplers HTTP fixtures

Captured live from `GET https://platform.uplers.com/api/single-hr-public?hr_number=<HR_ID>`
(public, unauthenticated) on 2026-08-20. 32 requests total; final `X-RateLimit-Remaining` 468 of 500.

Each file is the verbatim JSON response body except for the five `detail.*` POC fields, which are
sanitised. In all 32 fetched records those five fields were ALREADY `null`, so per the sanitisation
rule (keep null if it was null) every one of the 30 field-slots was kept null - there was no real
contact data present to redact. Everything else (company names, salaries, JDs, skills) is verbatim.

| file | HR_Number | id kind | is_aggregator_job | job_nature | RequestForTalent | CompanyName | Currency | cost_string | YearOfExp | max_yoe | ModeOfWork | joining_period | len(skills) | len(assessments) | len(shifts) | status | why this fixture was kept |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| HR100725001919.json | HR100725001919 | native | False | Uplers On-Boarded | Graphic Designer | Confido Health | INR | Upto INR 30,00,000 / year | 5.00 | 10.00 | Hybrid | 15 Days | 5 | 1 | 1 | 1 | assessments non-empty (len 1); also the ONLY native fetched with non-null city + city_data; Hybrid with non-null frequency_office_visit; DurationType Long Term; Upto-INR cost grammar |
| HR130826031902.json | HR130826031902 | native | False | Uplers On-Boarded | AI Full Stack Engineer | AgentAI | USD | USD 60,000-90,000 / year | 3.00 | 6.00 | Remote | 15 Days | 11 | 0 | 1 | 1 | Currency != INR: USD with a genuinely populated USD cost_string (every other USD fetched was Confidential); cost_start/end_in_dollar_yearly equal the printed 60000/90000 |
| HR290626125252.json | HR290626125252 | native | False | Uplers On-Boarded | Sr. Test Automation Analyst | Precisely | INR | Confidential | 4.00 | 6.00 | Remote | Immediately | 13 | 1 | 1 | 1 | IsConfidentialBudget == 1 and cost_string == Confidential; also the only kept Hire-a-Contractor pricing, with HowSoon 7 Days / joining_period Immediately |
| HR310725131019.json | HR310725131019 | native | False | Uplers On-Boarded | Customer Success Manager | GoForma | GBP | Upto GBP 549 / month | 2.00 | 4.00 | Remote | 15 Days | 12 | 1 | 1 | 1 | ordinary native: populated cost_string, skills 12, shifts 1, company.industry non-null; adds a 3rd currency GBP, the only Part Time Availability, and a MONTHLY rather than yearly cost grammar |
| HR1173448373079993.json | HR1173448373079993 | aggregated | True | Aggregated | Senior Staff Software Engineer (Backend) | Databricks | INR | Confidential | 15.00 | 0.00 | Office | 30 Days | 5 | 0 | 1 | 1 | the mandated aggregated record: is_aggregator_job true, job_nature Aggregated, PricingName and DurationType null, HR_Role null, cost dollar-yearly fields null, non-null city + city_data |
| HR0191124125506.json | HR0191124125506 | anomaly | False | Mavlers Inhouse | CRM Strategist (US Shift) | Mavlers | INR | INR 15,00,000-18,00,000 / year | 4.00 | 0.00 | Remote | 30 Days | 9 | 1 | 1 | 1 | the single 13-digit id anomaly: job_nature Mavlers Inhouse, HR_Role null, PricingName and DurationType null, assessments non-empty |

## Notes

- `is_partner_company` is NOT a boolean despite the name: in 31 of 32 fetched records it is a date
  STRING such as `"Jun 2026"`, and in exactly 1 record it is the boolean `false`.
- `YearOfExp`, `max_yoe`, `hr_yoe` and `cost` are decimal STRINGS (`"5.00"`), while `Quantity`,
  `IsConfidentialBudget`, `status` and `type` are ints and `is_aggregator_job` is a real bool.
- `HR_Status` is a string on some records and `null` on others.
- `frequency_office_visit` is non-null only when `ModeOfWork` is `Hybrid` in this sample.
- `role` and `company_pitch` were null in all 32 fetched records; `city` / `city_data` were non-null
  in only 2 of them (the aggregated record and HR100725001919).

---

## `talent_profile.json` - the AUTHENTICATED profile fixture

Different provenance from the six above, and the difference is the point.

Captured from `GET /api/talent/profile` on **2026-08-21** against his live signed-in session, by
`scripts/capture_profile_fixture.py`. Re-run that script to refresh it; do not hand-edit it.

**Why it exists.** Every profile test in this suite used to build its own payload, and every one
wrote a skill as `[{"name": "Node.js"}]` - a shape the live API has never returned. It sends a
JOIN: `talent_details.skills` carries rows of `{skill_id, years_of_experience, order}` and the
names live in a separate `masters.skills` lookup. **667 tests passed while the extractor read zero
skills off the real thing**, and the server told the operator his profile was empty on the day he
had finished filling it in. A hand-built payload can only test the shape its author imagined.

| | |
|---|---|
| `talent_details.skills` | 61 rows, `skill_id` -> `masters.skills` |
| `talent_details.primaryskills` | 56 rows, same master, a strict subset of `skills` |
| `talent_details.tools` | 12 rows, `tool_id` -> `masters.tools` |
| `masters.skills` | trimmed 176,329 -> 101: every cited id, plus 40 uncited DECOYS |
| `masters.tools` | trimmed 1,162 -> 22: every cited id, plus 10 decoys |
| also kept | `preferredMethodMaster`, `preferredModes`, `joiningMaster` (small, and all three are joined against) |

The decoys are load-bearing: without them a resolver that zipped the two lists positionally would
pass every count assertion and return 61 wrong names.

**Sanitisation is by DELETION, not masking**, so a test can assert absence and a future recapture
cannot quietly reintroduce a field. Removed: `current_ctc`, `expected_ctc`, `monthly_salary`,
`dob`, `contact_number`, `contact_number_country_code`, `whatsapp_optin`, `address`, `email`,
`profile_pic`, `profile_pic_url`, `ra_profile_pic_url`, `resume`, `resume_url`, `ra_resume_url`,
`repository_url`, `ra_repository_url`, `linkedin_id`, `project_url`, `gender`. The capture script
re-reads what it wrote and **deletes the file rather than leave a leak on disk**;
`test_talent_profile_real.py` asserts the same thing at commit time, by key and by value shape.

Note on the value-shape check: it looks for an email ADDRESS, not the word "email". His
achievements say "the bulk email scheduler" four times because bulk email is his professional
domain, and a substring scan flags his own CV as a leak.

**Anomalies worth knowing**, all present in this capture:

- `profile_completion_percentage` is **absent from the live payload entirely**. The top-level keys
  are only `talent_details`, `masters`, `recommandations`, `ai_generated_summary`. The model keeps
  the field because an older shape carried it, but it is always `None` and the note it drives never
  fires.
- `preferred_modes` means ENGAGEMENT TYPE (`Full time`, `Contract`), not work mode. The
  Remote/Office answer is `preferred_method`, an int resolved via `preferredMethodMaster`.
  These two are the easiest wrong join in the payload.
- `recommandations` is spelled that way by Uplers, and was `[]` at capture.
- `is_current` on an experience row is `0`/`1`/`2`, not a boolean.
- `years_of_experience` is a decimal STRING and is `"0"` on 58 of the 61 skill rows - Uplers means
  "not recorded", not "zero years", so only positive figures are carried through.
- `short_created_at` is `"1970-01-01"` on both profile and master rows: an unset epoch date.
