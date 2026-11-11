//! Small ownership-explicit C boundary around apple-codesign.
//!
//! This exposes upstream signing policy, not an emulation of Apple's codesign
//! command line. In particular, UnifiedSigner imports existing metadata and
//! shallow signing only skips nested bundles.

use apple_codesign::{
    EmbeddedSignature, MachFile, SettingsScope, SignatureReader, SigningSettings, UnifiedSigner,
    cryptography::InMemoryPrivateKey,
};
use std::{
    collections::BTreeSet,
    ffi::{CStr, CString, c_char},
    io::Cursor,
    panic::{UnwindSafe, catch_unwind},
    path::Path,
    ptr, slice,
};
use x509_certificate::{CapturedX509Certificate, InMemorySigningKeyPair, Sign};
use zeroize::Zeroizing;

type Result<T> = std::result::Result<T, String>;

#[repr(C)]
pub struct RCodesignBuffer {
    pub data: *mut u8,
    pub len: usize,
}

#[repr(C)]
pub struct RCodesignIdentity {
    pub certificate_der: *const u8,
    pub certificate_der_len: usize,
    pub private_key_pem: *const u8,
    pub private_key_pem_len: usize,
}

#[repr(C)]
pub struct RCodesignEntitlements {
    pub bundle_path: *const c_char,
    pub plist: *const u8,
    pub plist_len: usize,
}

#[repr(C)]
pub struct RCodesignSignOptions {
    pub identifier: *const c_char,
    pub entitlements: *const RCodesignEntitlements,
    pub entitlements_count: usize,
    pub shallow: u8,
}

// Keep allocation and deallocation in Rust, including error strings. Replacing
// interior NULs preserves the complete diagnostic in a valid C string.
fn error_string(message: String) -> *mut c_char {
    CString::new(message.replace('\0', "\\0"))
        .expect("interior NULs were replaced")
        .into_raw()
}

unsafe fn boundary(error: *mut *mut c_char, body: impl FnOnce() -> Result<()> + UnwindSafe) -> i32 {
    if !error.is_null() {
        unsafe { *error = ptr::null_mut() };
    }
    let result = catch_unwind(body).unwrap_or_else(|panic| {
        let message = panic
            .downcast_ref::<String>()
            .map(String::as_str)
            .or_else(|| panic.downcast_ref::<&str>().copied())
            .unwrap_or("unknown Rust panic");
        Err(format!("apple-codesign panicked: {message}"))
    });
    match result {
        Ok(()) => 0,
        Err(message) => {
            if !error.is_null() {
                unsafe { *error = error_string(message) };
            }
            1
        }
    }
}

unsafe fn buffer<'a, T>(data: *const T, len: usize) -> Result<&'a [T]> {
    if len == 0 {
        return Ok(&[]);
    }
    if data.is_null() || len > isize::MAX as usize / size_of::<T>() {
        return Err("invalid buffer".into());
    }
    Ok(unsafe { slice::from_raw_parts(data, len) })
}

unsafe fn string<'a>(value: *const c_char) -> Result<&'a str> {
    if value.is_null() {
        return Err("required string is NULL".into());
    }
    unsafe { CStr::from_ptr(value) }
        .to_str()
        .map_err(|e| format!("invalid UTF-8 string: {e}"))
}

fn entitlements(data: &[u8]) -> Result<plist::Value> {
    let value = plist::Value::from_reader(Cursor::new(data)).map_err(|e| e.to_string())?;
    if value.as_dictionary().is_none() {
        return Err("entitlements must be a plist dictionary".into());
    }
    Ok(value)
}

fn signing_identity(
    certificate: &[u8],
    private_key: &[u8],
) -> Result<(InMemorySigningKeyPair, CapturedX509Certificate)> {
    let certificate = CapturedX509Certificate::from_der(certificate)
        .map_err(|e| format!("invalid signing certificate: {e}"))?;
    let mut blocks =
        pem::parse_many(private_key).map_err(|e| format!("invalid private key PEM: {e}"))?;
    if blocks.len() != 1 {
        return Err("private key PEM must contain exactly one key".into());
    }
    let block = blocks.remove(0);
    let tag = block.tag().to_owned();
    let der = Zeroizing::new(block.into_contents());
    let key = match tag.as_str() {
        "PRIVATE KEY" => InMemoryPrivateKey::from_pkcs8_der(&*der),
        "RSA PRIVATE KEY" => InMemoryPrivateKey::from_pkcs1_der(&*der),
        _ => return Err("private key must be unencrypted PKCS#8 or PKCS#1 PEM".into()),
    }
    .map_err(|e| format!("invalid private key: {e}"))?;
    // Construct the reusable signer now, validating the private key before any
    // files are modified. Comparing both algorithm and public key prevents a
    // mismatched pair from producing a CMS signature that cannot be verified.
    let key = InMemorySigningKeyPair::try_from(key).map_err(|e| e.to_string())?;
    if key.key_algorithm() != certificate.key_algorithm()
        || key.public_key_data() != certificate.public_key_data()
    {
        return Err("private key does not match signing certificate".into());
    }
    Ok((key, certificate))
}

fn entitlement_scope(path: &str) -> Result<SettingsScope> {
    if path.is_empty() {
        return Ok(SettingsScope::Main);
    }
    if path
        .split('/')
        .any(|part| part.is_empty() || part == "." || part == "..")
    {
        return Err(format!(
            "entitlements path must be a normalized relative bundle path: {path}"
        ));
    }
    Ok(SettingsScope::Path(path.to_owned()))
}

unsafe fn configure_options(
    settings: &mut SigningSettings,
    options: &RCodesignSignOptions,
) -> Result<Vec<String>> {
    settings.set_shallow(options.shallow != 0);
    if !options.identifier.is_null() {
        settings.set_binary_identifier(SettingsScope::Main, unsafe { string(options.identifier)? });
    }
    let entries = unsafe { buffer(options.entitlements, options.entitlements_count)? };
    let mut paths = BTreeSet::new();
    for entry in entries {
        let path = unsafe { string(entry.bundle_path)? };
        let scope = entitlement_scope(path)?;
        if !paths.insert(path.to_owned()) {
            return Err(format!("duplicate entitlements path: {path}"));
        }
        if !path.is_empty() && settings.shallow() {
            return Err("nested entitlements require recursive signing".into());
        }
        let value = entitlements(unsafe { buffer(entry.plist, entry.plist_len)? })?;
        let mut xml = Vec::new();
        value.to_writer_xml(&mut xml).map_err(|e| e.to_string())?;
        settings
            .set_entitlements_xml(scope, String::from_utf8(xml).map_err(|e| e.to_string())?)
            .map_err(|e| e.to_string())?;
    }
    Ok(paths.into_iter().filter(|p| !p.is_empty()).collect())
}

/// # Safety
/// All pointers must satisfy the ownership and validity contract in rcodesign.h.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rcodesign_sign(
    input_path: *const c_char,
    output_path: *const c_char,
    identity: *const RCodesignIdentity,
    options: *const RCodesignSignOptions,
    error: *mut *mut c_char,
) -> i32 {
    unsafe {
        boundary(error, || {
            let input = string(input_path)?;
            let output = if output_path.is_null() {
                input
            } else {
                string(output_path)?
            };
            let identity = identity
                .as_ref()
                .map(|identity| {
                    signing_identity(
                        buffer(identity.certificate_der, identity.certificate_der_len)?,
                        buffer(identity.private_key_pem, identity.private_key_pem_len)?,
                    )
                })
                .transpose()?;
            // The key outlives both settings and the synchronous signing operation.
            // All state belongs to this call and is discarded if signing panics.
            let mut settings = SigningSettings::default();
            if let Some((key, certificate)) = &identity {
                settings.set_signing_key(key, certificate.clone());
                settings.chain_apple_certificates();
                settings.set_team_id_from_signing_certificate();
            }
            if let Some(options) = options.as_ref() {
                for path in configure_options(&mut settings, options)? {
                    if !Path::new(input).join(&path).is_dir() {
                        return Err(format!("entitlements bundle does not exist: {path}"));
                    }
                }
            }
            UnifiedSigner::new(settings)
                .sign_path(input, output)
                .map_err(|e| e.to_string())?;
            Ok(())
        })
    }
}

fn signature_entitlements(signature: &EmbeddedSignature<'_>) -> Result<Option<Vec<u8>>> {
    if let Some(xml) = signature.entitlements().map_err(|e| e.to_string())? {
        let bytes = xml.as_str().as_bytes();
        entitlements(bytes)?;
        // Preserve the original XML, including literal CRLF inside strings;
        // parsing and reserializing it can normalize that content.
        return Ok(Some(bytes.to_vec()));
    }
    let value = if let Some(der) = signature.entitlements_der().map_err(|e| e.to_string())? {
        der.parse_der().map_err(|e| e.to_string())?
    } else {
        return Ok(None);
    };
    if value.as_dictionary().is_none() {
        return Err("entitlements must be a plist dictionary".into());
    }
    let mut xml = Vec::new();
    value.to_writer_xml(&mut xml).map_err(|e| e.to_string())?;
    Ok(Some(xml))
}

fn read_entitlements(path: &Path) -> Result<Option<Vec<u8>>> {
    let data = match SignatureReader::from_path(path).map_err(|e| e.to_string())? {
        SignatureReader::MachO(_, data) => data,
        SignatureReader::Bundle(bundle) => {
            let name = bundle
                .main_executable()
                .map_err(|e| e.to_string())?
                .ok_or("bundle has no CFBundleExecutable")?;
            // Match apple-bundles' main-executable resolution for shallow iOS
            // bundles/frameworks and macOS bundles with Contents/MacOS layouts.
            let executable = if bundle.shallow() {
                bundle.resolve_path(name)
            } else {
                bundle.resolve_path(Path::new("MacOS").join(name))
            };
            std::fs::read(executable).map_err(|e| e.to_string())?
        }
        _ => return Err("entitlements require a Mach-O file or bundle".into()),
    };
    let file = MachFile::parse(&data).map_err(|e| e.to_string())?;
    let macho = file.nth_macho(0).map_err(|e| e.to_string())?;
    match macho.code_signature().map_err(|e| e.to_string())? {
        Some(signature) => signature_entitlements(&signature),
        None => Ok(None),
    }
}

/// # Safety
/// All pointers must satisfy the ownership and validity contract in rcodesign.h.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rcodesign_read_entitlements(
    input_path: *const c_char,
    output: *mut RCodesignBuffer,
    error: *mut *mut c_char,
) -> i32 {
    unsafe {
        boundary(error, || {
            let output = output.as_mut().ok_or("output buffer is NULL")?;
            output.data = ptr::null_mut();
            output.len = 0;
            if let Some(xml) = read_entitlements(Path::new(string(input_path)?))? {
                // A boxed slice carries exactly the length needed to reconstruct
                // its allocation in rcodesign_buffer_free, without exposing a
                // Vec's capacity or requiring the caller to use Rust's allocator.
                let xml = xml.into_boxed_slice();
                output.len = xml.len();
                output.data = Box::into_raw(xml).cast::<u8>();
            }
            Ok(())
        })
    }
}

/// # Safety
/// `buffer` must be NULL or an initialized, exclusively owned library buffer.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rcodesign_buffer_free(buffer: *mut RCodesignBuffer) {
    if let Some(buffer) = unsafe { buffer.as_mut() } {
        if !buffer.data.is_null() {
            let data = ptr::slice_from_raw_parts_mut(buffer.data, buffer.len);
            drop(unsafe { Box::from_raw(data) });
        }
        buffer.data = ptr::null_mut();
        buffer.len = 0;
    }
}

/// # Safety
/// `error` must be NULL or an unfreed error returned by this library.
#[unsafe(no_mangle)]
pub unsafe extern "C" fn rcodesign_error_free(error: *mut c_char) {
    if !error.is_null() {
        drop(unsafe { CString::from_raw(error) });
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    const CERTIFICATE: &[u8] = include_bytes!("../Tests/fixtures/certificate.der");
    const PKCS1: &[u8] = include_bytes!("../Tests/fixtures/key-pkcs1.pem");
    const PKCS8: &[u8] = include_bytes!("../Tests/fixtures/key-pkcs8.pem");

    #[test]
    fn both_rsa_pem_formats_match_the_certificate() {
        for pem in [PKCS1, PKCS8] {
            let (key, certificate) = signing_identity(CERTIFICATE, pem).unwrap();
            assert_eq!(key.public_key_data(), certificate.public_key_data());
            let mut settings = SigningSettings::default();
            settings.set_signing_key(&key, certificate);
            assert!(settings.signing_key().is_some());
            assert!(settings.time_stamp_url().is_none());
        }
    }

    #[test]
    fn rejects_mismatched_or_incomplete_identities() {
        let unrelated = include_bytes!("../Tests/fixtures/unrelated-key.pem");
        assert!(
            signing_identity(CERTIFICATE, unrelated)
                .unwrap_err()
                .contains("does not match")
        );
        assert!(signing_identity(CERTIFICATE, b"").is_err());
        assert!(signing_identity(b"", PKCS8).is_err());
        let multiple = [PKCS1, PKCS8].concat();
        assert!(
            signing_identity(CERTIFICATE, &multiple)
                .unwrap_err()
                .contains("exactly one")
        );
    }

    fn options(entries: &[RCodesignEntitlements]) -> RCodesignSignOptions {
        RCodesignSignOptions {
            identifier: ptr::null(),
            entitlements: entries.as_ptr(),
            entitlements_count: entries.len(),
            shallow: 0,
        }
    }

    #[test]
    fn entitlements_follow_their_bundle_scope() {
        let root = b"<plist><dict><key>name</key><string>app</string></dict></plist>";
        let extension = b"<plist><dict><key>name</key><string>extension</string></dict></plist>";
        let entries = [
            RCodesignEntitlements {
                bundle_path: c"".as_ptr(),
                plist: root.as_ptr(),
                plist_len: root.len(),
            },
            RCodesignEntitlements {
                bundle_path: c"PlugIns/Widget.appex".as_ptr(),
                plist: extension.as_ptr(),
                plist_len: extension.len(),
            },
        ];
        let mut settings = SigningSettings::default();
        unsafe {
            configure_options(&mut settings, &options(&entries)).unwrap();
        }
        let nested = settings.as_nested_bundle_settings("PlugIns/Widget.appex");
        let unrelated = settings.as_nested_bundle_settings("PlugIns/Other.appex");
        assert_eq!(
            settings
                .entitlements_plist(SettingsScope::Main)
                .unwrap()
                .as_dictionary()
                .unwrap()["name"]
                .as_string(),
            Some("app")
        );
        assert_eq!(
            nested
                .entitlements_plist(SettingsScope::Main)
                .unwrap()
                .as_dictionary()
                .unwrap()["name"]
                .as_string(),
            Some("extension")
        );
        assert!(unrelated.entitlements_plist(SettingsScope::Main).is_none());
    }

    #[test]
    fn invalid_scopes_cannot_silently_drop_entitlements() {
        for path in [
            "/absolute",
            "../outside",
            "PlugIns/../Widget.appex",
            "PlugIns//Widget.appex",
            "./Widget.appex",
            "Widget.appex/",
        ] {
            assert!(entitlement_scope(path).is_err(), "accepted {path}");
        }
        let xml = b"<plist><dict/></plist>";
        let entries = [RCodesignEntitlements {
            bundle_path: c"PlugIns/Widget.appex".as_ptr(),
            plist: xml.as_ptr(),
            plist_len: xml.len(),
        }];
        let mut options = options(&entries);
        options.shallow = 1;
        assert!(
            unsafe { configure_options(&mut SigningSettings::default(), &options) }
                .unwrap_err()
                .contains("recursive")
        );
        options.shallow = 0;
        options.entitlements = ptr::null();
        assert!(unsafe { configure_options(&mut SigningSettings::default(), &options) }.is_err());
    }

    #[test]
    fn reads_xml_and_der_entitlements_without_verifying_trust() {
        use apple_codesign::{
            Blob, CodeSigningMagic, CodeSigningSlot, EntitlementsBlob, EntitlementsDerBlob,
            create_superblob,
        };
        let xml = "<plist><dict><key>name</key><string>xml</string></dict></plist>";
        let der_value =
            entitlements(b"<plist><dict><key>name</key><string>der</string></dict></plist>")
                .unwrap();
        let xml_blob = (
            CodeSigningSlot::Entitlements,
            EntitlementsBlob::from_string(xml).to_blob_bytes().unwrap(),
        );
        let der_blob = (
            CodeSigningSlot::EntitlementsDer,
            EntitlementsDerBlob::from_plist(&der_value)
                .unwrap()
                .to_blob_bytes()
                .unwrap(),
        );
        for (blobs, expected) in [
            (vec![xml_blob.clone()], "xml"),
            (vec![der_blob.clone()], "der"),
            (vec![xml_blob, der_blob], "xml"),
        ] {
            let data = create_superblob(CodeSigningMagic::EmbeddedSignature, blobs.iter()).unwrap();
            let signature = EmbeddedSignature::from_bytes(&data).unwrap();
            let result = signature_entitlements(&signature).unwrap().unwrap();
            assert_eq!(
                entitlements(&result).unwrap().as_dictionary().unwrap()["name"].as_string(),
                Some(expected)
            );
        }
    }

    #[test]
    fn distinguishes_missing_empty_and_invalid_entitlements() {
        use apple_codesign::{
            Blob, CodeSigningMagic, CodeSigningSlot, EntitlementsBlob, create_superblob,
        };
        let empty = create_superblob(CodeSigningMagic::EmbeddedSignature, [].iter()).unwrap();
        assert!(
            signature_entitlements(&EmbeddedSignature::from_bytes(&empty).unwrap())
                .unwrap()
                .is_none()
        );
        for (xml, valid) in [
            ("<plist><dict/></plist>", true),
            ("not a plist", false),
            ("<plist><array/></plist>", false),
        ] {
            let blobs = [(
                CodeSigningSlot::Entitlements,
                EntitlementsBlob::from_string(xml).to_blob_bytes().unwrap(),
            )];
            let data = create_superblob(CodeSigningMagic::EmbeddedSignature, blobs.iter()).unwrap();
            let result = signature_entitlements(&EmbeddedSignature::from_bytes(&data).unwrap());
            if valid {
                assert!(
                    entitlements(&result.unwrap().unwrap())
                        .unwrap()
                        .as_dictionary()
                        .unwrap()
                        .is_empty()
                );
            } else {
                assert!(result.is_err());
            }
        }
    }

    #[test]
    fn preserves_original_xml_string_whitespace() {
        use apple_codesign::{
            Blob, CodeSigningMagic, CodeSigningSlot, EntitlementsBlob, create_superblob,
        };
        let xml = "<plist><dict><key>name</key><string>line1\r\nline2</string></dict></plist>";
        let blobs = [(
            CodeSigningSlot::Entitlements,
            EntitlementsBlob::from_string(xml).to_blob_bytes().unwrap(),
        )];
        let data = create_superblob(CodeSigningMagic::EmbeddedSignature, blobs.iter()).unwrap();
        let result = signature_entitlements(&EmbeddedSignature::from_bytes(&data).unwrap())
            .unwrap()
            .unwrap();
        assert_eq!(result, xml.as_bytes());
    }

    #[test]
    fn failed_reads_clear_output_and_return_owned_errors() {
        let mut output = RCodesignBuffer {
            data: ptr::null_mut(),
            len: 123,
        };
        let mut error = ptr::null_mut();
        unsafe {
            assert_eq!(
                rcodesign_read_entitlements(ptr::null(), &mut output, &mut error),
                1
            );
            assert!(output.data.is_null());
            assert_eq!(output.len, 0);
            assert!(!error.is_null());
            rcodesign_error_free(error);
            rcodesign_buffer_free(&mut output);
            rcodesign_buffer_free(ptr::null_mut());
        }
    }

    #[test]
    fn panics_do_not_cross_the_boundary() {
        let mut error = ptr::null_mut();
        unsafe {
            assert_eq!(boundary(&mut error, || panic!("test panic")), 1);
            assert!(
                CStr::from_ptr(error)
                    .to_str()
                    .unwrap()
                    .contains("test panic")
            );
            rcodesign_error_free(error);
        }
    }
}
