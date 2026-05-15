<!-- source: https://docs.stripe.com/connect/onboarding.md | retrieved: 2026-05-15T20:15:51Z -->

# Choose your onboarding configuration

Learn about the different options for onboarding your connected accounts.

Stripe offers several different onboarding options:

- **Stripe-hosted onboarding**: Your connected accounts go through the onboarding flow in a Stripe-hosted web form.
- **Embedded onboarding**: You embed the Account onboarding component directly in your application and your connected accounts go through the onboarding flow without leaving your application.
- **API onboarding**: You use the Stripe API to build your own customized onboarding UI.

Choose the onboarding option that best fits your business. We recommend using Stripe-hosted onboarding or Embedded onboarding. These options automatically update to handle changing requirements when they apply to a connected account.

|                                                       | [**STRIPE-HOSTED ONBOARDING**](https://docs.stripe.com/connect/hosted-onboarding.md) | [**EMBEDDED ONBOARDING**](https://docs.stripe.com/connect/embedded-onboarding.md)                                         | [**API ONBOARDING**](https://docs.stripe.com/connect/api-onboarding.md)                                    |
| ----------------------------------------------------- | ------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| **INTEGRATION EFFORT**                                | Minimal, go live quickly                                                             | More effort, go live quickly                                                                                              | Most effort, can delay going live                                                                          |
| **CUSTOMIZATION**                                     | Stripe-branded with limited platform branding                                        | [Highly themeable](https://docs.stripe.com/connect/customize-connect-embedded-components.md) with limited Stripe branding | Full control over your own UI                                                                              |
| **AUTOMATIC UPDATES FOR NEW COMPLIANCE REQUIREMENTS** | Immediate                                                                            | Immediate                                                                                                                 | Requires integration changes                                                                               |
| **SUPPORT NEW COUNTRIES WITHOUT INTEGRATION CHANGES** | ✓ Supported                                                                          | ✓ Supported                                                                                                               | ❌                                                                                                          |
| **SUPPORT LEGAL ENTITY SHARING** (Accounts v1 only)   | ✓ Supported                                                                          | ✓ Supported                                                                                                               | ❌                                                                                                          |
| **FLOW LOGIC**                                        | Limited control                                                                      | Limited control                                                                                                           | Full control                                                                                               |
| **IDEAL FOR**                                         | Platforms that want Stripe to handle onboarding                                      | Platforms that want a branded onboarding flow within their application                                                    | Platforms that require full control of the onboarding flow and have the resources to build and maintain it |

## Stripe-hosted onboarding

Stripe-hosted onboarding is a web form hosted by Stripe with your brand’s name, color, and icon, and is localized for all Stripe-supported countries. Stripe-hosted onboarding uses the Accounts API to read an account’s requirements and generate a custom guided flow. It lets the account user upload documents and applies data validation, including real-time verification when possible.

Additionally, Stripe-hosted onboarding lets existing connected accounts update their business type or previously submitted details.

Stripe-hosted onboarding supports [networked onboarding](https://docs.stripe.com/connect/networked-onboarding.md), which allows owners of multiple Stripe accounts to share certain types of business information between them. When they onboard an account, they can reuse that information from an existing account instead of resubmitting it.

Use Stripe-hosted onboarding if you want Stripe to handle onboarding and reduce the amount of effort for your platform.

See [Stripe-hosted onboarding](https://docs.stripe.com/connect/hosted-onboarding.md) to learn more.

## Embedded onboarding

Embedded onboarding is a themeable onboarding UI with limited Stripe branding, and it’s localized for all Stripe-supported countries. Your platform embeds the [Account onboarding component](https://docs.stripe.com/connect/supported-embedded-components/account-onboarding.md) in your application, and your connected accounts interact with the embedded component without leaving your application. Embedded onboarding uses the Accounts API to read an account’s requirements and generate a custom guided flow. It lets the account user upload documents and applies data validation, including real-time verification when possible.

Additionally, Embedded onboarding lets existing connected accounts update their business type or previously submitted details.

Embedded onboarding supports [networked onboarding](https://docs.stripe.com/connect/networked-onboarding.md), which allows owners of multiple Stripe accounts to share certain types of business information between them. When they onboard an account, they can reuse that information from an existing account instead of resubmitting it.

With embedded onboarding, you get a customized onboarding flow and don’t need to update your onboarding integration as compliance requirements change.

See [Embedded onboarding](https://docs.stripe.com/connect/embedded-onboarding.md) to learn more.

## API onboarding

You use the Accounts API to build an onboarding flow and handle identity verification, localization, and error handling for each country your connected accounts onboard in. Your platform is responsible for all interactions with your connected accounts and for collecting all the information needed to verify each account. You must plan on reviewing and updating onboarding requirements at least every 6 months.

We don’t recommend this option unless you’re committed to the operational complexity required to build and maintain an API onboarding flow. For a customized onboarding flow, use embedded onboarding.

See [API onboarding](https://docs.stripe.com/connect/api-onboarding.md) to learn more.


---

<!-- source: https://docs.stripe.com/connect/hosted-onboarding.md | retrieved: 2026-05-15T20:15:51Z -->

# Stripe-hosted onboarding

Onboard connected accounts by redirecting them to a Stripe-hosted onboarding flow.

Stripe-hosted onboarding handles the collection of business and identity verification information from connected accounts, requiring minimal effort by the platform. It’s a web form hosted by Stripe that renders dynamically based on the capabilities, country, and business type of each connected account.
![](https://b.stripecdn.com/docs-statics-srv/assets/hosted_onboarding_form.e59ba8300f563e43489953f06127f52c.png)

The hosted onboarding form in the Stripe sample integration, [Furever](https://furever.dev/).

Stripe-hosted onboarding supports [networked onboarding](https://docs.stripe.com/connect/networked-onboarding.md), which allows owners of multiple Stripe accounts to share business information between them. When they onboard an account, they can reuse that information from an existing account instead of resubmitting it.

## Customize the onboarding form [Dashboard]

Go to the [Connect settings page](https://dashboard.stripe.com/account/applications/settings) in the Dashboard to customize the visual appearance of the form with your brand’s name, color, and icon. Stripe-hosted onboarding requires this information. Stripe also recommends [collecting bank account information](https://dashboard.stripe.com/settings/connect/payouts/external_accounts) from your connected accounts as they’re onboarding.

## Create an account and prefill information [Server-side]

Create a [connected account](https://docs.stripe.com/api/accounts.md) with the default [controller](https://docs.stripe.com/api/accounts/create.md#create_account-controller) properties. See [design an integration](https://docs.stripe.com/connect/interactive-platform-guide.md) to learn more about controller properties. Alternatively, you can create a connected account by specifying an account [type](https://docs.stripe.com/api/accounts/create.md#create_account-type).

If you specify the account’s country or request any capabilities for it, then the account owner can’t change its country. Otherwise, it depends on the account’s Dashboard access:

- **Full Stripe Dashboard:** During onboarding, the account owner can select any acquiring country, the same as when signing up for a normal Stripe account. Stripe automatically requests a set of capabilities for the account based on the selected country.
- **Express Dashboard:** During onboarding, the account owner can select from a list of countries that you configure in your platform Dashboard [Onboarding options](https://dashboard.stripe.com/settings/connect/onboarding-options/countries). You can also configure those options to specify the default capabilities to request for accounts in each country.
- **No Stripe Dashboard**: If Stripe is responsible for collecting requirements, then the onboarding flow lets the account owner select any acquiring country. Otherwise, your custom onboarding flow must set the country and request capabilities.

#### With controller properties

```curl
curl https://api.stripe.com/v1/accounts \
  -u "<<YOUR_SECRET_KEY>>:" \
  -d "controller[fees][payer]=application" \
  -d "controller[losses][payments]=application" \
  -d "controller[stripe_dashboard][type]=express"
```

#### With account type

```curl
curl https://api.stripe.com/v1/accounts \
  -u "<<YOUR_SECRET_KEY>>:" \
  -d type=standard
```

The response includes the ID, which you use to reference the `Account` throughout your integration.

### Request capabilities

You can request [capabilities](https://docs.stripe.com/connect/account-capabilities.md#creating) when creating an account by setting the desired capabilities’ `requested` property to true. For accounts with access to the Express Dashboard, you can also configure your [Onboarding options](https://dashboard.stripe.com/settings/connect/onboarding-options/countries) to automatically request certain capabilities when creating an account.

Stripe’s onboarding UIs automatically collect the requirements for requested capabilities. To reduce onboarding effort, request only the capabilities you need.

### Prefill information

If you have information about the account holder (like their name, address, or other details), you can simplify onboarding by providing it when you create or update the account. The onboarding interface asks the account holder to confirm the pre-filled information before accepting the [Connect service agreement](https://docs.stripe.com/connect/service-agreement-types.md). The account holder can edit any pre-filled information before they accept the service agreement, even if you provided the information using the Accounts API.

If you onboard an account and your platform provides it with a URL, prefill the account’s [business_profile.url](https://docs.stripe.com/api/accounts/create.md#create_account-business_profile-url). If the business doesn’t have a URL, you can prefill its [business_profile.product_description](https://docs.stripe.com/api/accounts/create.md#create_account-business_profile-product_description) instead.

When testing your integration, use [test data](https://docs.stripe.com/connect/testing.md) to simulate different outcomes including identity verification, business information verification, payout failures, and more.

## Determine the information to collect

As the platform, you must decide if you want to collect the required information from your connected accounts *up front* (Upfront onboarding is a type of onboarding where you collect all required verification information from your users at sign-up) or *incrementally* (Incremental onboarding is a type of onboarding where you gradually collect required verification information from your users. You collect a minimum amount of information at sign-up, and you collect more information as the connected account earns more revenue). Up-front onboarding collects the `eventually_due` requirements for the account, while incremental onboarding only collects the `currently_due` requirements.

| Onboarding type | Advantages                                                                                                                                                                                                               |
| --------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Up-front**    | - Normally requires only one request for all information
  - Avoids the possibility of payout and processing issues due to missed deadlines
  - Exposes potential risk early when accounts refuse to provide information |
| **Incremental** | - Accounts can onboard quickly because they don’t have to provide as much information                                                                                                                                    |

To determine whether to use up-front or incremental onboarding, review the [requirements](https://docs.stripe.com/connect/required-verification-information.md) for your connected accounts’ locations and capabilities. While Stripe tries to minimize any impact to connected accounts, requirements might change over time.

For connected accounts where you’re responsible for requirement collection, you can customize the behavior of [future requirements](https://docs.stripe.com/connect/handle-verification-updates.md) using the `collection_options` parameter. To collect the account’s future requirements, set [`collection_options.future_requirements`](https://docs.stripe.com/api/account_links/create.md#create_account_link-collection_options-future_requirements) to `include`.

### Collect additional public details

Stripe collects the required public details for each connected account. You can choose additional fields to collect during onboarding according to your business needs. Any fields you choose that Stripe doesn’t require appear as optional, and connected accounts can choose whether to provide them.

1. In the [Public details](https://dashboard.stripe.com/settings/connect/onboarding-options/public-details) settings in the Dashboard, enable the **Collect public details** toggle.
1. Select the fields to show to connected accounts during onboarding.
1. Click **Save**.

#### Available fields

You can collect the following public details:

| Field                                                                            | Description                                                                                                     |
| -------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| [Statement descriptor](https://docs.stripe.com/connect/statement-descriptors.md) | The text that appears on a customer’s credit card or bank statement for payments made to the connected account. |
| Customer support phone number                                                    | A phone number customers can call for support related to the connected account.                                 |
| Customer support address                                                         | A mailing address customers can use to contact the connected account.                                           |
| Customer support email                                                           | An email address customers can use to contact the connected account.                                            |

> #### Requirements vary
> 
> Stripe’s requirements vary by connected account based on their business type, country, and requested capabilities. Enable fields to make sure they always appear during onboarding, whether or not they’re required.

## Create an Account Link [Server-side]

Create an [Account Link](https://docs.stripe.com/api/account_links/create.md) using the connected account ID and include a [refresh URL](https://docs.stripe.com/connect/hosted-onboarding.md#refresh-url) and a [return URL](https://docs.stripe.com/connect/hosted-onboarding.md#return-url). Stripe redirects the connected account to the refresh URL if the Account Link URL has already been visited, has expired, or is otherwise invalid. Stripe redirects connected accounts to the return URL when they have completed or left the onboarding flow. Additionally, based on the information you need to collect, pass either `currently_due` or `eventually_due` for `collection_options.fields`. This example passes `eventually_due` to use up-front onboarding. For incremental onboarding, set it to `currently_due`.

```curl
curl https://api.stripe.com/v1/account_links \
  -u "<<YOUR_SECRET_KEY>>:" \
  -d "account={{CONNECTEDACCOUNT_ID}}" \
  --data-urlencode "refresh_url=https://example.com/refresh" \
  --data-urlencode "return_url=https://example.com/return" \
  -d type=account_onboarding \
  -d "collection_options[fields]=eventually_due"
```

### Redirect your connected account to the Account Link URL 

Redirect the connected account to the Account Link URL to send them to the onboarding flow. You can only use each temporary Account Link URL once, because it grants access to the account holder’s personal information. Authenticate the account in your application before redirecting them to this URL. [Prefill](https://docs.stripe.com/connect/hosted-onboarding.md#prefill-information) any account information before generating the Account Link because you can’t read or write information for the connected account afterward.

> Don’t email, text, or otherwise send account link URLs outside of your platform application. Instead, provide them to the authenticated account holder within your application.

#### iOS

#### Swift

```swift
import UIKit
import SafariServices

let BackendAPIBaseURL: String = "" // Set to the URL of your backend server

class ConnectOnboardViewController: UIViewController {

    // ...

    override func viewDidLoad() {
        super.viewDidLoad()

        let connectWithStripeButton = UIButton(type: .system)
        connectWithStripeButton.setTitle("Connect with Stripe", for: .normal)
        connectWithStripeButton.addTarget(self, action: #selector(didSelectConnectWithStripe), for: .touchUpInside)
        view.addSubview(connectWithStripeButton)

        // ...
    }

    @objc
    func didSelectConnectWithStripe() {
        if let url = URL(string: BackendAPIBaseURL)?.appendingPathComponent("onboard-user") {
          var request = URLRequest(url: url)
          request.httpMethod = "POST"
          let task = URLSession.shared.dataTask(with: request) { (data, response, error) in
              guard let data = data,
                  let json = try? JSONSerialization.jsonObject(with: data, options: []) as? [String : Any],
                  let accountURLString = json["url"] as? String,
                  let accountURL = URL(string: accountURLString) else {
                      // handle error
              }

              let safariViewController = SFSafariViewController(url: accountURL)
              safariViewController.delegate = self

              DispatchQueue.main.async {
                  self.present(safariViewController, animated: true, completion: nil)
              }
          }
        }
    }

    // ...
}

extension ConnectOnboardViewController: SFSafariViewControllerDelegate {
    func safariViewControllerDidFinish(_ controller: SFSafariViewController) {
        // the user may have closed the SFSafariViewController instance before a redirect
        // occurred. Sync with your backend to confirm the correct state
    }
}

```

#### Android

```xml
<?xml version="1.0" encoding="utf-8"?>
<androidx.constraintlayout.widget.ConstraintLayout
    xmlns:android="http://schemas.android.com/apk/res/android"
    xmlns:app="http://schemas.android.com/apk/res-auto"
    xmlns:tools="http://schemas.android.com/tools"
    android:layout_width="match_parent"
    android:layout_height="match_parent"
    tools:context=".activity.ConnectWithStripeActivity">

    <Button
        android:id="@+id/connect_with_stripe"
        android:text="Connect with Stripe"
        android:layout_height="wrap_content"
        android:layout_width="wrap_content"
        app:layout_constraintBottom_toBottomOf="parent"
        app:layout_constraintEnd_toEndOf="parent"
        app:layout_constraintStart_toStartOf="parent"
        app:layout_constraintTop_toTopOf="parent"
        style="?attr/materialButtonOutlinedStyle"
        />

</androidx.constraintlayout.widget.ConstraintLayout>
```

#### Kotlin

```kotlin
class ConnectWithStripeActivity : AppCompatActivity() {

    private val viewBinding: ActivityConnectWithStripeViewBinding by lazy {
        ActivityConnectWithStripeViewBinding.inflate(layoutInflater)
    }
    private val httpClient = OkHttpClient()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(viewBinding.root)

        viewBinding.connectWithStripe.setOnClickListener {
            val weakActivity = WeakReference<Activity>(this)
            val request = Request.Builder()
                .url(BACKEND_URL + "onboard-user")
                .post("".toRequestBody())
                .build()
            httpClient.newCall(request)
                .enqueue(object: Callback {
                    override fun onFailure(call: Call, e: IOException) {
                        // Request failed
                    }
                    override fun onResponse(call: Call, response: Response) {
                        if (!response.isSuccessful) {
                            // Request failed
                        } else {
                            val responseData = response.body?.string()
                            val responseJson =
                                responseData?.let { JSONObject(it) } ?: JSONObject()
                            val url = responseJson.getString("url")

                            weakActivity.get()?.let {
                                val builder: CustomTabsIntent.Builder = CustomTabsIntent.Builder()
                                val customTabsIntent = builder.build()
                                customTabsIntent.launchUrl(it, Uri.parse(url))
                            }
                        }
                    }
                })
        }
    }

    internal companion object {
        internal const val BACKEND_URL = "https://example-backend-url.com/"
    }
}
```

## Identify and address requirement updates [Server-side]

Set up your integration to [listen for changes](https://docs.stripe.com/connect/handling-api-verification.md#verification-process) to account requirements. You can test handling new requirements (and how they might disable charges and payouts) with the [test trigger cards](https://docs.stripe.com/connect/testing.md#trigger-cards).

Send a connected account back through onboarding when it has any `currently_due` or `eventually_due` requirements. You don’t need to identify the specific requirements, because the onboarding interface knows what information it needs to collect. For example, if a typo is preventing verification of the account owner’s identity, onboarding prompts them to upload an identity document.

Stripe notifies you about any [upcoming requirements updates](https://support.stripe.com/user/questions/onboarding-requirements-updates) that affect your connected accounts. You can proactively collect this information by reviewing the [future requirements](https://docs.stripe.com/api/accounts/object.md#account_object-future_requirements) for your accounts.

For connected accounts where [controller.requirement_collection](https://docs.stripe.com/api/accounts/object.md#account_object-controller-requirement_collection) is `stripe`, stop receiving updates for identity information after creating an [Account Link](https://docs.stripe.com/api/account_links.md) or [Account Session](https://docs.stripe.com/api/account_sessions.md).

Accounts store identity information in the `company` and `individual` hashes.

### Handle verification errors 

Listen to the [account.updated](https://docs.stripe.com/api/events/types.md#event_types-account.updated) event. If the account contains any `currently_due` fields when the `current_deadline` arrives, the corresponding functionality is disabled and those fields are added to `past_due`.

Let your accounts remediate their verification requirements by directing them to the Stripe-hosted onboarding form.
 (See full diagram at https://docs.stripe.com/connect/hosted-onboarding)
## Handle the connected account returning to your platform [Server-side]

The Account Link requires a `refresh_url` and `return_url` to handle all cases in which the connected account is redirected back to your platform. It’s important to implement these correctly to provide the best onboarding flow for your connected accounts.

> You can use HTTP for your `refresh_url` and `return_url` while you’re in a testing environment (for example, to test locally), but live mode only accepts HTTPS. You must update any testing URLs to HTTPS URLs before you go live.

### Refresh URL 

Your connected account is redirected to the `refresh_url` when:

- The link is expired (a few minutes went by since the link was created).
- The link was already visited (the connected account refreshed the page or clicked the **back** or **forward** button).
- The link was shared in a third-party application such as a messaging client that attempts to access the URL to preview it. Many clients automatically visit links, which causes an Account Link to expire.

The `refresh_url` should call a method on your server to create a new Account Link with the same parameters and redirect the connected account to the new Account Link URL.

### Return URL 

Stripe redirects the connected account back to this URL when they complete the onboarding flow or click **Save for later** at any point in the flow. It doesn’t mean that all information has been collected, or that there are no outstanding requirements on the account. It only means the flow was entered and exited properly.

No state is passed with this URL. After a connected account is redirected to the `return_url`, determine if the account has completed onboarding. [Retrieve the account](https://docs.stripe.com/api/accounts/retrieve.md) and check the [requirements](https://docs.stripe.com/api/accounts/object.md#account_object-requirements) hash for outstanding requirements. Alternatively, listen to the `account.updated` event sent to your webhook endpoint and cache the state of the account in your application. If the account hasn’t completed onboarding, provide prompts in your application to allow them to continue onboarding later.

## Handle connected account-initiated updates [Server-side]

Stripe-hosted onboarding also supports connected account-initiated updates to the information they’ve already provided. Listen to the `account.updated` event sent to your webhook endpoint to be notified when the account completes requirements and updates their information.

When you create an Account Link, you can set the `type` to either `account_onboarding` or `account_update`.

> #### Account Link type restriction
> 
> You can create Account Links of type `account_update` only for connected accounts where your platform is responsible for collecting requirements, including Custom accounts. You can’t create them for accounts that have access to a Stripe-hosted Dashboard. If you use [Connect embedded components](https://docs.stripe.com/connect/get-started-connect-embedded-components.md), you can include components that allow your connected accounts to update their own information. For an account without Stripe-hosted Dashboard access where Stripe is liable for negative balances, you must use embedded components.

### Account Links for account_onboarding 

Account Links of this type provide a form for inputting outstanding requirements. Use it when you’re onboarding a new connected account, or when an existing user has new requirements (such as when a connected account had already provided enough information, but you requested a new capability that needs additional info). Send them to this type of Account Link to just collect the new information you need.

### Account Links for account_update 

Account Links of this type are enabled for accounts where your platform is responsible for requirement collection. `account_update` links display the attributes that are already populated on the account object and allow the connected account to edit previously provided information. Provide an option in your application (for example, “edit my profile” or “update my verification information”) for connected accounts to make updates themselves.

## Browser support

Stripe-hosted onboarding is only supported in web browsers. You can’t use it in embedded web views inside mobile or desktop applications.


---

<!-- source: https://docs.stripe.com/connect/custom-accounts.md | retrieved: 2026-05-15T20:15:51Z -->

# Using Connect with Custom connected accounts

Use Custom connected accounts with Connect to control your connected accounts' entire experience.

> #### Newer Connect integrations
> 
> The information on this page applies only to platforms that already use legacy connected account types. If you’re setting up a new Connect platform, or your integration uses the Accounts v2 API, see [Configure the behavior of connected accounts](https://docs.stripe.com/connect/accounts-v2/connected-account-configuration.md) to learn about connected account configurations. If your integration uses the Accounts v1 API, see [Account controller properties](https://docs.stripe.com/connect/migrate-to-controller-properties.md#account-controller-properties).

A *Custom* connected account is almost completely invisible to the account holder. You, the platform, are responsible for all interactions with your connected accounts and for collecting all the information needed to verify each account.

With Custom connected accounts, you can modify the connected account’s details and settings through the API, including managing their bank accounts and *payout* (A payout is the transfer of funds to an external account, usually a bank account, in the form of a deposit) schedule. Since Custom connected account holders can’t log into Stripe, it’s up to you to build the onboarding flow, connected account dashboard, reporting functionality, and communication channels.

Creating a Custom connected account involves the following steps:

1. Make sure you meet the [minimum requirements](https://docs.stripe.com/connect/custom-accounts.md#requirements).
1. Properly identify the [country](https://docs.stripe.com/connect/custom-accounts.md#country) and any related requirements.
1. [Create](https://docs.stripe.com/connect/custom-accounts.md#create) the account.
1. Complete the [identity verification](https://docs.stripe.com/connect/custom-accounts.md#identity-verification) process.

Identity verification requirements are updated as laws and regulations change globally. If you’re building your own onboarding flow to onboard accounts, you must plan on reviewing and updating onboarding requirements at least every six months. To avoid this maintenance obligation, use [Connect Onboarding for Custom Accounts](https://docs.stripe.com/connect/custom/hosted-onboarding.md).

> To comply with French PSD2 regulations, platforms in France [must use account tokens](https://stripe.com/guides/frequently-asked-questions-about-stripe-connect-and-psd2#regulatory-status-of-connect). An additional benefit of tokens is that the platform doesn’t have to store PII data, which is transferred from the connected account directly to Stripe. For platforms in other countries, we recommend using account tokens, but they aren’t required.

## Requirements for creating Custom connected accounts 

To use Custom connected accounts, you must meet all of these requirements:

- **Minimum API version**: You must be using an API version at least as recent as 2014-12-17. You can [view and upgrade](https://dashboard.stripe.com/workbench) your API version in the Dashboard if needed.
- **Terms of Service update**: Creating Custom connected accounts requires an [update to your terms of service](https://docs.stripe.com/connect/updating-service-agreements.md#tos-acceptance), as it must include a reference to Stripe’s services agreement. Stripe recommends that you consult with your attorneys on whether you should update your terms acceptance language to include reference to Stripe’s terms.
- **Handling information requests**: Instead of requesting information—such as a Social Security Number or passport scan—directly from your connected account user, Stripe requests the information it needs from you. You must collect that information from your connected account and provide it to Stripe. Otherwise, Stripe might disable payouts to the connected account.
- **Platform in a supported country**: Platforms in Australia, Austria, Belgium, Brazil, Bulgaria, Canada, Cyprus, the Czech Republic, Denmark, Estonia, Finland, France, Germany, Greece, Hong Kong, Hungary, India, Ireland, Italy, Japan, Latvia, Lithuania, Luxembourg, Malta, Mexico, the Netherlands, New Zealand, Norway, Poland, Portugal, Romania, Singapore, Slovakia, Slovenia, Spain, Sweden, Switzerland, Thailand, the United Kingdom, and the United States can create Custom accounts for any country [Stripe supports](https://stripe.com/global). [Contact us](connect@stripe.com) to be notified when platforms in your country can use Custom connected accounts.
- **Countries that don’t support self-serve**: Due to restrictions that apply when using Connect in the [United Arab Emirates](https://support.stripe.com/questions/connect-availability-in-the-uae), [India](https://support.stripe.com/questions/stripe-india-support-for-marketplaces), and [Thailand](https://support.stripe.com/questions/stripe-thailand-support-for-marketplace), platform users in these countries can’t self-serve Custom connected accounts. To begin onboarding for Custom connected accounts in these countries, [contact us](https://stripe.com/contact/sales).
- **Platforms in the UAE**: Platforms in the UAE can only use Custom connected accounts based in the UAE with the following charge types: [destination_charges](https://docs.stripe.com/connect/destination-charges.md) and [separate charges and transfers](https://docs.stripe.com/connect/separate-charges-and-transfers.md). Destination charges using the [on_behalf_of](https://docs.stripe.com/api/payment_intents/object.md#payment_intent_object-on_behalf_of) attribute aren’t yet supported for UAE platforms.

> Platforms outside of Mexico that want to create Custom connected accounts in Mexico and make them [settlement merchants](https://docs.stripe.com/connect/account-capabilities.md#card-payments) require further review. [Contact us](https://support.stripe.com/contact) to start the process.

- **Vetting for fraud**: Because your platform is responsible for losses incurred by Custom connected accounts, you must scrutinize all accounts that sign up through your platform for potential fraud. Refer to our [risk management best practices guide](https://docs.stripe.com/connect/risk-management/best-practices.md) for more information.

Note there’s an [additional cost](https://stripe.com/connect/pricing) for active Custom connected accounts. A Custom connected account is considered active if it has received at least one successful payout in a given month.

## Identify the country to use

The only piece of information you need to create a Custom connected account is the country where the individual or business primarily operates. You can collect everything else at a later time.

For example, if you’re in the United States and the business or individual you’re creating a connected account for is legally represented in Canada, assign `CA` as the country.

The country value also determines the [required verification information](https://docs.stripe.com/connect/required-verification-information.md) for the connected account.

## Create a Custom connected account

The basic process to create and connect a Custom connected account is to call the account creation endpoint, setting `type` to `custom` and providing a country and the [appropriate capabilities](https://docs.stripe.com/connect/account-capabilities.md#supported-capabilities).

```curl
curl https://api.stripe.com/v1/accounts \
  -u "<<YOUR_SECRET_KEY>>:" \
  -d country=US \
  -d type=custom \
  -d "capabilities[card_payments][requested]=true" \
  -d "capabilities[transfers][requested]=true"
```

Stripe supports cross-border transfers on the payments balance between the United States, Canada, United Kingdom, EEA, and Switzerland. In other scenarios, your platform and any connected account must be in the same region. Attempting to transfer funds across unsupported borders or balances returns an error. See [Cross-border payouts](https://docs.stripe.com/connect/cross-border-payouts.md) for supported funds flows between other regions.

You must only use transfers in combination with the permitted use cases for [charges](https://docs.stripe.com/connect/charges.md), [tops-ups](https://docs.stripe.com/connect/top-ups.md) and [fees](https://docs.stripe.com/connect/custom-accounts.md#collect-fees). We recommend using separate charges and transfers only when you’re responsible for negative balances of your connected accounts.

The result of a successful API call is the connected account information:

```json
{
  ...
  "id": ""{{CONNECTED_ACCOUNT_ID}}"",
  "type": "custom"
  ...
}
```

Store the `id` in your database—it’s the account ID. You’ll provide this value to [authenticate](https://docs.stripe.com/connect/authentication.md) as the connected account by passing it into requests in the `Stripe-Account` header.

> Store the received account ID. You need this information to perform requests on the connected account’s behalf.

## Start the identity verification process

An account created with only a country is fairly limited: it can only receive a small amount of funds. If you wish to enable payouts and keep the account in good standing, you need to [provide more information](https://docs.stripe.com/connect/identity-verification.md) about the account holder. The [required verification information](https://docs.stripe.com/connect/required-verification-information.md) page lists the minimum and likely identity verification requirements.

The easiest way to collect this information is to integrate [Connect Onboarding](https://docs.stripe.com/connect/custom/hosted-onboarding.md), which lets Stripe take care of the verification complexity. Otherwise, you must not only write your own API calls for initial integration, but also continue to check for changing onboarding requirements because of changing regulations around the world.

You can collect required information when you [create the account](https://docs.stripe.com/api.md#create_account) or by [updating the account](https://docs.stripe.com/api.md#update_account) later. At the very least, we recommend collecting and providing the connected account user’s name and date of birth up front. If you collect [address information](https://support.stripe.com/questions/connect-address-validation) upfront, make sure to validate the state value for US, CA, and AU connected accounts in your onboarding flow.

> For accounts with [business_type](https://docs.stripe.com/api/accounts/object.md#account_object-business_type) set to `individual`, provide at least one `individual` property (for example, `individual.first_name`) and a [Person](https://docs.stripe.com/api/persons/object.md) object is created automatically. If you don’t, or for accounts with the `business_type` set to `company`, you need to [create each Person](https://docs.stripe.com/api/persons/create.md) for the account.

## Webhooks

After an account is created, all notifications about changes to the account are sent to your [webhooks](https://docs.stripe.com/connect/webhooks.md) as `account.updated` events. Provide your *Connect* (Connect is Stripe's solution for multi-party businesses, such as marketplace or software platforms, to route payments between sellers, customers, and other recipients) *webhook* (A webhook is a real-time push notification sent to your application as a JSON payload through HTTPS requests) URL in your [account settings](https://dashboard.stripe.com/account/webhooks) and then watch for these events and respond to them as needed.

## See also

- [Onboarding custom accounts](https://docs.stripe.com/connect/custom/onboarding.md)
- [Updating service agreements](https://docs.stripe.com/connect/updating-service-agreements.md)
- [Identity verification](https://docs.stripe.com/connect/identity-verification.md)
- [Authentication](https://docs.stripe.com/connect/authentication.md)
- [Creating charges](https://docs.stripe.com/connect/charges.md)
