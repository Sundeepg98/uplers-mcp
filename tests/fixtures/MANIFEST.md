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
