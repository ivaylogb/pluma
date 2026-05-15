<!-- source: https://docs.stripe.com/connect/handling-api-verification.md | retrieved: 2026-05-15T20:15:51Z -->

# Handle verification with the API

Learn how Connect platforms can use webhooks and the API to handle verification of connected accounts.

Connect platforms that onboard connected accounts using the API must provide Stripe with required information for [Know Your Customer](https://support.stripe.com/questions/know-your-customer) (KYC) purposes and to enable [account capabilities](https://docs.stripe.com/connect/account-capabilities.md). They must collect the information themselves and use the Accounts and Persons APIs to provide it to Stripe. We then verify the information, asking for more details when needed.

Responsible platforms must also monitor their connected accounts’ requirement statuses and [handle any updates](https://docs.stripe.com/connect/handle-verification-updates.md) in a timely manner.

## Verification process

Before enabling charges and *payouts* (A payout is the transfer of funds to an external account, usually a bank account, in the form of a deposit) for a connected account, Stripe needs certain information that varies based on:

- The origin country of the connected accounts
- The [service agreement type](https://docs.stripe.com/connect/service-agreement-types.md) applicable to the connected accounts
- The [capabilities](https://docs.stripe.com/connect/account-capabilities.md) requested for the connected accounts
- The [business_type](https://docs.stripe.com/api/accounts/object.md#account_object-business_type) (for example, individual or company) and [company.structure](https://docs.stripe.com/api/accounts/object.md#account_object-company-structure) (for example, `public_corporation` or `private_partnership`)

Platforms must choose the proper [onboarding flow](https://docs.stripe.com/connect/identity-verification.md#onboarding-flows) for their business and connected accounts to meet the KYC requirements. That means providing all the requisite information up front or incrementally. Either way, set up your integration to watch for and respond to requests from Stripe.

1. Establish a [Connect webhook](https://docs.stripe.com/connect/webhooks.md) URL in your [webhook settings](https://dashboard.stripe.com/account/webhooks) to watch for activity, especially `account.updated` events. When using the [Persons API](https://docs.stripe.com/api/persons.md), also watch for `person.updated` events.
1. Immediately after creating an account, check the `Account` object’s [requirements.currently_due](https://docs.stripe.com/api/accounts/object.md#account_object-requirements-currently_due) attribute for additional requirements. Obtain any required information from the connected account and update the `Account`. As long as `requirements.currently_due` isn’t empty, the `Account` has outstanding requirements that might restrict its capabilities.
1. Continue watching for `account.updated` event notifications to see if the `requirements` hash changes, and ask the connected account for additional information as needed.

When you provide additional information, you don’t need to resubmit previously verified details. For example, if the `dob` is already verified, you don’t need to provide it again unless it changes.

### Stripe risk review requirements

Stripe risk reviews of a connected account can add extra requirements, which you can’t provide using the API. You can [take action in your Dashboard](https://docs.stripe.com/connect/dashboard/managing-individual-accounts.md#actions-required), or the connected account can provide them through a [Connect embedded component](https://docs.stripe.com/connect/supported-embedded-components.md#onboarding-and-compliance), [Stripe-hosted onboarding](https://docs.stripe.com/connect/hosted-onboarding.md), or [remediation link](https://docs.stripe.com/connect/dashboard/remediation-links.md).

## Determine if verification is needed 

The `charges_enabled` and `payouts_enabled` attributes on an `Account` object indicate whether it can create charges and accept payouts.

If either of those attributes is false, check the `Account`’s `requirements` hash to determine what information is needed to enable charges and payouts.

The `requirements` hash contains the following properties:

| Property               | Description                                                                                                                                                                                                                                                                                                                                                                                                                                         |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `current_deadline`     | The date by which you must resolve the requirements in `currently_due` to keep the account `active`. This is the earliest deadline across all of the account’s requested capabilities and risk requirements, including any hidden capabilities.                                                                                                                                                                                                     |
| `currently_due`        | An array containing the requirements that you must resolve by the `current_deadline` for the account to remain `active`.                                                                                                                                                                                                                                                                                                                            |
| `disabled_reason`      | A description of why the account isn’t enabled and why it can’t process charges or transfers.                                                                                                                                                                                                                                                                                                                                                       |
| `errors`               | An array containing details about any `currently_due` requirements with errors that you must resolve. For more information, see the [Validation and verification errors](https://docs.stripe.com/connect/handling-api-verification.md#validation-and-verification-errors) section.                                                                                                                                                                  |
| `eventually_due`       | An array containing the requirements that you might need to resolve, depending on whether the corresponding thresholds are reached. After one of these potential requirements becomes required, it appears in both the `eventually_due` and `currently_due` arrays. If a requirement becomes required and its due date is before the existing `current_deadline`, the `current_deadline` changes to the corresponding threshold’s enforcement date. |
| `past_due`             | An array containing the requirements that have disabled capabilities because they weren’t resolved before the `current_deadline`. The `past_due` array is a subset of `currently_due`.                                                                                                                                                                                                                                                              |
| `pending_verification` | An array containing requirements that are being reviewed or that might become required based on the review. This array is empty unless an asynchronous verification is pending. Unsuccessful verification moves a requirement to `eventually_due`, `currently_due`, `alternative_fields_due`, or `past_due`. A requirement that failed and is pending verification can also remain in `pending_verification`.                                       |

The example below shows what the `requirements` hash might look like for an account that has information that’s `currently_due`, information that’s `eventually_due`, and information that raised verification `errors`.

```json
{
  "id": ""{{CONNECTED_ACCOUNT_ID}}"",
  "object": "account",
  "requirements": {
      "alternatives": [],
      "current_deadline": 1529085600,
      "currently_due": [
          "company.tax_id",
          "company.verification.document",
          "tos_acceptance.date",
          "tos_acceptance.ip"
      ],
      "disabled_reason": null,
      "errors": [
          {
            "requirement": "company.verification.document",
            "reason": "The company name on the account couldn't be verified. Either update your business name or upload a document containing the business name.",
            "code": "failed_name_match"
          }
      ],
      "eventually_due": [
          "company.address.city",
          "company.address.line1",
          "company.address.postal_code",
          "company.address.state",
          "company.tax_id",
          "company.verification.document",
          "external_account",
          "tos_acceptance.date",
          "tos_acceptance.ip"
      ],
      "past_due": [],
      "pending_verification": []
  },
  ...
}
```

If `requirements.currently_due` contains entries, check `requirements.current_deadline`, which is a Unix timestamp. Stripe typically disables payouts on the account if we don’t receive the information by the `current_deadline`. However, other consequences might apply in some situations. For example, if payouts are already disabled and the account is unresponsive to our inquiries, Stripe might also disable the ability to process charges.

Separately, the [requirements.disabled_reason](https://docs.stripe.com/api/accounts/object.md#account_object-requirements-disabled_reason) property can contain a string describing why the account has certain capabilities disabled. In some situations, platforms and connected accounts can submit a form to resolve or appeal the reason.

- Connected accounts with access to the full Stripe Dashboard, including Standard accounts, can access additional information (if available) in the Dashboard.
- Platforms can look up an account’s `disabled_reason` on the [Connected accounts](https://docs.stripe.com/connect/dashboard/review-actionable-accounts.md) page. You might be able to provide additional information on behalf of your connected accounts. If the disabled reason is associated with an appeal, you can generate a link to a form for the account to resolve the appeal.

| Reason                                   | Meaning                                                                                                                                                                                                                                                                                  |
| ---------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `action_required.requested_capabilities` | You must [request capabilities](https://docs.stripe.com/connect/account-capabilities.md#requesting-unrequesting) for the connected account.                                                                                                                                              |
| `listed`                                 | The account might be on a prohibited persons or companies list. Stripe investigates and either rejects or reinstates the account accordingly.                                                                                                                                            |
| `rejected.fraud`                         | The account is rejected because of suspected fraud or illegal activity.                                                                                                                                                                                                                  |
| `rejected.incomplete_verification`       | The account is rejected from incomplete verification requirements within the required threshold.                                                                                                                                                                                         |
| `rejected.listed`                        | The account is rejected because it’s on a third-party prohibited persons or companies list, for example, a financial services provider or government.                                                                                                                                    |
| `rejected.other`                         | The account is rejected for another reason.                                                                                                                                                                                                                                              |
| `rejected.terms_of_service`              | The account is rejected because of suspected terms of service violations.                                                                                                                                                                                                                |
| `requirements.past_due`                  | Additional verification information is required to enable capabilities on this account.                                                                                                                                                                                                  |
| `requirements.pending_verification`      | Stripe is currently verifying information on the connected account. No action is required. Inspect the [requirements.pending_verification](https://docs.stripe.com/api/accounts/object.md#account_object-requirements-pending_verification) array to see the information being verified. |
| `under_review`                           | The account is under review by Stripe.                                                                                                                                                                                                                                                   |

## Validation and verification errors 

The `Account` object includes a [requirements.errors](https://docs.stripe.com/api/accounts/object.md#account_object-requirements-errors) array that explains why the validation or verification requirements haven’t been met. You must fulfill these requirements in order to enable the account’s capabilities.

The `errors` array has the following attributes:

| Attribute     | Description                                                                                                                                                                              |
| ------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `code`        | Indicates the type of error that occurred. See the [API reference](https://docs.stripe.com/api/accounts/object.md#account_object-requirements-errors-code) for all possible error codes. |
| `reason`      | A plain language message that explains why the error occurred and how to resolve it.                                                                                                     |
| `requirement` | Specifies which information from the `currently_due` or `alternative_fields_due` array is needed.                                                                                        |

The following example shows an `errors` array for an account with requirements that are `currently_due`, the reason why the submitted information can’t be used to enable the account, and how to resolve the error.

```json
{
  "id": ""{{CONNECTED_ACCOUNT_ID}}"",
  "object": "account",
  "requirements": {
      "current_deadline": 1234567800,
      "currently_due": [
          "company.address.line1",
          "{{PERSON_ID}}.verification.document"
      ],
      "errors": [
          {
            "requirement": "company.address.line1",
            "code": "invalid_street_address",
            "reason": "The provided street address cannot be found. Please verify the street name and number are correct in \"10 Downing Street\""
          },
          {
            "requirement": "{{PERSON_ID}}.verification.document",
            "code": "verification_document_failed_greyscale",
            "reason": "Greyscale documents cannot be read. Please upload a color copy of the document."
          }
      ]
  },
  ...
}
```

If verification or validation is unsuccessful, requirements can reappear in `currently_due`, `alternative_fields_due`, or `eventually_due` with error information. To receive notification of these requirements, set a [Connect webhook](https://docs.stripe.com/connect/webhooks.md) to listen to the `account.updated` event.

## Business information

Stripe verifies all information submitted about a business. For example, we might verify that the business URL is valid, is reachable, and includes information about the business. To check the verification status, you can retrieve the `requirements` hash on the `Account` object.

The following errors relate to business information verification:

| Error                                      | Resolution                                                                                     |
| ------------------------------------------ | ---------------------------------------------------------------------------------------------- |
| `invalid_business_profile_name`            | Business names must be easy to understand and consist of recognizable words.                   |
| `invalid_business_profile_name_denylisted` | The business name must match the account’s business and can’t be a generic or well-known name. |
| `invalid_product_description_length`       | The product description must be at least 10 characters.                                        |
| `invalid_product_description_url_match`    | The product description must be different from the business URL.                               |

See [Handle URL verification errors](https://docs.stripe.com/connect/handling-api-verification.md#url-verification) to resolve the following URL errors:

- `invalid_url_denylisted`
- `invalid_url_format`
- `invalid_url_web_presence_detected`
- `invalid_url_website_business_information_mismatch`
- `invalid_url_website_empty`
- `invalid_url_website_inaccessible`
- `invalid_url_website_inaccessible_geoblocked`
- `invalid_url_website_inaccessible_password_protected`
- `invalid_url_website_incomplete`
- `invalid_url_website_incomplete_cancellation_policy`
- `invalid_url_website_incomplete_customer_service_details`
- `invalid_url_website_incomplete_legal_restrictions`
- `invalid_url_website_incomplete_refund_policy`
- `invalid_url_website_incomplete_return_policy`
- `invalid_url_website_incomplete_terms_and_conditions`
- `invalid_url_website_incomplete_under_construction`
- `invalid_url_website_other`

## Business representatives 

You must collect and submit information about the people associated with a connected account. The process depends on whether your connected accounts are companies, individuals, or both.

For companies, use the [Persons API](https://docs.stripe.com/api/persons.md) to add the information to a `Person` object associated with the `Account` object. To add documents to the [verification](https://docs.stripe.com/api/persons/object.md#person_object-verification) hash on the `Person` object, first use the [Files API](https://docs.stripe.com/api/files.md) to upload the document files to Stripe’s servers.

For individuals, you can either create a `Person` or add the information to the [individual](https://docs.stripe.com/api/accounts/object.md#account_object-individual) hash on the `Account` object.

If your connected accounts include both companies and individuals, create `Person` objects so you can use the same process for all of them.

To check the verification status of an `Account`, you can retrieve its [requirements](https://docs.stripe.com/api/persons/object.md#person_object-requirements) hash.

The following errors relate to person verification:

| Error                                       | Resolution                                                                                                                             |
| ------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `invalid_address_city_state_postal_code`    | Stripe couldn’t validate the combination of city, state, and postal code in the provided address.                                      |
| `invalid_address_highway_contract_box`      | The person’s address must be a valid physical address that the account conducts business from, and it can’t be a Highway Contract Box. |
| `invalid_address_private_mailbox`           | The person’s address must be a valid physical address that the account conducts business from, and it can’t be a private mailbox.      |
| `invalid_dob_age_under_minimum`             | The person must be at least 13 years old.                                                                                              |
| `invalid_dob_age_over_maximum`              | The person’s date of birth must be within the past 120 years.                                                                          |
| `invalid_phone_number`                      | Stripe couldn’t validate the phone number on the account. Make sure the formatting matches the person’s country.                       |
| `invalid_street_address`                    | Stripe couldn’t validate the street name or number in the provided address.                                                            |
| `invalid_tax_id`

  `invalid_tax_id_format` | The tax ID must be a unique set of 9 numbers without dashes or other special characters.                                               |

## Acceptable verification documents 

The types of identity documents that Stripe accepts for connected accounts vary by country and are [the same as for other Stripe accounts](https://docs.stripe.com/acceptable-verification-documents.md).

## Company information

During the verification process, you might need to collect information about the company for an account.

To check the verification status, you can retrieve the [company.verification](https://docs.stripe.com/api/accounts/object.md#account_object-company-verification) subhash on the `Account` object.

```json
{
  "id": ""{{CONNECTED_ACCOUNT_ID}}"",
  "object": "account",
  ...
  "company": {
    "verification": {
      "document": null
    },
    ...
  },
  ...
}
```

You can look up the definition for each verification attribute on the `Account` object.

## Statement descriptors

Stripe validates the [statement descriptor and statement descriptor prefix](https://docs.stripe.com/connect/statement-descriptors.md) when you set them on an `Account`. For example, we might verify that the first 22 characters, which are provided to the card networks, match the description of the business. We check whether they’re a close match of the `Account`’s `business_profile.name`, `business_profile.url`, or the name of the company or individual.

To check the statement descriptor verification status, you can retrieve the `requirements` hash on the `Account` object.

The following errors relate to statement descriptor verification:

| Error                                                                                         | Resolution                                                                                                              |
| --------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- |
| `invalid_statement_descriptor_length`                                                         | The statement descriptor must be at least 5 characters.                                                                 |
| `invalid_statement_descriptor_business_mismatch`                                              | The statement descriptor must be similar to the business name, legal entity name, or business URL.                      |
| `invalid_statement_descriptor_denylisted`

  `invalid_statement_descriptor_prefix_denylisted` | The statement descriptor can’t match a generic or well-known business name.                                             |
| `invalid_statement_descriptor_prefix_mismatch`                                                | The statement descriptor prefix must be similar to your statement descriptor, business name, legal entity name, or URL. |

## Handle document verification problems 

Refer to the following table to resolve common requirement verification errors related to uploaded document files.

If verification fails, don’t resubmit the same file. Duplicate uploads fail automatically.

| Verification type | Code                                                                                                                                                                                                                                                                                                                                                                 | Resolution                                                                                                                                                                                                                                                                                                                                                                                                       |
| ----------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Business          | `verification_failed_keyed_match`, `verification_failed_document_match`                                                                                                                                                                                                                                                                                              | We couldn’t verify the information on the account. Your account user can either upload a verification document or update their information.                                                                                                                                                                                                                                                                      |
| Business          | `verification_failed_tax_id_not_issued`, `verification_failed_tax_id_match`                                                                                                                                                                                                                                                                                          | The IRS couldn’t verify the information that your account user provided. Ask them to correct any possible errors in the company name or tax ID or upload a document that verifies them. (US only)                                                                                                                                                                                                                |
| Business          | `verification_failed_id_number_match`, `verification_failed_name_match`, `verification_failed_address_match`                                                                                                                                                                                                                                                         | The information on the document doesn’t match the information provided by the account user. Ask them to verify their information and either correct it or upload a matching document.                                                                                                                                                                                                                            |
| Business          | `verification_document_address_missing`, `verification_document_id_number_missing`, `verification_document_name_missing`                                                                                                                                                                                                                                             | The uploaded document is missing required information. Ask your account user to upload another document that contains the missing information.                                                                                                                                                                                                                                                                   |
| Business          | `verification_legal_entity_structure_mismatch`                                                                                                                                                                                                                                                                                                                       | The business type or structure seems to be incorrect. Provide the correct business type and structure for this account.                                                                                                                                                                                                                                                                                          |
| Identity          | `verification_failed_keyed_identity`                                                                                                                                                                                                                                                                                                                                 | We couldn’t verify the name on the account. Ask your account user to verify that they provided their full legal name and to also provide a government-issued photo ID matching that name.                                                                                                                                                                                                                        |
| Identity          | `verification_document_name_mismatch`, `verification_document_dob_mismatch`, `verification_document_address_mismatch`, `verification_document_id_number_mismatch`, `verification_document_photo_mismatch`                                                                                                                                                            | The information on the ID document doesn’t match the information provided by the account user. Ask them to verify and correct the provided information.                                                                                                                                                                                                                                                          |
| Identity          | `verification_document_fraudulent`, `verification_document_manipulated`                                                                                                                                                                                                                                                                                              | The document might have been altered. Contact Stripe support to learn why verification failed.                                                                                                                                                                                                                                                                                                                   |
| Relationship      | `information_missing`                                                                                                                                                                                                                                                                                                                                                | See the error message for the missing information in the document or keyed-in data. If related to holding companies with significant ownership, the error code also identifies the missing holding companies. Learn more about [beneficial ownership verification for holding companies](https://support.stripe.com/questions/beneficial-ownership-verification-for-holding-companies).                          |
| Relationship      | `verification_failed_authorizer_authority`                                                                                                                                                                                                                                                                                                                           | We couldn’t verify the authority of the provided authorizer. Change the authorizer to a person who is registered as an authorized representative. Learn more about [representative authority verification](https://support.stripe.com/questions/representative-authority-verification).                                                                                                                          |
| Relationship      | `verification_failed_representative_authority`                                                                                                                                                                                                                                                                                                                       | We couldn’t verify the authority of the account representative. Add an authorizer to the account and provide a Letter of Authorization signed by the authorizer. Learn more about [representative authority verification](https://support.stripe.com/questions/representative-authority-verification).                                                                                                           |
| Relationship      | `verification_missing_owners`                                                                                                                                                                                                                                                                                                                                        | A business owner wasn’t provided. Provide information for all business owners.                                                                                                                                                                                                                                                                                                                                   |
| Relationship      | `verification_missing_directors`                                                                                                                                                                                                                                                                                                                                     | Directors weren’t provided. Update the account and upload a registration document with the current directors.                                                                                                                                                                                                                                                                                                    |
| Relationship      | `verification_document_directors_mismatch`                                                                                                                                                                                                                                                                                                                           | The directors listed in the document are missing from the account. Update the account and upload a registration document with the current directors.                                                                                                                                                                                                                                                             |
| Relationship      | `verification_rejected_ownership_exemption_reason`                                                                                                                                                                                                                                                                                                                   | We rejected the ownership exemption reason. Choose a different exemption reason or upload a proof of ultimate beneficial ownership document.                                                                                                                                                                                                                                                                     |
| Upload            | `verification_document_corrupt`, `verification_document_copy`, `verification_document_greyscale`, `verification_document_incomplete`, `verification_document_not_readable`, `verification_document_not_uploaded`, `verification_document_not_signed`, `verification_document_missing_back`, `verification_document_missing_front`, `verification_document_too_large` | The upload failed because of a problem with the file. Ask your account user to provide a new file that meets these requirements:
  - Color image (8,000 pixels by 8,000 pixels or smaller)
  - 10 MB or less
  - Identity documents are JPG or PNG format
  - Address or legal entity documents are JPG, PNG, or PDF format
  - Legal entity documents must include all pages
  - Must not be password protected |
| Upload            | `verification_document_country_not_supported`, `verification_document_invalid`, `verification_document_type_not_supported`                                                                                                                                                                                                                                           | The provided file isn’t an [acceptable form of ID from a supported country](https://docs.stripe.com/connect/handling-api-verification.md#acceptable-verification-documents), or isn’t an expected type of legal entity document. Ask your account user to provide a new file that meets that requirement.                                                                                                        |
| Upload            | `verification_document_verification_failed_other`, `verification_document_failed_other`                                                                                                                                                                                                                                                                              | Contact Stripe support to learn why identity verification failed.                                                                                                                                                                                                                                                                                                                                                |
| Upload            | `verification_document_expired`, `verification_document_issue_or_expiry_date_missing`                                                                                                                                                                                                                                                                                | The document is missing an issue or expiry date or is expired. The expiration date on an identity document must be after the date the document was submitted. The issue date on an address document must be within the last six months.                                                                                                                                                                          |

## Handle URL verification errors  

Stripe’s terms of service require all e-commerce businesses to populate the [business_profile.url](https://docs.stripe.com/api/accounts/object.md#account_object-business_profile-url) property on their `Account` with a working URL of their business website when requesting the `card_payments` capability. A connected account is considered an e-commerce business if it promotes or sells any products or services through an online website, social media profile, or mobile application. For more information, see the [Business website for account activation FAQ](https://support.stripe.com/questions/business-website-for-account-activation-faq).

If the connected account doesn’t operate a website to promote their business, sell products, or accept payments, they’re required to provide the [business_profile.product_description](https://docs.stripe.com/api/accounts/object.md#account_object-business_profile-product_description) instead. A product description must detail the type of products being sold, as well as the manner in which the business charges its customers (for example, in-person transactions).

URLs for e-commerce businesses must conform to certain card network standards. In order to comply with these standards, Stripe conducts a number of verifications when reviewing URLs. Learn about the [best practices](https://docs.stripe.com/get-started/checklist/website.md) for URLs and common elements for e-commerce businesses.

In many cases, you can resolve URL verification errors by doing either of the following:

- [Generating a remediation link](https://docs.stripe.com/connect/dashboard/remediation-links.md) from your platform Dashboard.
- Updating the [business_profile.url](https://docs.stripe.com/api/accounts/update.md#update_account-business_profile-url) on the `Account` object.

If you resolve the error another way (for example, by using the company website to fix a problem), you must trigger re-verification by changing the URL on the `Account` object to any other value, then immediately changing it back.

You can’t use the API to resolve all URL-related issues. Certain URL verification errors require information such as how to access the connected account’s website or to attest that the account is exempt from URL requirements. These issues require you or your connected account to provide supplemental information.

If you can’t resolve the issue, direct your connected account to [contact Stripe support](https://support.stripe.com/contact).

Refer to the following table to resolve URL verification errors.

| Error                                                     | Resolution                                                                                                                                                                                                                      |
| --------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `invalid_url_denylisted`                                  | The provided URL matches a generic business website that Stripe believes is unrelated to the account. Provide a URL that’s specific to the business.                                                                            |
| `invalid_url_format`                                      | The provided URL is formatted incorrectly. Provide a URL that’s formatted correctly, such as `https://example.com`.                                                                                                             |
| `invalid_url_web_presence_detected`                       | We detected that the account uses a website, social media profile, or mobile application to sell or promote products or services, but a URL hasn’t been provided. Provide a URL.                                                |
| `invalid_url_website_business_information_mismatch`       | The information on the website at the provided URL doesn’t match the information on the Stripe account.                                                                                                                         |
| `invalid_url_website_empty`                               | We can’t verify the website at the provided URL because the website has no content.                                                                                                                                             |
| `invalid_url_website_inaccessible`                        | We can’t reach the website at the provided URL. If you block certain regions from viewing your website, temporarily remove the blocker until we can verify your website.                                                        |
| `invalid_url_website_inaccessible_geoblocked`             | We can’t verify the website at the provided URL because certain regions are blocked from accessing it. If you block certain regions from viewing your website, temporarily remove the blocker until we can verify your website. |
| `invalid_url_website_inaccessible_password_protected`     | We can’t verify the website at the provided URL because the website is password-protected.                                                                                                                                      |
| `invalid_url_website_incomplete`                          | The website at the provided URL is missing either a business name or a clear description of goods and services offered.                                                                                                         |
| `invalid_url_website_incomplete_cancellation_policy`      | The website doesn’t contain a cancellation policy.                                                                                                                                                                              |
| `invalid_url_website_incomplete_customer_service_details` | The website doesn’t contain customer service details.                                                                                                                                                                           |
| `invalid_url_website_incomplete_legal_restrictions`       | The website doesn’t contain applicable disclosures for products and services that are subject to legal or export restrictions.                                                                                                  |
| `invalid_url_website_incomplete_refund_policy`            | The website doesn’t contain a refund policy.                                                                                                                                                                                    |
| `invalid_url_website_incomplete_return_policy`            | The website doesn’t contain a return policy and process.                                                                                                                                                                        |
| `invalid_url_website_incomplete_terms_and_conditions`     | The website doesn’t contain terms and conditions.                                                                                                                                                                               |
| `invalid_url_website_incomplete_under_construction`       | We can’t verify the website at the provided URL because the website is still under construction.                                                                                                                                |
| `invalid_url_website_other`                               | We can’t verify the account’s business using a website, social media profile, or mobile application at the provided URL.                                                                                                        |

## Handle liveness requirements 

An account can have one or more [Person](https://docs.stripe.com/api/persons.md) objects with a `proof_of_liveness` requirement. A `proof_of_liveness` requirement might require collection of an electronic ID credential, such as [MyInfo](https://www.singpass.gov.sg/main/individuals/) in Singapore, or by using Stripe Identity to collect a document or selfie. We recommend using Stripe-hosted or embedded onboarding to satisfy all variations of the `proof_of_liveness` requirement.

#### Hosted

[Stripe-hosted onboarding](https://docs.stripe.com/connect/hosted-onboarding.md) can complete all variations of `proof_of_liveness` requirements.

[Create an Account Link](https://docs.stripe.com/connect/hosted-onboarding.md#create-account-link) using the connected account ID, and send the account to the `url` returned.

```curl
curl https://api.stripe.com/v1/account_links \
  -u "<<YOUR_SECRET_KEY>>:" \
  -d "account={{CONNECTEDACCOUNT_ID}}" \
  --data-urlencode "refresh_url=https://example.com/refresh" \
  --data-urlencode "return_url=https://example.com/return" \
  -d type=account_onboarding \
  -d "collection_options[fields]=currently_due"
```

The account receives a prompt to complete the `proof_of_liveness` requirement, along with any other currently due requirements. Listen to the `account.updated` event sent to your webhook endpoint to be notified when the account completes requirements and updates their information. After the account completes the requirement, the account is redirected to the `return_url` specified.

#### Embedded

[Embedded onboarding](https://docs.stripe.com/connect/embedded-onboarding.md) can complete all forms of `proof_of_liveness` requirements.

When [creating an Account Session](https://docs.stripe.com/api/account_sessions/create.md), enable account onboarding by specifying `account_onboarding` in the `components` parameter.

If you don’t need to collect bank account information, disable `external_account_collection`. This typically applies to Connect platforms that want to use third-party external account collection providers.

```curl
curl https://api.stripe.com/v1/account_sessions \
  -u "<<YOUR_SECRET_KEY>>:" \
  -d "account={{CONNECTEDACCOUNT_ID}}" \
  -d "components[account_onboarding][enabled]=true" \
  -d "components[account_onboarding][features][external_account_collection]=false"
```

After creating the Account Session and [initializing ConnectJS](https://docs.stripe.com/connect/get-started-connect-embedded-components.md#account-sessions), you can render the Account onboarding component in the front end:

#### JavaScript

```js
// Include this element in your HTML
const accountOnboarding = stripeConnectInstance.create('account-onboarding');
accountOnboarding.setOnExit(() => {
  console.log('User exited the onboarding flow');
});
container.appendChild(accountOnboarding);

// Optional: make sure to follow our policy instructions above
// accountOnboarding.setFullTermsOfServiceUrl('{{URL}}')
// accountOnboarding.setRecipientTermsOfServiceUrl('{{URL}}')
// accountOnboarding.setPrivacyPolicyUrl('{{URL}}')
// accountOnboarding.setCollectionOptions({
//   fields: 'eventually_due',
//   futureRequirements: 'include',
//   requirements: {
//     exclude: ['business_profile.product_description']
//   }
// })
// accountOnboarding.setOnStepChange((stepChange) => {
//   console.log(`User entered: ${stepChange.step}`);
// });
```

The account receives a prompt to complete the `proof_of_liveness` requirement, along with any other currently due requirements. Listen to the `account.updated` event sent to your webhook endpoint to be notified when the account completes requirements and updates their information. After the account completes the requirements, ConnectJS calls your `onExit` JavaScript handler.

#### Identity

You can use [Stripe Identity](https://docs.stripe.com/identity.md) to fulfill a `proof_of_liveness` requirement on a `Person` object by collecting a document and selfie.

[Create a VerificationSession](https://docs.stripe.com/api/identity/verification_sessions/create.md). Specify the `related_person` parameter to associate the verification data collected with the `Person` object that requires the `proof_of_liveness`, as shown in the following example.

```curl
curl https://api.stripe.com/v1/identity/verification_sessions \
  -u "<<YOUR_SECRET_KEY>>:" \
  -d type=document \
  -d "options[document][require_matching_selfie]=true" \
  -d "related_person[account]={{CONNECTEDACCOUNT_ID}}" \
  -d "related_person[person]={{PERSON_ID}}"
```

After you create the `VerificationSession`, use the returned `client_secret` to [show the Identity modal to the user](https://docs.stripe.com/identity/verify-identity-documents.md?platform=web&type=modal#show-modal) or redirect the user to the `url`. Verification completion automatically updates the account.

We send an `account.updated` event to your webhook endpoint when the account completes the identity check and updates their information.

## Handle identity verification 

Depending on the identity information we’ve verified for an account, we might ask you to upload one or more documents. The required documents appear in the `requirements` hash on the `Account` object.

You must upload the documents that appear in `requirements.currently_due`:

- `person.verification.document`: Upload a color scan or photo of an acceptable form of ID.
- `person.verification.additional_document`: Upload a color scan or photo of a document that verifies the user’s address, such as a utility bill.
- `company.verification.document`: Upload a proof of entity document that establishes the business entity ID number, such as the company’s articles of incorporation.

If `requirements.alternatives.alternative_fields_due` contains `verification.document` requirements, you can use them as an alternative to `requirements.alternatives.original_fields_due`.

For security reasons, Stripe doesn’t accept ID documents through email. Uploading a document is a two-step process:

1. [Upload the file to Stripe](https://docs.stripe.com/connect/handling-api-verification.md#upload-a-file).
1. [Attach the file to the account](https://docs.stripe.com/connect/handling-api-verification.md#attach-a-file).

### Upload a file 

To upload a file, call the Files API to [create a File](https://docs.stripe.com/api/files/create.md).

The uploaded file must meet these requirements:

- Color image (8,000 pixels by 8,000 pixels or smaller)
- 10 MB or less
- Identity documents are JPG or PNG format
- Address or legal entity documents are JPG, PNG, or PDF format

Pass the file data in the `file` parameter and set the [purpose](https://docs.stripe.com/api/files/create.md#create_file-purpose) parameter according to the `Account` or `Person` object that will hold the document. To identify the purpose, look up the property in the API Reference.

#### curl

```bash
curl https://files.stripe.com/v1/files \
  -u <<YOUR_SECRET_KEY>>: \
  -H "Stripe-Account: {{CONNECTED_STRIPE_ACCOUNT_ID}}" \
  -F "purpose"="identity_document" \
  -F "file"="@/path/to/a/file"
```

The following request uploads the file and returns a token:

```json
{
  "id": ""{{FILE_ID}}"",
  "created": 1403047735,
  "size": 4908
}
```

Use the token’s `id` value to attach the file to a connected account for identity verification.

### Attach the file 

After you upload the file and receive a representative token, update the `Account` or `Person` object and provide the file ID in the appropriate parameter.

The following example is for a government-issued ID document:

```curl
curl https://api.stripe.com/v1/accounts/{{CONNECTEDACCOUNT_ID}}/persons/{{PERSON_ID}} \
  -u "<<YOUR_SECRET_KEY>>:" \
  -d "verification[document][front]={{FILE_ID}}"
```

The following example is for a company document:

```curl
curl https://api.stripe.com/v1/accounts/{{CONNECTEDACCOUNT_ID}} \
  -u "<<YOUR_SECRET_KEY>>:" \
  -d "company[verification][document][front]={{FILE_ID}}"
```

This update changes `verification.status` to `pending`. If an additional person needs verification, use the [Persons API](https://docs.stripe.com/api/persons.md) to update them.

### Confirm ID verification

Satisfying all identity verification requirements for a person or company triggers a `v2.core.account_person.updated` or `v2.core.account[identity].updated` webhook notification, signaling that the verification process is complete.

Stripe can take anywhere from a few minutes to a few business days to verify an image, depending on its readability.

If the verification attempt fails, the associated requirement entry contains an error with a `code` and `description` describing the cause. The `description` is a non-localized plain language message, such as “The image supplied isn’t readable,” that you can present to your account user. The `code` value is a string, such as `verification_document_not_readable`, that you can use to localize error messages for your account users.

Verification failure also triggers a `v2.core.account_person.updated` or `v2.core.account[identity].updated` webhook notification.

### Hosted document collection with Stripe Identity 

You can use [Stripe Identity](https://docs.stripe.com/identity.md) to fulfill a `person.verification.document` requirement by collecting a document and attaching it directly to the account. However, you can’t use Stripe Identity to fulfill `person.verification.additional_document` or `company.verification.document` requirements.

[Create a VerificationSession](https://docs.stripe.com/api/identity/verification_sessions/create.md). Specify the `related_person` parameter to associate the collected verification data with the `Person` object that requires the `document`, as shown in the following example:

```curl
curl https://api.stripe.com/v1/identity/verification_sessions \
  -u "<<YOUR_SECRET_KEY>>:" \
  -d type=document \
  -d "related_person[account]={{CONNECTEDACCOUNT_ID}}" \
  -d "related_person[person]={{PERSON_ID}}"
```

After you create the `VerificationSession`, use the returned `client_secret` to [show the Identity modal to the user](https://docs.stripe.com/identity/verify-identity-documents.md?platform=web&type=modal#show-modal) or redirect the user to the `url`. Verification completion automatically updates the account.

We send an `account.updated` event to your webhook endpoint when the account completes the identity check and updates their information.

## Handle form or support-based requirements  

Stripe reports risk and compliance requirements in the [requirements](https://docs.stripe.com/api/accounts/object.md#account_object-requirements) hash. These requirements have the `<id>.<requirement_description>.<resolution_path>` format.

- `id`: Uniquely identifies information that Stripe or our financial partners need. This identifier is always prefixed with `interv_` to indicate that it’s a risk verification requirement.
- `requirement_description`: Specifically describes the information needed to complete the requirement, such as `identity_verification`, `rejection_appeal`, and so on.
- `resolution_path`: Specifies how you or your connected account can provide the requested information:
  - `challenge`: The connected account must respond directly to challenge prompts, which often require sensitive information (such as a bank account) or information that only the account owner can provide (such as a selfie).
  - `form`: The connected account can complete form requests, or you can complete them on their behalf.
  - `notice`: The connected account must resolve the issue through a third party, for example, having a lien holder send a release notice to Stripe.
  - `support`: The requirement isn’t directly actionable. Contact [Stripe support](https://support.stripe.com/).
  - `underwriting_case`: Stripe has requested additional information about the connected account in the underwriting dashboard.

```json
{
  "id": ""{{CONNECTED_ACCOUNT_ID}}"",
  "object": "account",
  "requirements": {
      "current_deadline": 1234567800,
      "currently_due": [
          "{{REQUIREMENT_ID}}.restricted_or_prohibited_industry_diligence.form"
      ],
      "pending_verification": [],
      ...
  },
  ...
}
```

After satisfying a resolution path, the value of the requirement’s resolution path might change to `support` and the requirement also appears in the `pending_verification` section of the requirements hash. Stripe verifies the submitted information and either dismisses the requirement as resolved or posts a new currently due requirement.

```json
{
  "id": ""{{CONNECTED_ACCOUNT_ID}}"",
  "object": "account",
  "requirements": {
      "current_deadline": 1234567800,
      "currently_due": [],
      "pending_verification": [
        "{{REQUIREMENT_ID}}.restricted_or_prohibited_industry_diligence.support"
      ],
      ...
  },
  ...
}
```

You can remediate risk and compliance requirements in any of the following ways, depending on the type of requirement:

- **Connect embedded components**: [Embed Connect components](https://docs.stripe.com/connect/get-started-connect-embedded-components.md) into your website, and direct your users to the [account onboarding](https://docs.stripe.com/connect/supported-embedded-components/account-onboarding.md) embedded component, where they’re prompted to complete outstanding requirements in your UI. Alternatively, use the [notification banner](https://docs.stripe.com/connect/supported-embedded-components/notification-banner.md) embedded component to prompt your users for any outstanding requirements.
- **Stripe hosted onboarding**: Generate links to direct your connected accounts to complete outstanding requirements programmatically through account links or manually in your [platform Dashboard](https://docs.stripe.com/connect/dashboard/review-actionable-accounts.md).
- **Complete on behalf of your accounts**: Use your [platform Dashboard](https://docs.stripe.com/connect/dashboard/review-actionable-accounts.md) to identify and complete form-based risk requirements from connected account details on behalf of your accounts.

The following table provides more information about risk- and compliance-related requirements.

| Value                                         | Description                                                                                                                                                                                                                                                                                                    |
| --------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `business_model_verification`                 | We require more information about the nature of the business to verify that we can support the account.                                                                                                                                                                                                        |
| `restricted_or_prohibited_industry_diligence` | The business might operate in a [restricted category](https://stripe.com/legal/restricted-businesses) (for example, selling alcohol, insurance, or financial products). We might require more information about the nature of the business or licensing information to verify that we can support the account. |
| `intellectual_property_usage`                 | The business might be selling products or services that are protected by copyright. We require more information to verify that the account is authorized to sell those products.                                                                                                                               |
| `supportability_rejection_appeal`             | The Stripe terms of service prohibit supporting the business. The account can appeal this determination.                                                                                                                                                                                                       |
| `other_supportability_inquiry`                | We require more information to verify that we can support the account.                                                                                                                                                                                                                                         |
| `credit_review`                               | We require more information about the nature of the business to verify that we can support the account.                                                                                                                                                                                                        |
| `reserve_appeal`                              | We applied a reserve to the account, which doesn’t impact the account’s ability to accept payments with Stripe. The account can appeal this determination.                                                                                                                                                     |
| `identity_verification`                       | The person responsible for the account must verify their identity by uploading a government-issued ID document and a selfie.                                                                                                                                                                                   |
| `url_inquiry`                                 | The business URL must reflect the products and services that it provides. We might require a change to the URL before we can support the account.                                                                                                                                                              |
| `address_verification`                        | We must verify the address of the business through document upload.                                                                                                                                                                                                                                            |
| `bank_account_verification`                   | We must verify bank account details associated with the business.                                                                                                                                                                                                                                              |
| `customer_service_contact`                    | We must verify customer service contact information associated with the business.                                                                                                                                                                                                                              |
| `domain_verification`                         | We must verify that the account owner controls the URL or domain that they provided.                                                                                                                                                                                                                           |
| `fulfillment_policy`                          | We must verify the business’s fulfillment policy.                                                                                                                                                                                                                                                              |
| `other_compliance_inquiry`                    | We require more compliance information that doesn’t fit any of the other descriptions.                                                                                                                                                                                                                         |
| `other_business_inquiry`                      | We require more business information that doesn’t fit any of the other descriptions.                                                                                                                                                                                                                           |
| `platform_concern`                            | The platform initiated an intervention (real or an API integration test) on its own connected account.                                                                                                                                                                                                         |
| `product_description`                         | The business’s Stripe account must include an accurate product description.                                                                                                                                                                                                                                    |
| `rejection_appeal`                            | The Stripe terms of service prohibit supporting the business because of the level of risk it presents. The account can appeal this determination.                                                                                                                                                              |
| `statement_descriptor`                        | We need a statement descriptor that accurately reflects the business.                                                                                                                                                                                                                                          |
| `sanctions_review`                            | We must verify that the business isn’t involved with a sanctioned person or jurisdiction.                                                                                                                                                                                                                      |
| `pep_review`                                  | We must verify that the business isn’t involved with a person of interest or politically exposed person.                                                                                                                                                                                                       |
| `legal_hold`                                  | Stripe is required to hold funds for a legal reason. Fulfilling the requirement can involve remitting funds to a third party.                                                                                                                                                                                  |

### Retrieve requirements by capability

You can retrieve risk and compliance requirements specific to each capability by using the [Capabilities API](https://docs.stripe.com/api/capabilities.md). Each capability has a `requirements` hash to indicate which specific requirements are affecting that capability. This can help you understand the status of any given capability.

## See also

- [Identity verification for connected accounts](https://docs.stripe.com/connect/identity-verification.md)
- [Account tokens](https://docs.stripe.com/connect/account-tokens.md)
- [Testing Connect](https://docs.stripe.com/connect/testing.md)
- [Testing account identity verification](https://docs.stripe.com/connect/testing-verification.md)
- [Required verification information](https://docs.stripe.com/connect/required-verification-information.md)
