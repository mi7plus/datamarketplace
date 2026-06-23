//! Contract + determinism tests (P0/P1). Parity vs Python is asserted by the
//! Python-side shadow tests (backend/tests/test_rust_parity.py), which feed the
//! same files to both implementations.

use rowbound_ingest::contract::{IngestReport, IngestRequest, Modality, Spec, SpecColumn};
use rowbound_ingest::tabular;

fn spec(cols: &[(&str, &str, bool)], uk: &[&str]) -> Option<Spec> {
    Some(Spec {
        columns: cols
            .iter()
            .map(|(n, t, r)| SpecColumn {
                name: n.to_string(),
                col_type: t.to_string(),
                required: *r,
            })
            .collect(),
        unique_key: uk.iter().map(|s| s.to_string()).collect(),
    })
}

#[test]
fn request_roundtrips_json() {
    let json = r#"{
        "job_id": "j1",
        "submission_id": "11111111-1111-1111-1111-111111111111",
        "s3_key": "req/prov/data.csv",
        "filename": "data.csv",
        "content_hash": "abc",
        "modality": "tabular",
        "spec": {"columns": [{"name": "email", "type": "string"}], "unique_key": ["email"]}
    }"#;
    let req: IngestRequest = serde_json::from_str(json).unwrap();
    assert_eq!(req.modality, Modality::Tabular);
    assert_eq!(req.spec.unwrap().unique_key, vec!["email".to_string()]);
}

#[test]
fn deterministic_same_input_same_output() {
    let csv = b"email,n\nAlice@X.com,1\nbob@x.com,2\nALICE@x.com ,3\n";
    let s = spec(&[("email", "string", true), ("n", "integer", true)], &["email"]);
    let a = tabular::process_tabular(csv, "f.csv", &s, "j", "sub");
    let b = tabular::process_tabular(csv, "f.csv", &s, "j", "sub");
    assert_eq!(a.report.validated_amount, b.report.validated_amount);
    assert_eq!(a.key_hashes, b.key_hashes);
}

#[test]
fn normalization_collapses_near_dupes() {
    // "Alice@X.com" and "ALICE@x.com " normalize to the same key (case + trim).
    let csv = b"email\nAlice@X.com\nALICE@x.com \n";
    let s = spec(&[("email", "string", true)], &["email"]);
    let out = tabular::process_tabular(csv, "f.csv", &s, "j", "sub");
    assert_eq!(out.report.validated_amount, 1);
    assert_eq!(out.report.duplicate_rows, 1);
}

#[test]
fn report_serializes_with_expected_fields() {
    let csv = b"email\na@x.com\n";
    let s = spec(&[("email", "string", true)], &["email"]);
    let out = tabular::process_tabular(csv, "f.csv", &s, "j", "sub");
    let v = serde_json::to_value(&out.report).unwrap();
    assert!(v.get("validated_amount").is_some());
    assert!(v.get("dataset_hash").is_some());
    assert!(v.get("stats").is_some());
    let _: IngestReport = serde_json::from_value(v).unwrap();
}
