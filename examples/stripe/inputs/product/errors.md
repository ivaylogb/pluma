<!--
sources:
  - https://docs.stripe.com/api/errors.md
  - https://docs.stripe.com/error-codes.md
  - https://docs.stripe.com/connect/handling-api-verification.md
  - https://github.com/stripe/stripe-python/blob/41a2ece934c8d365b9fc88253bc3c4675913d09e/stripe/_error.py
retrieved: 2026-05-15T20:15:51Z
note: |
  Distilled flat catalog of Stripe errors a developer hits while moving a
  Connect connected account from creation toward charges_enabled. Codes,
  HTTP statuses, trigger conditions, and suggested actions are taken
  faithfully from the Stripe sources listed above; descriptions stay close
  to Stripe's own wording. Out-of-scope codes (pure card declines, Terminal,
  Issuing, Tax-only, Financial Connections) are excluded except where they
  intersect the onboarding path.
-->

# Stripe Connect onboarding error catalog

The onboarding path has three distinct failure layers, and a developer
debugging "why isn't `charges_enabled` true" can be stuck at any of them:

1. **Transport / auth** — the request never reaches account logic
   (wrong key, wrong mode, not a platform).
2. **Request shape** — `invalid_request_error` on `POST /v1/accounts`,
   `POST /v1/accounts/{id}/persons`, etc. (missing/invalid params).
3. **Verification state** — the request succeeded but the account is gated:
   `requirements.currently_due` is non-empty, `requirements.disabled_reason`
   is set, or `requirements.errors[]` contains validation/verification codes.

Layer 3 is the one most developers don't anticipate: the API returns `200`,
the `Account` object exists, and `charges_enabled` is still `false`.

---

## Error types and HTTP status (api/errors.md)

`StripeError.code` is a short string; `type` is one of the enum values below.

| Type | Meaning | Source |
|---|---|---|
| `api_error` | Problem on Stripe's side (e.g. temporary server problem); extremely uncommon. | https://docs.stripe.com/api/errors.md |
| `card_error` | The user entered a card that can't be charged. Most common at payment time, not onboarding. | https://docs.stripe.com/api/errors.md |
| `idempotency_error` | An `Idempotency-Key` was reused on a request that doesn't match the first request's endpoint and parameters. | https://docs.stripe.com/api/errors.md |
| `invalid_request_error` | The request has invalid parameters. This is the dominant type during account/person creation. | https://docs.stripe.com/api/errors.md |

| HTTP | Name | When | Source |
|---|---|---|---|
| 200 | OK | Everything worked as expected. Note: a `200` does **not** mean the account is enabled. | https://docs.stripe.com/api/errors.md |
| 400 | Bad Request | Request was unacceptable, often a missing required parameter. | https://docs.stripe.com/api/errors.md |
| 401 | Unauthorized | No valid API key provided. | https://docs.stripe.com/api/errors.md |
| 402 | Request Failed | Parameters valid but the request failed. | https://docs.stripe.com/api/errors.md |
| 403 | Forbidden | The API key doesn't have permissions to perform the request. | https://docs.stripe.com/api/errors.md |
| 404 | Not Found | The requested resource doesn't exist. | https://docs.stripe.com/api/errors.md |
| 409 | Conflict | Request conflicts with another request (e.g. same idempotency key). | https://docs.stripe.com/api/errors.md |
| 424 | External Dependency Failed | Failure in a dependency external to Stripe. | https://docs.stripe.com/api/errors.md |
| 429 | Too Many Requests | Rate limited; use exponential backoff. | https://docs.stripe.com/api/errors.md |
| 500/502/503/504 | Server Errors | Something went wrong on Stripe's end (rare). | https://docs.stripe.com/api/errors.md |

---

## Layer 1 — transport / auth / mode (error-codes.md)

| Code | HTTP | When it's thrown | Suggested action | Source |
|---|---|---|---|---|
| `secret_key_required` | 401 | A publishable key (`pk_...`) was used where a secret key (`sk_...`) is required — common when a frontend key is copied into server-side Connect calls. | Obtain current API keys from the Dashboard and use the secret key server-side. | https://docs.stripe.com/error-codes.md |
| `api_key_expired` | 401 | The API key provided has expired. | Obtain current API keys from the Dashboard and update the integration. | https://docs.stripe.com/error-codes.md |
| `platform_api_key_expired` | 401 | The Connect platform's API key has expired — platform generated a new key, or the connected account was disconnected from the platform. | Obtain current API keys, update the integration, or reconnect the account. | https://docs.stripe.com/error-codes.md |
| `account_invalid` | 403 | The account ID passed in the `Stripe-Account` header is invalid (e.g. acting on behalf of an account that doesn't belong to the platform). | Check that requests specify a valid connected account ID. | https://docs.stripe.com/error-codes.md |
| `platform_account_required` | 403 | A non-platform account tried to work with other accounts (Connect not enabled). | Set up a Stripe Connect platform in the Dashboard. | https://docs.stripe.com/error-codes.md |
| `livemode_mismatch` | 400 | Test and live mode keys/requests/objects were crossed (e.g. a `acct_` created in test mode referenced with a live key). | Use keys, requests, and objects within the corresponding mode only. | https://docs.stripe.com/error-codes.md |
| `testmode_charges_only` | 402 | The platform account can only make test charges; live charge attempted. | Complete the platform's own onboarding in the Dashboard to process live charges. | https://docs.stripe.com/error-codes.md |
| `rate_limit` | 429 | Too many requests hit the API too quickly. | Apply exponential backoff. | https://docs.stripe.com/error-codes.md |
| `idempotency_key_in_use` | 409 | The idempotency key is currently in use by another in-flight request (duplicate concurrent calls). | Serialize the requests; don't fire duplicates simultaneously. | https://docs.stripe.com/error-codes.md |

---

## Layer 2 — request shape on account / person creation (error-codes.md)

These arrive as `invalid_request_error` (HTTP 400) on `POST /v1/accounts`,
`POST /v1/accounts/{id}/persons`, and `POST /v1/account_links`.

| Code | HTTP | When it's thrown | Suggested action | Source |
|---|---|---|---|---|
| `parameter_missing` | 400 | One or more required values are missing (e.g. `country`, `capabilities`, person fields). | Check API docs for which values are required to create/modify the resource. | https://docs.stripe.com/error-codes.md |
| `parameter_unknown` | 400 | The request contains one or more unexpected parameters (e.g. a v2-style field on a v1 `POST /v1/accounts`). | Remove the unexpected parameters and retry. | https://docs.stripe.com/error-codes.md |
| `parameter_invalid_empty` | 400 | One or more required values weren't provided. | Include all required parameters. | https://docs.stripe.com/error-codes.md |
| `parameter_invalid_string_empty` | 400 | One or more required string values is empty. | Ensure string values contain at least one character. | https://docs.stripe.com/error-codes.md |
| `parameter_invalid_integer` | 400 | A parameter requires an integer but a different type was sent. | Send the supported type; check the API reference. | https://docs.stripe.com/error-codes.md |
| `resource_missing` | 404 | The ID provided isn't valid — resource doesn't exist or an ID for a different resource was used (e.g. a person ID where an account ID is expected). | Verify the ID and resource type. | https://docs.stripe.com/error-codes.md |
| `resource_already_exists` | 400 | A resource with a user-specified ID already exists. | Use a different unique `id`. | https://docs.stripe.com/error-codes.md |
| `email_invalid` | 400 | The account/person email address is invalid (e.g. not properly formatted). | Validate the email format before submitting. | https://docs.stripe.com/error-codes.md |
| `url_invalid` | 400 | The URL provided (e.g. `business_profile.url`, `account_links` return/refresh URL) is invalid. | Provide a valid URL. | https://docs.stripe.com/error-codes.md |
| `country_code_invalid` | 400 | The `country` code provided was invalid. | Send a valid ISO country code. | https://docs.stripe.com/error-codes.md |
| `country_unsupported` | 400 | Platform attempted to create a custom account in a country not yet supported. | Restrict signups to countries supported by custom accounts. | https://docs.stripe.com/error-codes.md |
| `account_country_invalid_address` | 400 | The country of the business address doesn't match the country of the account. | Businesses must be located in the same country as the account. | https://docs.stripe.com/error-codes.md |
| `account_error_country_change_requires_additional_steps` | 400 | The platform tried to change the account country after Connect onboarding. | Contact Stripe support — country change requires extra steps. | https://docs.stripe.com/error-codes.md |
| `state_unsupported` | 400 | `legal_entity` for a U.S. custom account specifies an unsupported state (mostly associated states/territories). | Use a supported state. | https://docs.stripe.com/error-codes.md |
| `tax_id_invalid` | 400 | The tax ID number provided is invalid (e.g. missing digits). | Tax ID must be at least nine digits; validate before submit. | https://docs.stripe.com/error-codes.md |
| `account_holder_name_verification_failed` | 402 | The bank account holder name doesn't match the name on file for the external account. | Correct the account holder name on the external account. | https://docs.stripe.com/error-codes.md |
| `account_number_invalid` | 400 | The external bank account number provided is invalid. | Validate entry forms against Stripe's per-country bank account formats. | https://docs.stripe.com/error-codes.md |
| `account_closed` | 402 | The provided bank account has been closed. | Collect a different external account. | https://docs.stripe.com/error-codes.md |
| `bank_account_unusable` | 402 | The bank account provided can't be used. | Use a different bank account. | https://docs.stripe.com/error-codes.md |
| `bank_account_unverified` | 402 | The platform is attempting to share an unverified bank account with a connected account. | Verify the bank account before sharing it. | https://docs.stripe.com/error-codes.md |
| `bank_account_exists` | 400 | The bank account already exists on the specified object. | Reference the existing external account instead of re-adding. | https://docs.stripe.com/error-codes.md |
| `bank_account_bad_routing_numbers` | 400 | The bank account doesn't support the currency in question. | Collect an account that supports the payout currency. | https://docs.stripe.com/error-codes.md |
| `progressive_onboarding_limit_exceeded` | 402 | The platform reached its progressive (incremental) onboarding limit — accounts collected minimal info and now must complete full verification. | Collect the remaining required information for accounts. | https://docs.stripe.com/error-codes.md |

---

## Layer 3a — `requirements.disabled_reason` (handling-api-verification.md)

The API call succeeded; the account is gated. `disabled_reason` describes
why charges/transfers are disabled. Surfaced on the `Account` object, not as
an exception.

| Value | When | Suggested action | Source |
|---|---|---|---|
| `requirements.past_due` | Additional verification information is required to enable capabilities; a `current_deadline` passed. | Collect and submit the `requirements.past_due` / `currently_due` fields. | https://docs.stripe.com/connect/handling-api-verification.md |
| `requirements.pending_verification` | Stripe is currently verifying submitted information. No action required. | Inspect `requirements.pending_verification`; wait for `account.updated`. | https://docs.stripe.com/connect/handling-api-verification.md |
| `listed` | The account might be on a prohibited persons/companies list; Stripe investigates. | Wait for Stripe's investigation outcome. | https://docs.stripe.com/connect/handling-api-verification.md |
| `rejected.fraud` | Account rejected for suspected fraud or illegal activity. | Account is rejected; appeal via Dashboard if applicable. | https://docs.stripe.com/connect/handling-api-verification.md |
| `rejected.incomplete_verification` | Rejected because verification requirements weren't completed within the required threshold. | Account is rejected; appeal via Dashboard if applicable. | https://docs.stripe.com/connect/handling-api-verification.md |
| `rejected.listed` | Rejected because it's on a third-party prohibited persons/companies list. | Account is rejected; appeal via Dashboard if applicable. | https://docs.stripe.com/connect/handling-api-verification.md |
| `rejected.terms_of_service` | Rejected for suspected terms of service violations. | Account is rejected; appeal via Dashboard if applicable. | https://docs.stripe.com/connect/handling-api-verification.md |
| `rejected.other` | Rejected for another reason. | Account is rejected; appeal via Dashboard if applicable. | https://docs.stripe.com/connect/handling-api-verification.md |

---

## Layer 3b — `requirements.errors[].code` validation/verification codes

These appear inside the `Account.requirements.errors[]` array (and the
equivalent per-`Person` / per-`Capability` arrays). Each entry explains why
a `currently_due` requirement hasn't been met. HTTP is `200` — the developer
must poll/inspect rather than catch an exception.

| Code | When | Suggested action | Source |
|---|---|---|---|
| `invalid_address_city_state_postal_code` | Stripe couldn't validate the city/state/postal-code combination. | Re-collect a consistent address. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_street_address` | Stripe couldn't validate the street name or number. | Re-collect a valid physical street address. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_address_highway_contract_box` | Address is a highway contract box, not a physical address. | Collect a valid physical address the account does business from. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_address_private_mailbox` | Address is a private mailbox, not a physical address. | Collect a valid physical address the account does business from. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_dob_age_under_minimum` | The person is under the minimum age (must be at least 13). | Re-collect an accurate date of birth. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_dob_age_over_maximum` | The person's date of birth is more than 120 years ago. | Re-collect an accurate date of birth. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_phone_number` | Stripe couldn't validate the phone number on the account. | Match formatting to the person's country. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_tax_id` / `invalid_tax_id_format` | Tax ID invalid or wrong format (must be 9 digits, no separators). | Re-collect the tax ID in the required format. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_business_profile_name` | Business name isn't easily understandable / not recognizable words. | Collect a clear business name. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_business_profile_name_denylisted` | Business name is generic or a well-known name and doesn't match the account. | Collect the account's real business name. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_product_description_length` | Product description shorter than 10 characters. | Collect a longer product description. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_product_description_url_match` | Product description is identical to the business URL. | Collect a distinct product description. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_statement_descriptor_length` | Statement descriptor shorter than 5 characters. | Collect a longer statement descriptor. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_statement_descriptor_business_mismatch` | Statement descriptor doesn't resemble the business name. | Align the descriptor with the business. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_statement_descriptor_denylisted` / `invalid_statement_descriptor_prefix_denylisted` | Descriptor matches a generic or well-known business name. | Use a descriptor specific to the account. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_statement_descriptor_prefix_mismatch` | Statement descriptor prefix doesn't resemble the business name. | Align the prefix with the business. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_url_format` | `business_profile.url` is not a well-formed URL. | Collect a valid URL. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_url_denylisted` | The URL is on a denylist. | Collect the account's real website. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_url_web_presence_detected` | A web presence was detected but the provided URL doesn't reflect it. | Provide the account's actual web presence. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_url_website_business_information_mismatch` | The website's business information doesn't match the account. | Reconcile website content with account info. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_url_website_empty` | The website has no content. | Provide a populated website. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_url_website_inaccessible` | The website is inaccessible to Stripe. | Make the website publicly reachable. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_url_website_inaccessible_geoblocked` | The website is geoblocked from Stripe. | Remove geoblocking or provide an accessible URL. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_url_website_inaccessible_password_protected` | The website is password protected. | Remove the password gate or provide an accessible URL. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_url_website_incomplete` | The website is missing required business content. | Add the missing business content. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_url_website_incomplete_cancellation_policy` | Website missing a cancellation policy. | Add a cancellation policy. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_url_website_incomplete_customer_service_details` | Website missing customer service details. | Add customer service details. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_url_website_incomplete_legal_restrictions` | Website missing legal restriction information. | Add legal restriction information. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_url_website_incomplete_refund_policy` | Website missing a refund policy. | Add a refund policy. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_url_website_incomplete_return_policy` | Website missing a return policy. | Add a return policy. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_url_website_incomplete_terms_and_conditions` | Website missing terms and conditions. | Add terms and conditions. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_url_website_incomplete_under_construction` | Website is under construction. | Publish a complete website. | https://docs.stripe.com/connect/handling-api-verification.md |
| `invalid_url_website_other` | Website fails verification for another reason. | Review website against Stripe requirements. | https://docs.stripe.com/connect/handling-api-verification.md |
| `verification_document_failed_copy` | Submitted ID document appears to be a copy, not an original. | Re-collect an original identity document. | https://docs.stripe.com/connect/handling-api-verification.md |
| `verification_document_failed_greyscale` | Submitted ID document is greyscale. | Re-collect a color document scan/photo. | https://docs.stripe.com/connect/handling-api-verification.md |

> The `verification_document_failed_*` and `invalid_url_website_*` families
> have additional members; the rows above are the onboarding-relevant subset
> documented at the source URL. See `requirements.md` and `persons.md` (this
> directory) for the full per-country / per-capability requirement lists.

---

## SDK exception classes (stripe-python `stripe/_error.py`)

What stripe-python actually raises. Note: Layer 3 verification state is
**not** an exception — it's data on a successfully returned object, so
`try/except` never fires for it. This is a primary onboarding confusion.

| Class | Base | Raised when | Source |
|---|---|---|---|
| `StripeError` | `Exception` | Base class; carries `message`, `code`, `http_status`, `json_body`, `request_id`. | https://github.com/stripe/stripe-python/blob/41a2ece934c8d365b9fc88253bc3c4675913d09e/stripe/_error.py |
| `APIError` | `StripeError` | Generic API problem on Stripe's side. | .../stripe/_error.py |
| `APIConnectionError` | `StripeError` | Network failure talking to the API. | .../stripe/_error.py |
| `StripeErrorWithParamCode` | `StripeError` | Base for errors carrying `param` and `code`. | .../stripe/_error.py |
| `CardError` | `StripeErrorWithParamCode` | A card can't be charged (payment time, not onboarding). | .../stripe/_error.py |
| `IdempotencyError` | `StripeError` | Idempotency key reused with mismatched endpoint/params. | .../stripe/_error.py |
| `InvalidRequestError` | `StripeErrorWithParamCode` | Invalid parameters — the dominant exception on `accounts.create` / `persons.create`. Carries `param`. | .../stripe/_error.py |
| `AuthenticationError` | `StripeError` | No valid API key (`secret_key_required`, expired key). | .../stripe/_error.py |
| `PermissionError` | `StripeError` | Key lacks permission for the request (`account_invalid`, `platform_account_required`). | .../stripe/_error.py |
| `RateLimitError` | `StripeError` | Too many requests too quickly. | .../stripe/_error.py |
| `SignatureVerificationError` | `StripeError` | Webhook signature verification failed (relevant when handling `account.updated`). | .../stripe/_error.py |
| `TemporarySessionExpiredError` | `StripeError` | A temporary session expired. | .../stripe/_error.py |
