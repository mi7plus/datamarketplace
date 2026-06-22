//! Parity with Python `app/keys.py` + `app/ingest.py`.
//!
//! The `EXPECTED_*` hashes were captured from the LIVE Python code via:
//!   python -c "from app.keys import key_hash; print(key_hash(row, uk))"
//! If Python's normalization or repr changes, these will fail — which is the
//! point: the cross-source dedup anti-join depends on byte-identical hashes.

use rowbound_ingest::contract::{Column, Spec};
use rowbound_ingest::keys::{key_hash, normalize_value};
use rowbound_ingest::tabular::validate_dataset;

fn norm_parts(pairs: &[&str]) -> Vec<String> {
    pairs.iter().map(|s| normalize_value(s)).collect()
}

#[test]
fn key_hash_matches_python_ground_truth() {
    // (normalized inputs, expected hash) — captured from Python.
    let cases: &[(&[&str], &str)] = &[
        (
            &["  Alice@Example.COM ", "5"],
            "7969a2c259319ffbb33188699d4b2dfd778e1b527c5e01776083b3a92500a462",
        ),
        (
            &["Acme   Inc"],
            "bc1d0bcf94fd01dd788af74f2a48382399510d86d2fcbe2e5137d49312fed187",
        ),
        (
            &["5", "x"],
            "7a105488817e342acbd6582e4d2e885e40af000a152f9ffd3fcded895f0d4fc4",
        ),
        // Single quote in the value → Python repr switches to double quotes.
        (
            &["O'Brien"],
            "cc5d4aaf5c423bf54451222f4d84bb461811709f8d882124dc15105dd440c9ae",
        ),
        // Tab collapses to a single space under normalization.
        (
            &["a\tb"],
            "4b3d642be2afb4334e9ae34bc9d18511ecb8020add5851d6706e2453d880c307",
        ),
        // Missing key column normalizes to "".
        (
            &[""],
            "3ab190cc1597fea331cfd483f5b21b79a3d9cd059a75037922dbcaa6d01bb874",
        ),
    ];
    for (inputs, expected) in cases {
        let parts = norm_parts(inputs);
        assert_eq!(&key_hash(&parts), expected, "mismatch for {inputs:?}");
    }
}

#[test]
fn normalize_collapses_near_dupes() {
    assert_eq!(normalize_value("Acme  Inc"), normalize_value("acme inc"));
    assert_eq!(normalize_value("  X "), "x");
    assert_eq!(normalize_value("a\t b\n c"), "a b c");
}

#[test]
fn dedup_is_deterministic_and_normalized() {
    let spec = Spec {
        columns: vec![Column {
            name: "name".into(),
            col_type: "string".into(),
            required: true,
        }],
        unique_key: Some(vec!["name".into()]),
    };
    // "Acme  Inc" and "acme inc" are the same record after normalization.
    let csv = b"name\nAcme  Inc\nacme inc\nGlobex\n";
    let r = validate_dataset(csv, "data.csv", &spec);
    assert_eq!(r.validated_amount, 2); // one dupe collapsed
    assert_eq!(r.key_hashes.len(), 2);
    assert_eq!(r.validation_report["duplicate_rows"], 1);
}

#[test]
fn float_typed_key_renders_like_python_str() {
    // float column "5" → parsed 5.0 → Python str "5.0" → normalized "5.0".
    let spec = Spec {
        columns: vec![Column {
            name: "v".into(),
            col_type: "float".into(),
            required: true,
        }],
        unique_key: Some(vec!["v".into()]),
    };
    let csv = b"v\n5\n";
    let r = validate_dataset(csv, "f.csv", &spec);
    assert_eq!(r.validated_amount, 1);
    assert_eq!(r.key_hashes[0], key_hash(&["5.0".to_string()]));
}

#[test]
fn rejects_rows_missing_required_columns() {
    let spec = Spec {
        columns: vec![
            Column {
                name: "id".into(),
                col_type: "integer".into(),
                required: true,
            },
            Column {
                name: "note".into(),
                col_type: "string".into(),
                required: false,
            },
        ],
        unique_key: Some(vec!["id".into()]),
    };
    let csv = b"id,note\n1,hello\n,missing-id\nx,bad-int\n";
    let r = validate_dataset(csv, "d.csv", &spec);
    assert_eq!(r.validated_amount, 1); // only row 1 conforms
    assert_eq!(r.validation_report["rejected_rows"], 2);
}

#[test]
fn jsonl_parses_and_validates() {
    let spec = Spec {
        columns: vec![Column {
            name: "email".into(),
            col_type: "string".into(),
            required: true,
        }],
        unique_key: Some(vec!["email".into()]),
    };
    let jsonl = b"{\"email\": \"a@b.com\"}\n{\"email\": \"a@b.com\"}\n{\"email\": \"c@d.com\"}\n";
    let r = validate_dataset(jsonl, "d.jsonl", &spec);
    assert_eq!(r.validated_amount, 2);
}
