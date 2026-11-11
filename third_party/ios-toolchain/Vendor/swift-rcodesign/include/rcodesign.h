#ifndef SWIFT_RCODESIGN_H
#define SWIFT_RCODESIGN_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

typedef struct {
    const uint8_t *certificate_der;
    size_t certificate_der_len;
    // One unencrypted PRIVATE KEY (PKCS#8) or RSA PRIVATE KEY (PKCS#1) PEM block.
    const uint8_t *private_key_pem;
    size_t private_key_pem_len;
} rcodesign_identity;

typedef struct {
    // UTF-8 path relative to the input bundle, e.g. "PlugIns/Widget.appex".
    // Use "" for the input itself. Paths must not contain empty, . or ..
    // components, leading/trailing slashes, or duplicate another entry.
    const char *bundle_path;
    // XML or binary entitlements dictionary. An empty dictionary explicitly
    // replaces existing entitlements; omitting an entry allows upstream import.
    const uint8_t *plist;
    size_t plist_len;
} rcodesign_entitlements;

typedef struct {
    // Optional UTF-8 identifier. Upstream bundle signing derives the main
    // executable identifier from CFBundleIdentifier even when this is supplied.
    const char *identifier;
    // NULL with count zero means no explicit entitlements for any bundle.
    const rcodesign_entitlements *entitlements;
    size_t entitlements_count;
    // Nonzero skips signing nested bundles. Standalone nested Mach-O files
    // still follow apple-codesign's signing policy. Nested entitlement entries
    // require recursive signing (shallow == 0).
    uint8_t shallow;
} rcodesign_sign_options;

// Return 0 on success, 1 on failure. If error is non-NULL, each call initializes
// *error to NULL and supplies an owned UTF-8 message on failure. Release it with
// rcodesign_error_free. Output pointers must not alias any input storage.
// All input pointers are borrowed only for the duration of the call. Non-NULL
// byte pointers must be valid for their lengths; strings must be NUL-terminated.
// Calls with independent inputs may run concurrently. Do not sign overlapping
// filesystem paths concurrently. Rust unwinding panics are caught at the ABI.
//
// output_path == NULL signs in place. Otherwise it must differ from input_path
// or refer to exactly the same path. Signing is not transactional: failure can
// leave an in-place bundle partially updated. NULL options defaults to recursive
// signing without explicit identifier or entitlements.
// NULL identity selects ad-hoc signing; a supplied identity must contain both a
// certificate and matching private key. Invalid credentials never fall back to
// ad-hoc signing. Apple CA certificates and team IDs are derived automatically.
// No timestamp server is contacted, and embedded provisioning profiles are kept.
int32_t rcodesign_sign(const char *input_path, const char *output_path,
                      const rcodesign_identity *identity,
                      const rcodesign_sign_options *options, char **error);

typedef struct {
    uint8_t *data;
    size_t len;
} rcodesign_buffer;

// Read entitlements from a Mach-O file or a bundle's main executable. Universal
// binaries use the first Mach-O architecture in file order. Reads the XML slot,
// preserving its bytes, or decodes DER to XML if the XML slot is absent.
// This extracts metadata; it does not verify the signature or certificate trust.
//
// Uses the same status/error and borrowed-input conventions as rcodesign_sign.
// output is required and must not alias any input or error storage. It is reset
// to {NULL, 0} before reading, including on failure. Success with {NULL, 0} means
// the executable is unsigned or has no entitlements; an empty dictionary returns
// a nonempty plist. Invalid paths, binaries, or entitlements are errors.
// Release a non-NULL result with rcodesign_buffer_free, never the C allocator.
int32_t rcodesign_read_entitlements(const char *input_path,
                                   rcodesign_buffer *output, char **error);

// Accepts NULL or an initialized buffer returned by rcodesign_read_entitlements.
// Frees its allocation and resets it to {NULL, 0}. Do not free copies of a buffer.
void rcodesign_buffer_free(rcodesign_buffer *buffer);

// Accepts NULL. Other values must be returned by this library and freed exactly
// once. Never use the C allocator to free them.
void rcodesign_error_free(char *error);

#ifdef __cplusplus
}
#endif
#endif
