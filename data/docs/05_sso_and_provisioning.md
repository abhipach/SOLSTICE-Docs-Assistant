# Single Sign-On and Provisioning

## Supported identity providers
Single sign-on (SSO) uses SAML 2.0 and is available on the Enterprise plan. Okta, Microsoft Entra ID and Google Workspace are supported. OIDC and LDAP are not supported.

## Setting up SSO
Go to Settings, then Security, then Single sign-on. Upload your identity provider's metadata XML, map the email attribute, run the test sign-in and then enable SSO. Once enforcement is turned on, all users except Owners must sign in through SSO.

## Just-in-time provisioning
When enabled, a new user who signs in through SSO is created automatically with the Learner role.

## SCIM provisioning
SCIM user provisioning is available on Enterprise. The SCIM token expires after 12 months and must be regenerated before then to avoid sync failures.
