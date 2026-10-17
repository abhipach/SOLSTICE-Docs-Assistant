# Account Access and Password Resets

## Resetting your own password
Admins who sign in with an email and password can reset their own password. On the sign-in page select "Forgot password" and enter your work email. The reset link is valid for 60 minutes and can only be used once. New passwords must be at least 12 characters long. If the email does not arrive, check your spam folder and confirm that messages from noreply@solstice-learning.example are allowed.

## Resetting a password for another user
Admins with the User Manager role can send a reset link to a colleague or learner. Go to Users, select the person, then choose "Send password reset". Admins cannot view or set another person's password directly.

## Accounts that sign in with SSO
Password resets do not apply to users who sign in through single sign-on. Their password is managed by your identity provider, such as Okta or Microsoft Entra ID.

## Account lockout
After 5 failed sign-in attempts an account is locked for 15 minutes. An Owner can unlock the account immediately from Users, then Unlock.

## Resetting multi-factor authentication
Owners can reset multi-factor authentication (MFA) for a user from Users, then Security, then Reset MFA. The user enrolls a new device the next time they sign in.
