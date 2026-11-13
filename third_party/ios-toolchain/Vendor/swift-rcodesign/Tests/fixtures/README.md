These are public, generated test credentials, never used for real signing.
`certificate.der` is a self-signed RSA code-signing certificate; `key-pkcs1.pem`
and `key-pkcs8.pem` encode the same matching key. `unrelated-key.pem` exercises
rejection of mismatched credentials. No test relies on trusting this certificate
or on its expiration date.

`entitlements-macho` is an arm64 Mach-O executable compiled from
`int main(void) { return 0; }` and ad-hoc signed with `{"name": "app"}` entitlements.
It contains both XML and DER slots. Tests only parse this fixture; they never
execute it, so entitlement-reading tests also run on Linux and other architectures.
