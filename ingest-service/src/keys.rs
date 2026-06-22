//! Dedup key hashing — BYTE-IDENTICAL parity with the Python `app/keys.py`.
//!
//! The cross-source dedup anti-join only works if a record hashes to the same
//! value here as it does in Python. Python computes
//! `sha256(repr(normalized_key_tuple)).hexdigest()`,
//! where the tuple is `tuple(normalize_value(row[k]) for k in unique_key)` and
//! `normalize_value` = strip + lowercase + collapse internal whitespace. The
//! tricky part is `repr` of a Python tuple-of-str: 1-tuples carry a trailing
//! comma, and Python picks the quote char (prefers `'`, switches to `"` when the
//! string contains `'` but not `"`) and escapes control chars. We reproduce that
//! exactly. See `tests/parity.rs` for hashes captured from the live Python code.

use sha2::{Digest, Sha256};

/// strip + lowercase + collapse internal whitespace (matches Python
/// `normalize_value`: `s.strip().lower()` then `re.sub(r"\s+", " ", s)`).
pub fn normalize_value(v: &str) -> String {
    // `.strip()` + collapse `\s+` == split on unicode whitespace and rejoin.
    // Lowercasing first matches Python order (lowercasing never alters whitespace).
    v.to_lowercase()
        .split_whitespace()
        .collect::<Vec<_>>()
        .join(" ")
}

/// Reproduce Python's `repr()` of a single `str`.
fn py_repr_str(s: &str) -> String {
    let has_single = s.contains('\'');
    let has_double = s.contains('"');
    // Python prefers single quotes; uses double only if the string has a single
    // quote and no double quote (so it can avoid escaping).
    let quote = if has_single && !has_double { '"' } else { '\'' };

    let mut out = String::with_capacity(s.len() + 2);
    out.push(quote);
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c == quote => {
                out.push('\\');
                out.push(quote);
            }
            // Other C0 control chars + DEL → \xNN (lowercase hex), as Python does.
            c if (c as u32) < 0x20 || (c as u32) == 0x7f => {
                out.push_str(&format!("\\x{:02x}", c as u32));
            }
            // Printable (incl. printable non-ASCII) is emitted verbatim, like py3 repr.
            c => out.push(c),
        }
    }
    out.push(quote);
    out
}

/// Reproduce Python's `repr()` of a tuple of strings (with the 1-tuple comma).
fn py_repr_tuple(parts: &[String]) -> String {
    let inner: Vec<String> = parts.iter().map(|p| py_repr_str(p)).collect();
    if inner.len() == 1 {
        format!("({},)", inner[0])
    } else {
        format!("({})", inner.join(", "))
    }
}

/// The normalized key tuple's parts for a record under the declared unique_key.
/// `get` resolves a column to its raw (pre-normalization) string; missing → "".
pub fn normalized_key<'a, F>(unique_key: &[String], get: F) -> Vec<String>
where
    F: Fn(&str) -> Option<&'a str>,
{
    unique_key
        .iter()
        .map(|k| normalize_value(get(k).unwrap_or("")))
        .collect()
}

/// Stable SHA-256 hex of a record's normalized key tuple — parity with Python.
pub fn key_hash(parts: &[String]) -> String {
    let repr = py_repr_tuple(parts);
    let mut hasher = Sha256::new();
    hasher.update(repr.as_bytes());
    hex::encode(hasher.finalize())
}

/// SHA-256 hex of raw file bytes (the `dataset_hash`).
pub fn dataset_hash(bytes: &[u8]) -> String {
    let mut hasher = Sha256::new();
    hasher.update(bytes);
    hex::encode(hasher.finalize())
}
