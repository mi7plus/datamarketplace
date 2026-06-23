//! Dedup-key normalization + hashing — a byte-exact port of Python `app/keys.py`.
//!
//! PARITY IS LOAD-BEARING. Existing `AcceptedKey` rows were hashed by the Python
//! implementation; cross-source dedup only works if Rust produces identical
//! hashes. The Python contract is:
//!
//!   normalize_value(v) = str(v).strip().lower() with internal \s+ collapsed to " "
//!   key_hash(row, uk)  = sha256( repr( tuple(normalize_value(row[k]) for k in uk) ) )
//!
//! So we must reproduce Python's `repr` of a tuple of strings exactly, including:
//!   * single-quote preference, switching to double quotes when the string
//!     contains `'` but not `"`,
//!   * the single-element trailing comma: `('x',)`,
//!   * `\\`, `\n`, `\r`, `\t` and control-char `\xNN` escaping.
//!
//! Float/!ascii edge cases are covered by the shadow-parity tests (P1); keys are
//! overwhelmingly strings/integers in practice. See README "Parity caveats".

use sha2::{Digest, Sha256};

/// Port of Python `normalize_value`: trim, lowercase, collapse internal
/// whitespace runs to a single ASCII space.
pub fn normalize_value(v: &str) -> String {
    let trimmed = v.trim();
    let lowered = trimmed.to_lowercase();
    collapse_whitespace(&lowered)
}

fn collapse_whitespace(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    let mut in_ws = false;
    for ch in s.chars() {
        if ch.is_whitespace() {
            if !in_ws {
                out.push(' ');
                in_ws = true;
            }
        } else {
            out.push(ch);
            in_ws = false;
        }
    }
    out
}

/// SHA-256 of `repr(tuple(normalized_values))`, matching Python `key_hash`.
/// `values` are already-normalized strings, in unique_key order.
pub fn key_hash(values: &[String]) -> String {
    let repr = py_repr_tuple(values);
    let mut hasher = Sha256::new();
    hasher.update(repr.as_bytes());
    hex::encode(hasher.finalize())
}

/// Reproduce Python's `repr()` of a tuple of `str`.
pub fn py_repr_tuple(values: &[String]) -> String {
    let mut out = String::from("(");
    for (i, v) in values.iter().enumerate() {
        if i > 0 {
            out.push_str(", ");
        }
        out.push_str(&py_repr_str(v));
    }
    // Single-element tuples render with a trailing comma in Python.
    if values.len() == 1 {
        out.push(',');
    }
    out.push(')');
    out
}

/// Reproduce Python's `repr()` of a single `str`.
pub fn py_repr_str(s: &str) -> String {
    let has_single = s.contains('\'');
    let has_double = s.contains('"');
    // Python prefers single quotes; uses double quotes only when the string has a
    // single quote but no double quote.
    let quote = if has_single && !has_double { '"' } else { '\'' };

    let mut out = String::with_capacity(s.len() + 2);
    out.push(quote);
    for ch in s.chars() {
        match ch {
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if c == quote => {
                out.push('\\');
                out.push(c);
            }
            c if is_py_printable(c) => out.push(c),
            c => out.push_str(&py_escape_char(c)),
        }
    }
    out.push(quote);
    out
}

/// Approximation of Python `str.isprintable()` sufficient for normalized keys:
/// printable ASCII shown literally; ASCII controls escaped; non-ASCII passed
/// through (Python shows most printable Unicode literally). Non-printable
/// Unicode in a key is rare and caught by shadow parity tests.
fn is_py_printable(c: char) -> bool {
    if (c as u32) < 0x20 || (c as u32) == 0x7f {
        return false; // ASCII control chars
    }
    true
}

fn py_escape_char(c: char) -> String {
    let cp = c as u32;
    if cp <= 0xff {
        format!("\\x{:02x}", cp)
    } else if cp <= 0xffff {
        format!("\\u{:04x}", cp)
    } else {
        format!("\\U{:08x}", cp)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalize_matches_python() {
        assert_eq!(normalize_value("  Acme   Inc "), "acme inc");
        assert_eq!(normalize_value("HELLO"), "hello");
        assert_eq!(normalize_value("5"), "5");
        assert_eq!(normalize_value(""), "");
    }

    #[test]
    fn repr_tuple_multi() {
        let v = vec!["acme inc".to_string(), "5".to_string()];
        assert_eq!(py_repr_tuple(&v), "('acme inc', '5')");
    }

    #[test]
    fn repr_tuple_single_has_trailing_comma() {
        let v = vec!["x".to_string()];
        assert_eq!(py_repr_tuple(&v), "('x',)");
    }

    #[test]
    fn repr_switches_to_double_quotes() {
        // Python: repr("it's") == "\"it's\""
        assert_eq!(py_repr_str("it's"), "\"it's\"");
    }

    #[test]
    fn repr_escapes_backslash_and_controls() {
        assert_eq!(py_repr_str("a\\b"), "'a\\\\b'");
        assert_eq!(py_repr_str("a\tb"), "'a\\tb'");
    }

    #[test]
    fn key_hash_is_stable() {
        // Same normalized tuple -> identical hash (determinism).
        let a = key_hash(&["acme inc".into(), "5".into()]);
        let b = key_hash(&["acme inc".into(), "5".into()]);
        assert_eq!(a, b);
        assert_eq!(a.len(), 64);
    }

    // GOLDEN VECTORS — generated from the real Python app/keys.py. These are the
    // parity contract: backend/tests/test_rust_parity.py asserts the SAME values.
    // If either side changes, dedup against existing AcceptedKey rows breaks.
    #[test]
    fn key_hash_matches_python_golden() {
        assert_eq!(
            key_hash(&["acme inc".into(), "5".into()]),
            "f56de70cfdee91c8f7a35c9fa6db38b1df5e4bf884112abb1e3a8a08bd51fb78"
        );
        assert_eq!(
            key_hash(&["hello".into()]),
            "4dd012f16965b64ad0d5232cfefdac8408ab5a2d782ab267f8d7bf28dc6c1f13"
        );
        assert_eq!(
            key_hash(&["it's".into()]),
            "5ec42fb4e8710713fed0a1c388c55a2be0ddd22ca0f9034f3e28e29e8a2a42d8"
        );
    }
}
