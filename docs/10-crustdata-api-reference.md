# 10 - Crustdata API Implementation Reference (API version 2025-11-01)

Researched 2026-10-11 from the official docs. No API calls were made with any key. Every fact carries a source URL. Anything not in the docs is marked **UNKNOWN**. Anything inferred (not stated in the docs) is marked **INFERENCE**.

Docs index (machine readable): https://docs.crustdata.com/llms.txt . Every docs page has a `.md` variant (append `.md`). The OpenAPI YAML files (`/openapi-specs/2025-11-01/*.yaml`) redirect to a login page and are not publicly fetchable. The same OpenAPI text is embedded in the `api-reference/...md` pages, which were used here.

---

## 0. Global conventions

| Item | Value | Source |
|---|---|---|
| Base URL | `https://api.crustdata.com` | https://docs.crustdata.com/company-docs/enrichment/introduction.md |
| Required headers | `authorization: Bearer YOUR_API_KEY`, `content-type: application/json`, `x-api-version: 2025-11-01` | https://docs.crustdata.com/company-docs/search/introduction.md |
| Missing version header | "requests without it return `400`" | https://docs.crustdata.com/general/credits.md |
| Error envelope | `{ "error": { "type": "...", "message": "...", "metadata": [] } }` | https://docs.crustdata.com/company-docs/enrichment/reference.md |
| Operators for ranges | `=>` (>=) and `=<` (<=). `>=` / `<=` are rejected with 400 | https://docs.crustdata.com/company-docs/search/reference.md |
| Per-call credit header | Response header `X-Credits-Used` (exact decimal, e.g. `0.03`). See section 7 | https://docs.crustdata.com/general/credits.md |
| Request id header | Response header `X-Request-Id`; pass it to `GET /account/usage/events/{request_id}` for the charge breakdown | https://docs.crustdata.com/general/credits.md |
| Rate-limit headers | `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset` (seconds until window rolls over) on 429; batch 429s carry `Retry-After` | https://docs.crustdata.com/general/rate-limits.md , https://docs.crustdata.com/openapi-specs/2025-11-01/best-practices.md |
| Credit expiry | Purchased credits valid 12 months | https://docs.crustdata.com/general/pricing.md |

### Error codes (cross-endpoint)

| Status | Meaning | Source |
|---|---|---|
| 400 | `invalid_request`: bad field, bad operator, bad cursor, missing `x-api-version`, wrong identifier combo | https://docs.crustdata.com/company-docs/search/reference.md |
| 401 | `unauthorized`: "Invalid API key in request." / "Missing API key in request" | https://docs.crustdata.com/company-docs/enrichment/reference.md |
| 402 | `insufficient_credits` (account out of credits, or the API key's monthly cap exhausted). Terminal, do not retry. Batch submit that cannot be afforded: `credit_limit_exceeded` | https://docs.crustdata.com/openapi-specs/2025-11-01/best-practices.md , https://docs.crustdata.com/general/credits.md |
| 403 | `permission_error`: endpoint not enabled, or requested field not enabled on the account (`Access denied to fields: ...`, with `metadata[].denied_fields` / `permitted_fields`). The docs also say 403 can mean "insufficient credits" on some endpoint pages (inconsistent with 402 above; handle both) | https://docs.crustdata.com/api-reference/company-apis/get-full-company-enrichment.md , https://docs.crustdata.com/person-docs/search/reference.md |
| 404 | Defined in the OpenAPI for company enrich, but the API actually returns `200` with empty `matches`; handle both | https://docs.crustdata.com/company-docs/enrichment/reference.md |
| 413 | `request_too_large`: body over 10 MB | https://docs.crustdata.com/company-docs/search/reference.md |
| 429 | `rate_limit_error`; wait `x-ratelimit-reset` seconds (+ jitter) | https://docs.crustdata.com/openapi-specs/2025-11-01/best-practices.md |
| 500 | `internal_error`; retry with backoff. NOTE: on `/job/search` an unsupported filter field or malformed geo value returns **500**, not 400 | https://docs.crustdata.com/job-docs/search/reference.md |

### Default rate limits (RPM) for endpoints we use
Source: https://docs.crustdata.com/general/rate-limits.md ("Verify active limits in your dashboard"; your own are returned by `GET /account/endpoints`).

| Endpoint | RPM |
|---|---|
| `/company/enrich` | 15 |
| `/company/search` | 30 |
| `/company/identify` | 30 |
| `/company/search/autocomplete` | 300 |
| `/person/search` | 30 |
| `/person/enrich` | 15 |
| `/person/search/autocomplete` | 300 (table) but the person autocomplete page says 45; **inconsistent, treat as UNKNOWN, assume the lower value** |
| `/job/search` | 30 |
| `/job/search/autocomplete` | UNKNOWN: not in the rate-limit table; the job autocomplete page says 30 (https://docs.crustdata.com/job-docs/autocomplete/introduction.md) |
| `/account/credits`, `/account/endpoints` | 300 |
| `/account/usage/*` | 60 (shared budget) |

Batch jobs additionally have a concurrency cap (default 5 active jobs per pool): https://docs.crustdata.com/general/rate-limits.md

---

## 1. Company Enrich (by domain)

Sources: https://docs.crustdata.com/company-docs/enrichment/introduction.md , https://docs.crustdata.com/company-docs/enrichment/reference.md , https://docs.crustdata.com/api-reference/company-apis/get-full-company-enrichment.md

### Endpoint
`POST https://api.crustdata.com/company/enrich`

### Request body

| Param | Type | Required | Notes |
|---|---|---|---|
| `domains` / `professional_network_profile_urls` / `names` / `crustdata_company_ids` | string[] (ids: integer[]) | Exactly ONE identifier type | Mixing types returns 400. "Max 25 per request." |
| `fields` | string[] | No | Default `["basic_info"]` (plus `crustdata_company_id`). Sections you do not list are omitted/null. |
| `exact_match` | boolean | No | Default `null` (auto). `true` restricts to exact `primary_domain` matches. |

Valid `fields` section names: `basic_info, headcount, funding, locations, taxonomy, revenue, hiring, followers, seo, competitors, social_profiles, web_traffic, employee_reviews, people, news, software_reviews, public_launches, market_intel, technographics (gated add-on), social_posts (gated beta add-on), reviews, metadata, crustdata_company_id, updated_at, indexed_at`. `roles` and `skills` are NOT valid for enrich (search-only). Source: reference.md and the OpenAPI text.

The OpenAPI describes `fields` as group names. The batch endpoint documents that dotted leaf paths (e.g. `headcount.total`) are accepted (https://docs.crustdata.com/company-docs/enrichment/batch.md). Whether dotted paths work on the non-batch `/company/enrich` is **UNKNOWN / not documented**; request whole groups (`"headcount"`, `"hiring"`, `"funding"`) to be safe.

### Verbatim minimal request (from docs)
```bash
curl --request POST \
  --url https://api.crustdata.com/company/enrich \
  --header 'authorization: Bearer YOUR_API_KEY' \
  --header 'content-type: application/json' \
  --header 'x-api-version: 2025-11-01' \
  --data '{
    "domains": ["retool.com"],
    "fields": ["basic_info", "headcount", "funding", "people"]
  }'
```
Request for our needs (INFERENCE built from documented parts):
```json
{ "domains": ["example.com"], "fields": ["basic_info", "headcount", "hiring", "funding"], "exact_match": true }
```

### Response shape
Top-level **array**, one entry per submitted identifier:
```json
[
  {
    "matched_on": "retool.com",
    "match_type": "domain",
    "matches": [
      { "confidence_score": 1.0, "company_data": { "crustdata_company_id": 633593, "basic_info": {...}, "headcount": {...} } }
    ]
  }
]
```
No match: `200` with `"matches": []`. Check `matches.length > 0` before reading `company_data`. Multiple matches possible: pick highest `confidence_score`, verify `basic_info.primary_domain`.

### Exact field names we need (all under `matches[].company_data`)

| Need | Exact path | Type / notes | Source |
|---|---|---|---|
| Name | `basic_info.name` | string | enrich reference |
| Domain | `basic_info.primary_domain` (also `all_domains[]`, `website`) | string | enrich reference |
| Headcount band | `basic_info.employee_count_range` | e.g. `"201-500"` | enrich intro example |
| **Total headcount** | `headcount.total` | integer | OpenAPI schema (api-reference page) |
| Headcount growth % | `headcount.growth_percent.{mom, qoq, six_months, yoy, two_years}` | number (percent), nullable | OpenAPI: "Keys are period aliases: `mom`, `qoq`, `six_months`, `yoy`, `two_years`" |
| Headcount growth absolute | `headcount.growth_absolute.{mom, qoq, six_months, yoy, two_years}` | integer delta | same |
| Headcount history | `headcount.timeseries[]` = `{date, employee_count}` | array | OpenAPI schema |
| Department headcount (current) | `headcount.by_role_absolute` (map: role name -> integer) and `headcount.by_role_percent` (map -> number) | Map KEYS are NOT documented (**UNKNOWN**: exact role key spelling/casing, e.g. whether it is `engineering` or `Engineering`) | OpenAPI schema: `additionalProperties` only |
| Department headcount over time | `headcount.by_function_timeseries.CURRENT_FUNCTION.<FunctionName>[]` = `{date, employee_count}`, e.g. key `"Accounting"`; docs text mentions `"Engineering"`. Also `GEO_REGION.<Region>[]` | Compute growth yourself from points. Date format example: `"2024-12-01 00:00:00"` | OpenAPI schema + https://docs.crustdata.com/company-docs/enrichment/batch.md |
| Region headcount | `headcount.by_region_absolute`, `by_region_percent`; `headcount.largest_headcount_country` | maps | OpenAPI schema |
| Skill headcount | `headcount.by_skill_absolute`, `by_skill_percent` | maps | OpenAPI schema |
| **Department growth** | There is NO documented `engineering growth %` scalar in enrich. Options: (a) derive from `headcount.by_function_timeseries.CURRENT_FUNCTION.Engineering`; (b) use `/company/search` fields `roles.growth_6m` / `roles.growth_yoy` (filterable only, NOT returned); (c) `hiring.by_function_qoq_pct` and `hiring.by_function_6m_pct` (hiring-demand growth by function, not headcount) | | OpenAPI schema; https://docs.crustdata.com/company-docs/search/reference.md |
| Open job count | `hiring.openings_count` | integer | enrich reference |
| Open job growth | `hiring.openings_growth_percent` (map; example keys `mom`, `qoq`, `yoy`) | | enrich intro example |
| Hiring by function growth | `hiring.by_function_qoq_pct`, `hiring.by_function_6m_pct` (maps) | key spelling UNKNOWN | OpenAPI schema |
| Open jobs history | `hiring.open_jobs_timeseries[]` = `{date, open_jobs}` | | OpenAPI schema |
| Recent openings | `hiring.recent_openings[]` = `{title, url, number_of_openings, category, description, date_added, date_updated, location_text}`; `hiring.recent_titles_csv` | **`hiring.recent_openings` is a field-gated path on some accounts**: the OpenAPI 403 example shows `Access denied to fields: hiring.recent_openings`. Check `GET /account/endpoints?path=/company/enrich` | OpenAPI 403 example |
| Funding total | `funding.total_investment_usd` | number | enrich reference |
| Last round | `funding.last_round_type`, `funding.last_round_amount_usd`, `funding.last_fundraise_date` | | enrich reference |
| Investors / rounds | `funding.investors[]`, `funding.investors_detailed[]`, `funding.milestones[]` (`date, funding_date, amount_usd, round_type, investors, lead_investors`), `funding.acquisitions[]`, `funding.acquired_by[]` | | OpenAPI schema |
| Leadership | `people.founders`, `people.cxos`, `people.decision_makers` (each with `crustdata_person_id`, `basic_profile`) | | enrich intro example |

**Period key mapping (important):** `/company/enrich` uses `mom, qoq, six_months, yoy, two_years`; `/company/search` uses `1m, 3m, 6m, 12m`. Mapping: `mom <-> 1m`, `qoq <-> 3m`, `six_months <-> 6m`, `yoy <-> 12m`; `two_years` has no search counterpart. Source: https://docs.crustdata.com/company-docs/enrichment/reference.md

Real response sample (docs, `serverobotics.com`): `headcount.total: 381`, `growth_percent: {mom: 3.81, qoq: 8.24, six_months: 24.92, yoy: 94.39, two_years: 269.9}`, `growth_absolute: {mom: 14, qoq: 29, six_months: 76, yoy: 185, two_years: 278}`. Source: https://docs.crustdata.com/api-reference/company-apis/get-full-company-enrichment.md

### Credits
- "**Pricing:** `2 credits per record`. Requesting `technographics` adds **+2 credits** per company that returns technographics data." Source: https://docs.crustdata.com/company-docs/enrichment/introduction.md
- Pricing table: "`/company/enrich` | **2-4** per record | Base **2**; requesting `technographics` adds **+2**". Source: https://docs.crustdata.com/general/pricing.md
- `social_posts` add-on: flat 5 credits per company. Not needed.
- Charge for a no-match input on enrich: **UNKNOWN - not documented** for company enrich (person marketing page says "charged for a miss $0", see section 4). Verify from `X-Credits-Used` on a smoke test.
- Batch: `POST /batch/company/enrich`, "Same as company enrich pricing" (2-4 per record), 30 RPM.

### Rate limit
15 requests/min. Source: enrich intro.md.

### Errors
400 (bad/multiple identifier, invalid field with `metadata.available_fields`), 401, 403 (endpoint or field not enabled), 404 (per spec), 500. Example 400 message: `"Exactly one identifier must be provided: crustdata_company_ids, names, domains, or professional_network_profile_urls"`.

### Free resolver
`POST /company/identify` is **Free** (body: one of `domains`, `names`, `professional_network_profile_urls`, `crustdata_company_ids`, optional `exact_match`; max 25). Returns same array shape with `company_data.basic_info` only (incl. `crustdata_company_id`, `professional_network_id`, `employee_count_range`, `industries`). Rate limit 30 RPM. Use it first to get `crustdata_company_id` (needed for the Jobs and Person filters). Source: https://docs.crustdata.com/company-docs/identify/introduction.md , pricing.md ("Free endpoints" list).

---

## 2. Company Search (brief)

Sources: https://docs.crustdata.com/company-docs/search/introduction.md , https://docs.crustdata.com/company-docs/search/reference.md

`POST https://api.crustdata.com/company/search`

| Param | Type | Notes |
|---|---|---|
| `filters` | object | Required if `search` omitted. Single `{field,type,value}` or group `{op:"and"|"or", conditions:[...]}` (nestable) |
| `search` | `{query, mode}` | Natural-language ranked search; `mode`: `hybrid` (default) / `lexical` / `semantic`. Not combinable with `sorts` |
| `fields` | string[] | Dot paths. Default = all fields (large). `crustdata_company_id` always returned |
| `sorts` | `[{"field":..., "order":"asc|desc"}]` | Filter-only search. Sorting free. (One docs paragraph says `column` instead of `field`; all examples use `field`. For the Jobs API, `column` is explicitly rejected with 400. Use `field`.) |
| `limit` | int | Default 20; max 1000 (filter-only), 100 (ranked) |
| `cursor` | string | `next_cursor` from prior response; cursors expire 20 min after initial search |

Operators (company search, page text): `=`, `!=`, `<`, `>`, `=<`, `=>`, `in`, `not_in`, `contains`, `not_contains`, `is_null`, `is_not_null`, `(.)` fuzzy, `[.]` exact token, `geo_distance`, `geo_exclude`.

Verbatim domain lookup (docs):
```bash
curl --request POST --url https://api.crustdata.com/company/search \
  --header 'authorization: Bearer YOUR_API_KEY' --header 'content-type: application/json' --header 'x-api-version: 2025-11-01' \
  --data '{"filters":{"field":"basic_info.primary_domain","type":"=","value":"retool.com"},"limit":1,"fields":["crustdata_company_id","basic_info.name","basic_info.primary_domain","headcount.total","funding.total_investment_usd"]}'
```
Response: `{ "companies": [ { "crustdata_company_id": 633593, "basic_info": {...} } ], "next_cursor": "...|null", "total_count": N|null }`.

Filterable/sortable headcount fields in search: `headcount.total`, `headcount.growth_percent.{1m,3m,6m,12m}`, `headcount.growth_absolute.{1m,3m,6m,12m}` (growth paths filterable, NOT sortable). `roles.distribution.<function>` (e.g. `roles.distribution.engineering`), `roles.distribution_percent`, `roles.growth_6m`, `roles.growth_yoy` are **filter-only; requesting them in `fields` returns 400**. Function names: accounting, administrative, arts_and_design, business_development, community_and_social_services, consulting, customer_success_and_support, education, engineering, entrepreneurship, finance, healthcare_services, human_resources, information_technology, legal, marketing, media_and_communication, military_and_protective_services, operations, product_management, program_and_project_management, purchasing, quality_assurance, real_estate, research, sales, support. Returned search sections are limited to: `basic_info, headcount (total only), funding (total_investment_usd, last_round_amount_usd, investors), locations, taxonomy, revenue, hiring (openings_count, openings_growth_percent), followers, social_profiles, software_reviews`. So **growth maps and department data need Enrich**, not Search.

Credits: "Base: **0.03 credits per result**. Premium filter or receive charges, per result: Taxonomy 0.1; Followers, headcount, funding, hiring, software reviews, maps 0.2; Technographics 1 (filter side only). Filtering and receiving are billed separately. Sorting is free. ... Requests with no results consume no credits." Rate limit 30/min. Source: company-docs/search/introduction.md and https://docs.crustdata.com/general/pricing.md . Example: domain filter + returning `headcount.total` = 0.03 + 0.2 = 0.23 per result.

Pagination errors: 400 `"Invalid cursor: expired or malformed; restart without cursor"`. Bad field: 400 `"Unsupported columns in conditions: [...]"`.

---

## 3. Person Search (past/current employer, titles, seniority)

Sources: https://docs.crustdata.com/person-docs/search/introduction.md , https://docs.crustdata.com/person-docs/search/reference.md , https://docs.crustdata.com/api-reference/person-apis/search-people-using-filters-and-sorting.md

`POST https://api.crustdata.com/person/search` (headers as section 0). Default rate limit 30 RPM.

### Request body

| Param | Type | Required | Notes |
|---|---|---|---|
| `filters` | object | Yes | Condition or group. Group `op`: `and`, `or`, `all_of` (lowercase only) |
| `fields` | string[] | No | Dot paths or families. **If omitted, the default set (experience + education) is returned.** `crustdata_person_id` always included |
| `sorts` | `[{field, order}]` | No | Needed for stable pagination. Sortable incl. `crustdata_person_id`, `basic_profile.name`, `experience.employment_details.start_date`, `experience.employment_details.company_id`, `metadata.updated_at`, `professional_network.followers/connections` |
| `limit` | int | No | Default 20; 1 to 1000. `count` is an alias |
| `cursor` | string | No | `next_cursor` from previous response; stop when `null`. Keep filters/sorts unchanged |
| `post_processing` | `{exclude_profiles[], exclude_names[]}` | No | |
| `explain` | boolean | No | On empty result names the culprit condition (`remarks[]`); free |
| `search` / `mode` | | No | Beta semantic search (`search.query`, `search.mode` hybrid/lexical/semantic; top-level `mode: "exact"` keeps hard filters). No `sorts` with it |

Operators: `=`, `!=`, `<`, `=<`, `>`, `=>`, `in`, `not_in`, `is_null`, `is_not_null` (value must be literal `null`, key required), `has_all`, `(.)` (all-words, case-insensitive, typo-tolerant on some fields; `|` is NOT OR), `(!)` (substring negation), `[.]` (exact phrase), `geo_distance`, `geo_exclude`. **No `contains`.** Source: person search reference.

IMPORTANT matching semantics (person search reference): `=`, `!=`, `in`, `not_in` match the **whole stored value** (e.g. `"Qorvo"` does not match `"Qorvo, Inc."`). Use `(.)` / `[.]` for words in titles.

### Filter field names

| Purpose | Field |
|---|---|
| Current employer, by domain | `experience.employment_details.current.company_website_domain` (bare domain e.g. `"stripe.com"`) |
| Past employer, by domain | `experience.employment_details.past.company_website_domain` |
| Any role (current or past), by domain | `experience.employment_details.company_website_domain` |
| Employer by Crustdata company id | `experience.employment_details.current.company_id` / `.past.company_id` / `experience.employment_details.company_id` (integer). Most reliable. Get it from Company Identify (free) |
| Employer by profile URL | `...current.company_professional_network_profile_url`, `...past.company_professional_network_profile_url` |
| Employer by name | `...current.company_name`, `...past.company_name`, `experience.employment_details.company_name` (whole-value match with `=`/`in`) |
| Title | `...current.title`, `...past.title`, `experience.employment_details.title` (use `(.)` or `[.]`) |
| Seniority (closed set, case-insensitive, exact values) | `experience.employment_details.[current.|past.]seniority_level`: `"Entry Level"`, `"Entry Level Manager"`, `"Senior"`, `"Director"`, `"Owner / Partner"`, `"CXO"`, `"Vice President"`, `"In Training"`, `"Experienced Manager"`, `"Strategic"`. Invalid value returns 400 |
| Function (closed set) | `...function_category`: `"Engineering"`, `"Sales"`, `"Consulting"`, `"Marketing"`, `"Operations"`, `"Finance"`, `"Research"`, `"Customer Success and Support"`, `"Arts and Design"`, `"Human Resources"`, `"Legal"`, `"Product Management"` |
| Role dates | `experience.employment_details.start_date`, `.end_date`; `...current.start_date`, `...past.start_date` (NOTE: no documented `past.end_date` filter path in the searchable-fields table; the all-roles path `experience.employment_details.end_date` exists) |
| Normalized title (beta) | `basic_profile.normalized_title.department / sub_department / matched_title` |
| Tenure | `...years_at_company_raw` |
| "Same job" vs "different jobs" | `and` group on one nested path = ONE employment entry must satisfy all conditions. `all_of` = each condition satisfied by some entry, possibly different entries |

Valid employer-domain note: subdomains are not indexed ("The domain is a subdomain. The index does not hold subdomains"). If a domain returns nobody, run with `"explain": true`; the `remarks[].resolution` gives the `company_id` filter. Source: person search reference.

### Verbatim-style request: former tech leaders of a company domain
Built only from documented operators/fields (INFERENCE on combination; the one-employment-entry semantics for an `and` group on `past.*` is documented in the "Nested-array matching" section):
```json
{
  "filters": {
    "op": "and",
    "conditions": [
      { "field": "experience.employment_details.past.company_website_domain", "type": "=", "value": "example.com" },
      {
        "op": "or",
        "conditions": [
          { "field": "experience.employment_details.past.title", "type": "[.]", "value": "CTO" },
          { "field": "experience.employment_details.past.title", "type": "[.]", "value": "Chief Technology Officer" },
          { "field": "experience.employment_details.past.title", "type": "[.]", "value": "VP Engineering" },
          { "field": "experience.employment_details.past.title", "type": "[.]", "value": "Vice President of Engineering" },
          { "field": "experience.employment_details.past.title", "type": "[.]", "value": "Director of Engineering" },
          { "field": "experience.employment_details.past.title", "type": "[.]", "value": "Principal Engineer" }
        ]
      }
    ]
  },
  "fields": [
    "crustdata_person_id",
    "basic_profile.name",
    "basic_profile.current_title",
    "experience.employment_details.current",
    "experience.employment_details.past"
  ],
  "limit": 25
}
```
Caveat (INFERENCE): the docs only guarantee same-entry matching for conditions on the same nested path; to be safe when mixing domain + title on past roles, wrap the `and` pair in an `all_of` group (docs example: `{"op":"all_of","conditions":[{"op":"and","conditions":[title cond, company_id cond]}]}`). Using `company_id` (integer) instead of domain is the documented reliable route ("This is the most reliable way to find people at one specific company").

Current role at a company with a technical-leadership title (docs recipe "Search by employer and title" uses `company_name in [...]` plus an `or` of `(.)` title conditions on `current.title`).

### Response shape
```json
{ "profiles": [ { "crustdata_person_id": 14540, "basic_profile": {...}, "experience": {"employment_details": {"current": [ ... ], "past": [ ... ]}}, "education": {...}, "social_handles": {...}, "contact": {"has_business_email": false} } ],
  "next_cursor": "H4sI...|null", "total_count": 8, "total_count_relation": null, "remarks": [] }
```
`total_count` is the full-database match count. Empty result = `200` with `"profiles": []`.

### Employment-history fields returned (each element of `experience.employment_details.current[]` / `.past[]`)
From the OpenAPI schema `PersonSearchEmploymentDetails` (https://docs.crustdata.com/api-reference/person-apis/search-people-using-filters-and-sorting.md):
`name` (company name), `title`, `description`, `start_date` (string), `end_date` (string), `is_default`, `employment_type`, `location.raw`, `crustdata_company_id`, `professional_network_id`, `company_professional_network_profile_url`, `company_website` (full URL, e.g. `"https://stripe.com"`), `seniority_level`, `function_category`, `years_at_company`, `years_at_company_raw`, `company_headcount_latest`, `company_headcount_range`, `company_industries`, `company_type`, `company_status`, `company_headquarters_country`, `company_hq_location`, `position_id`, `business_email_verified`, `company_profile_picture_permalink`. 

Filter-path vs returned-path twins (must use the returned name in `fields`, else 400): `current.company_name` -> `current.name`; `current.company_id` -> `current.crustdata_company_id`; `current.company_website_domain` -> `current.company_website` (and same for `past.`). The three all-roles paths (`experience.employment_details.company_name/company_id/company_website_domain`) are filter-only, never returned. Source: person search reference ("Filter paths and their returned twins").

Date format of `start_date`/`end_date` strings: example `'2017-01-01'` in OpenAPI; precision beyond that UNKNOWN. Whether `end_date` is null for current roles: UNKNOWN (not stated).

### Fields we must NOT request (contact info)
- Search never returns email/phone values. The only contact output is `contact.has_business_email` (boolean). A `contact` request may even 403 if not permitted (OpenAPI 403 example `Access denied to fields: contact`). Emails/phones come only from `/person/contact/enrich` or `/person/enrich` add-ons (section 4) which we should not call.
- How to exclude: send an explicit `fields` allow-list that omits `contact`. If `fields` is omitted the API returns "the default profile sections" (docs: "A request with no `fields` returns experience and education"); the exact default list (whether `contact` is included) is **UNKNOWN**, so always pass `fields`.
- Also avoid `social_handles.professional_network_identifier.profile_url` unless needed (it is a profile URL, not contact info, but it is personal identity data).
- Do not request `research_profiles` (403 without grant, extra 0.4/result).
- `skills` and `dev_platform_profiles` are not returned by search at all.

### Credits (person search)
- "Search costs `0.03` credits per result. Each premium group that you filter on or receive adds a per-result charge." Source: https://docs.crustdata.com/person-docs/search/reference.md
- Premium groups (filter / response): Experience 0.1 / 0.1; Education 0.1 / 0.1; Skills 0.1 / 0.1; Certifications 0.2 / 0.2; Professional network 0.2 / 0.2; Summary - / 0.2; Honors 0.2 / 0.2; Dev platform (GitHub basic) 0.8 filter-only; (repos) 2.5 filter-only; Research profiles 0.4 / 0.4. Source: https://docs.crustdata.com/general/pricing.md
- "A request with no `fields` returns experience and education, so it costs `0.23` per result on the standard plan." Source: person-docs/search/introduction.md
- **Budget consequence:** any employer/title filter is on `experience.*` (0.1) and returning `experience` adds another 0.1, so a typical DealScope person search = 0.03 + 0.1 (filter) + 0.1 (response) = **0.23 credits per returned person**, not 0.03. Returning only `basic_profile.*` fields with an experience filter = 0.13. A result set of 0 rows costs 0. Sorting is free.
- Unknown: whether the 0.1 experience charge applies when only a sub-path such as `experience.employment_details.past.title` is requested; docs say a root covers every path beneath it ("the longest matching prefix wins"), so assume yes. Source: https://docs.crustdata.com/general/permissions.md

### Errors
400 (unsupported field, wrong operator, bad closed-set value such as `"vp"`, filter path in `fields`, bad cursor), 401, 403 (permission/preview/field denied/credits), 413, 500.

---

## 4. Person Enrich (brief)

Sources: https://docs.crustdata.com/person-docs/enrichment/introduction.md , https://docs.crustdata.com/person-docs/enrichment/reference.md , https://docs.crustdata.com/general/pricing.md

`POST https://api.crustdata.com/person/enrich` ; body `{ "professional_network_profile_urls": [ ... up to 25 ], "fields": [ ... ] }`. Default `fields`: `basic_profile`, `social_handles` only. Response: top-level array of `{matched_on, match_type, match_status (matched|not_found|redacted), matches:[{confidence_score, person_data}]}`. Rate limit 15 RPM. Enrich is by profile URL only (no domain/title input); it is NOT a discovery tool.

Verbatim minimal request (pricing page):
```bash
curl --request POST --url https://api.crustdata.com/person/enrich \
  --header 'authorization: Bearer YOUR_API_KEY' --header 'content-type: application/json' --header 'x-api-version: 2025-11-01' \
  --data '{"professional_network_profile_urls":["https://www.linkedin.com/in/abhilashchowdhary"]}'
```

Cost (cached `/person/enrich`): pricing page says "**1-9** per record ... Starts with a base profile and scales with requested data." Base profile **1**; personal email +2; phone +2; business email +1; developer platform +1; research profiles +2; max 9. Source: general/pricing.md. (The enrich intro page says "Maximum: 4 credits per profile", excluding the contact add-ons; the two pages disagree, so keep contact fields out and expect 1 to 2.)

Cached vs realtime: `/person/enrich` serves the **cached dataset**. Fresh retrieval is `POST /person/professional_network/enrich/live`, **7 credits per profile**, 10 RPM, plan-gated (enterprise). Source: general/pricing.md , rate-limits.md. Per the person marketing page, misses are not charged ("$0, charged for a miss", https://crustdata.com/people-api); the docs say `redacted` results are never billed.

`/person/contact/enrich` (emails/phones): per requested type per matched person: business email 1, personal email 2, phone 2, `verified:true` +0.5; enterprise plans. Do NOT use. Source: pricing.md.

---

## 5. Job Listings Search

Sources: https://docs.crustdata.com/job-docs/search/introduction.md , https://docs.crustdata.com/job-docs/search/reference.md , https://docs.crustdata.com/api-reference/job-apis/search-the-indexed-job-dataset.md

`POST https://api.crustdata.com/job/search` ; headers as section 0. Body is required (`{}` matches the whole dataset).

### Request body

| Param | Type | Default | Notes |
|---|---|---|---|
| `filters` | condition or group | none | Same `{field,type,value}` / `{op,conditions}` grammar |
| `fields` | string[] | all fields | Dot paths or groups: `crustdata_job_id, job_details, company, location, content, metadata` |
| `sorts` | `[{field, order}]` | | Sortable only: `crustdata_job_id`, `metadata.date_added`, `metadata.date_updated`, `company.headcount.total`, `company.followers.count`, `company.revenue.estimated.lower_bound_usd`, `company.funding.last_fundraise_date`, `company.funding.num_funding_rounds`, `relevance` (only with a text query). Sorting on title/category/company id fails. `column` instead of `field` -> 400 |
| `limit` | int | 20 | 0 to 1000. `0` = no rows (aggregations only) |
| `cursor` | string | | `next_cursor` from previous page; keep filters/sorts/fields identical. Best-effort consistency, not a snapshot |
| `aggregations` | array | | `{type:"count"}` or `{type:"group_by", field, agg:"count", size (1-1000, default 100)}` |

Operators: `=`, `!=`, `<`, `=<`, `>`, `=>`, `in`, `not_in`, `is_null`, `is_not_null` (value `null` required), `(.)` (all-words, typo tolerant), `[.]` (exact phrase), `geo_distance`, `geo_exclude` (only on `location` / `location.raw`). Exact-match AND on the same field (e.g. two different titles with `=`) always returns zero. Dates: date-only value is read as `T00:00:00` UTC; `=>` inclusive, `<` exclusive.

### Filter field names

| Purpose | Field |
|---|---|
| Company by domain | `company.basic_info.primary_domain` (filter + group + return) |
| Company by Crustdata id | `company.basic_info.company_id` (integer alias; returned as `company.basic_info.crustdata_company_id`) |
| Company by name | `company.basic_info.name` (filter, returned; not groupable/sortable) |
| Title | `job_details.title` (`(.)`/`[.]`/`=`/`in`) |
| Category (function) | `job_details.category` e.g. `"Engineering"`, `"Sales"`, `"Operations"`, `"Others"` |
| Date posted | `metadata.date_added` ("the job-posted date: the date the listing was added on the source portal"); sortable and filterable |
| Date refreshed | `metadata.date_updated` |
| Reposted flag | `job_details.reposted_job` (boolean, filterable/returned) |
| Source | `job_details.source` (`professional_network`, `greenhouse`, `workday`, `lever`, `ashby`, `smartrecruiters`, `workable`, `icims`, `rippling`, `yc`) |
| Employment type | `job_details.employment_type` (`full_time, part_time, contract, intern, temporary`; null for `professional_network` source) |
| Workplace | `job_details.workplace_type` (`Remote`, `Hybrid`, `On-site`, `""`) |
| Description text | `content.description` (use `[.]` for exact keyword) |
| Posting technologies (filter-only) | `technographics.technologies.name/category/super_category` (case-sensitive; only for `professional_network`-sourced postings) |

### Fields returned (per `job_listings[]` item)
`crustdata_job_id`; `job_details.{job_id, title, category, workplace_type, source, employment_type, url, reposted_job, number_of_openings}`; `company.basic_info.{crustdata_company_id, name, primary_domain, website, professional_network_id, industries}`; `company.{locations, headcount.{total,range,largest_headcount_country}, followers.count, revenue, funding.{total_investment_usd, valuation_usd, last_fundraise_date, last_round_type, num_funding_rounds, investors}, competitors}`; `location.{raw, city, district, state, country, pincode}`; `content.description`; `metadata.{date_added, date_updated}`. Timestamp format: `"2026-04-07T11:37:29"`.
Mapping to our needs: title = `job_details.title`; date posted = `metadata.date_added`; date updated = `metadata.date_updated`; reposted flag = `job_details.reposted_job`; openings count per posting = `job_details.number_of_openings` (returned only, not filterable); url = `job_details.url`; category = `job_details.category`.

### Verbatim minimal request (docs "first search", trimmed to one field set)
```bash
curl --request POST \
  --url https://api.crustdata.com/job/search \
  --header 'authorization: Bearer YOUR_API_KEY' \
  --header 'content-type: application/json' \
  --header 'x-api-version: 2025-11-01' \
  --data '{
    "filters": {
      "op": "and",
      "conditions": [
        { "field": "company.basic_info.company_id", "type": "=", "value": 631394 },
        { "field": "job_details.title", "type": "=", "value": "Software Engineer" }
      ]
    },
    "fields": ["job_details.title","job_details.url","company.basic_info.name","location.raw","metadata.date_added"],
    "sorts": [ { "field": "metadata.date_added", "order": "desc" } ],
    "limit": 2
  }'
```
Our use case (INFERENCE from documented fields): by domain, engineering, last 90 days:
```json
{
  "filters": { "op": "and", "conditions": [
    { "field": "company.basic_info.primary_domain", "type": "=", "value": "example.com" },
    { "field": "job_details.category", "type": "=", "value": "Engineering" },
    { "field": "metadata.date_added", "type": "=>", "value": "2026-07-13" } ] },
  "fields": ["crustdata_job_id","job_details.title","job_details.category","job_details.url","job_details.reposted_job","job_details.number_of_openings","metadata.date_added","metadata.date_updated"],
  "sorts": [{ "field": "metadata.date_added", "order": "desc" }],
  "limit": 100
}
```

### Response shape
```json
{ "job_listings": [ { "crustdata_job_id": 41053563, "job_details": {...}, "company": {...}, "location": {...}, "content": {...}, "metadata": {...} } ],
  "next_cursor": "H4sI...|null", "total_count": 18, "aggregations": [ ... ] }
```
`total_count` can be `null` for very broad queries. Count aggregation response: `{"type":"count","field":null,"value":549}`. group_by buckets: `{key, count, metadata:{company_name, company_website_domain, linkedin_id}}`.

Freshness caveat: "Closed or removed listings are **not** guaranteed to disappear from the index immediately." To approximate currently hiring, filter a recent `metadata.date_added` window. Source: job-docs/search/reference.md

### Credits - JOBS PRICE
- "**Pricing:** `0.03 credits per result returned`. A request with no results does not consume credits." Source: https://docs.crustdata.com/job-docs/search/introduction.md
- Pricing table: "`/job/search` | **0.03** per result | Indexed job discovery, filtering, and hiring analysis." Source: https://docs.crustdata.com/general/pricing.md
- **Counts are effectively free:** "To get just the total number of jobs matching a filter, send a `count` aggregation with `limit: 0`. No job rows are returned, so the call consumes no per-result credits." Source: job-docs/search/introduction.md (so `limit: 0` + `total_count` is the cheap way to count postings per company; still counts against the 30 RPM limit).
- Radius (geo) queries: "no new credit cost" (changelog, https://docs.crustdata.com/openapi-specs/2025-11-01/changelog.md).
- No premium surcharges are documented for Jobs. The marketing page https://crustdata.com/apis/job-listing only says "Job listing calls draw from the same credit balance as every other Crustdata endpoint." and "There is no separate jobs subscription." (no per-call price). The credit number comes from the docs pages above.
- Live job search (not needed): `/job/professional_network/search/live`, 2 credits per result, 10 RPM, enterprise/plan-gated.
- Batch: `POST /batch/job/search` 0.03 per result, up to 10 companies per job (https://docs.crustdata.com/general/pricing.md , job intro).
- Rate limit: 30 requests per minute.

### Errors
400 `invalid_request` (limit out of range, `column` instead of `field`), 401, **500** `internal_error` for unsupported filter field (`"Unsupported columns in conditions: [...]"`), unsupported `group_by` field, malformed geo value. Groupable: `company.basic_info.{company_id, crustdata_company_id, industries, primary_domain}`, `company.funding.last_round_type`, `company.headcount.range`, `company.locations.country`, `job_details.{category, employment_type, source, title, workplace_type}`, `location.country`.

---

## 6. Free endpoints, autocomplete, account endpoints

| Endpoint | Cost | Notes | Source |
|---|---|---|---|
| `GET /account/credits` | Free | No params. Response `{ "account": { "credits": 9406.5, "recurring_credits": 10000, "recurring_credits_frequency": "monthly", "recurring_credits_refresh_date": "..." } }` (+ optional `wallets[]`, `credit_topups[]`). 300 RPM. 401 body `{ "message": "Missing API key in request" }` | https://docs.crustdata.com/general/credits.md |
| `GET /account/endpoints` | Free | Optional `?path=/company/enrich` (exact, case-sensitive), `?category=`, `?status=enabled|disabled`. Returns per-endpoint `status`, `effective_rate_limit_rpm`, `fields.enabled/disabled`, `base_credits`, `premium_fields[]`, `premium_filters[]`, `premium_modes[]` = YOUR account's actual prices. Always pass `path` (unfiltered payload ~89 KB). 300 RPM | https://docs.crustdata.com/general/permissions.md |
| `GET /account/usage/summary`, `/account/usage/events`, `/account/usage/events/{request_id}`, `/account/usage/errors` | Free | Shared 60 RPM; no `X-Credits-Used` header; events appear within ~10 s | https://docs.crustdata.com/general/usage.md |
| `GET /batch/{batch_id}`, `GET /batch/` | Free | | pricing.md |
| `POST /company/identify` | Free | 30 RPM | pricing.md |
| `POST /company/search/autocomplete` | Free | Body `{field, query ("" = most common), limit (default 20, max 100)}`; response `{ "suggestions": [ {"value": "..."} ] }`. No `filters` scope | https://docs.crustdata.com/company-docs/autocomplete/introduction.md |
| `POST /person/search/autocomplete` | Free | Same shape; `field` is the RETURNED path, e.g. `experience.employment_details.current.title`, not the filter path. Covers `title, name, company_industries, seniority_level, function_category` on current/past/all paths | https://docs.crustdata.com/person-docs/autocomplete/introduction.md , person search reference |
| `POST /job/search/autocomplete` | Free | Same shape; example `field: "title"`. Also serves `technology`, `technology_category` | https://docs.crustdata.com/job-docs/autocomplete/introduction.md |

The CreditGovernor can poll `GET /account/credits` (free) before/after each run, and read `X-Credits-Used` on every response (header present on success AND error responses; "Endpoints that don't consume credits report `0`"; absent on rate-limit 429s generated before reaching the API). Balance deduction rounds fractional cost up to the next whole credit, so summed header values can be slightly below the balance change. Source: general/credits.md.

---

## 7. Credit cost summary for DealScope planning

| Call | Credits | Source |
|---|---|---|
| Company Identify (domain -> id) | 0 | pricing.md |
| Company Enrich (domain) | 2 per matched record (+2 if technographics returned) | enrich intro |
| Company Search | 0.03/result + 0.2 per premium group filtered and/or returned (headcount, funding, hiring each 0.2) | pricing.md |
| Person Search | 0.03/result + 0.1 experience (filter) + 0.1 experience (response) = ~0.23/result with experience returned | pricing.md |
| Person Enrich (cached) | 1 base (up to 9 with contact add-ons) | pricing.md |
| Person Enrich live | 7 | pricing.md |
| Jobs Search | 0.03 per result returned; `limit:0` count = 0 | job intro |
| Autocomplete (all), account/credits, account/endpoints, usage | 0 | pricing.md |

Discrepancy with `docs/06-crustdata-credit-budget.md`: that file budgets "People search 0.03 credits/result" (line 24, 40) and "Jobs: exact cost must be verified" (line 42, 74). Update: person search is ~0.23 credits per result when employment history is filtered/returned, and Jobs is 0.03 per result per the official docs (confirm with `GET /account/endpoints?path=/job/search` and the first `X-Credits-Used`).

## 8. Open items / uncertainties (do not assume)

1. `headcount.by_role_absolute` / `by_role_percent` map key names (casing and spelling) are not documented; capture from a live response and log. 
2. No documented per-department headcount growth scalar in enrich. Derive from `headcount.by_function_timeseries.CURRENT_FUNCTION.<Function>` (date format `"YYYY-MM-DD 00:00:00"` per example) and/or `hiring.by_function_qoq_pct|6m_pct`.
3. `hiring.recent_openings` may be field-gated per account (appears as a disabled field in docs examples); verify with `/account/endpoints?path=/company/enrich`. Jobs API (`/job/search`) is the alternative source of openings.
4. Whether dotted sub-paths (e.g. `headcount.total`) work in non-batch `/company/enrich` `fields`: not documented (only group names documented; batch documents dotted paths).
5. Default `fields` set for `/person/search` when omitted (docs: "experience and education"); whether `contact` is included is not stated. Always pass explicit `fields`.
6. `end_date` null-ness for current roles and date string precision in person employment entries: not documented.
7. No documented `...past.end_date` filter path (only the all-roles `experience.employment_details.end_date`).
8. Rate-limit figures differ between pages for person/job autocomplete (300 vs 45; job 30 vs absent). Pages warn limits vary by plan; read `effective_rate_limit_rpm` from `/account/endpoints`.
9. Charge for company-enrich no-match inputs: not documented.
10. Hackathon/partner accounts may have negotiated prices; the pricing page says list prices apply "unless negotiated" and that `/account/endpoints` is authoritative for your account.
11. Marketing pages (company-data-api, people-api, job-listing) contain no plan dollar prices; "See pricing" links to mcp.crustdata.com (not fetched). Dollar-per-credit: UNKNOWN - not documented in the docs pages reviewed.
