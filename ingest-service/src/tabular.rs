//! Tabular validation — port of `app/ingest.py` (CSV + JSONL).
//!
//! Parity contract with Python:
//!   * conformance: required columns present + type-parseable; extra cols allowed.
//!   * within-submission dedup on the NORMALIZED key (see keys.rs).
//!   * keys hash the *parsed* value's Python `str()` form — so a `float` column
//!     "5" keys as "5.0", a `boolean` "yes" keys as "true". `py_str_of_parsed`
//!     reproduces that. (Residual float-repr edge cases for float-typed keys are
//!     the one thing P1 shadow-mode is meant to catch — keys are normally
//!     string/integer identifiers.)

use std::collections::HashSet;

use serde_json::{json, Map, Value};

use crate::contract::{IngestReport, IngestStatus, Spec};
use crate::keys::{dataset_hash, key_hash, normalize_value};

const SAMPLE_ROWS: usize = 5;
const FORMULA_TRIGGERS: [char; 6] = ['=', '+', '-', '@', '\t', '\r'];

/// Parsed cell: the typed JSON value (for the sample) + its Python-`str` form
/// (for key normalization).
struct Parsed {
    json: Value,
    py_str: String,
}

fn parse_cell(raw: &str, col_type: &str) -> Option<Parsed> {
    match col_type {
        "integer" => raw.trim().parse::<i64>().ok().map(|n| Parsed {
            json: json!(n),
            py_str: n.to_string(),
        }),
        "float" => raw.trim().parse::<f64>().ok().map(|f| Parsed {
            json: json!(f),
            py_str: py_float_str(f),
        }),
        "boolean" => {
            // Python's parser never raises — always conforms.
            let b = matches!(raw.trim().to_lowercase().as_str(), "true" | "1" | "yes");
            Some(Parsed {
                json: json!(b),
                py_str: if b { "True" } else { "False" }.to_string(),
            })
        }
        // string / date / datetime → validated as a non-empty string.
        _ => Some(Parsed {
            json: json!(raw),
            py_str: raw.to_string(),
        }),
    }
}

/// Python `str(float)`: integral floats render with a trailing ".0"; other
/// finite values use Rust's shortest round-trip (agrees with CPython for the
/// common decimal range). Big/scientific magnitudes are a documented edge.
fn py_float_str(f: f64) -> String {
    if f.is_finite() && f == f.trunc() && f.abs() < 1e16 {
        format!("{:.1}", f)
    } else {
        f.to_string()
    }
}

fn neutralize(v: &Value) -> Value {
    if let Value::String(s) = v {
        if let Some(first) = s.chars().next() {
            if FORMULA_TRIGGERS.contains(&first) {
                return Value::String(format!("'{s}"));
            }
        }
    }
    v.clone()
}

/// Validate one row against the spec.
/// Returns (conforms, parsed_json_row, key_strs, errors).
fn validate_row(
    row: &Map<String, Value>,
    spec: &Spec,
) -> (bool, Map<String, Value>, std::collections::HashMap<String, String>, Vec<String>) {
    let mut parsed = Map::new();
    let mut key_strs = std::collections::HashMap::new();
    let mut errors = Vec::new();

    for col in &spec.columns {
        let raw = match row.get(&col.name) {
            Some(Value::String(s)) => s.clone(),
            Some(Value::Null) | None => String::new(),
            Some(other) => other.to_string(),
        };

        if raw.is_empty() {
            if col.required {
                errors.push(format!("missing required column '{}'", col.name));
            }
            continue;
        }

        match parse_cell(&raw, &col.col_type) {
            Some(p) => {
                key_strs.insert(col.name.clone(), p.py_str);
                parsed.insert(col.name.clone(), p.json);
            }
            None => {
                if col.required {
                    errors.push(format!(
                        "column '{}' cannot be parsed as {}: {:?}",
                        col.name, col.col_type, raw
                    ));
                }
            }
        }
    }

    let conforms = errors.is_empty();
    (conforms, parsed, key_strs, errors)
}

pub fn validate_dataset(bytes: &[u8], filename: &str, spec: &Spec) -> IngestReport {
    let ds_hash = dataset_hash(bytes);
    let ext = filename.rsplit('.').next().unwrap_or("").to_lowercase();

    let rows = match if ext == "jsonl" {
        parse_jsonl(bytes)
    } else {
        parse_csv(bytes)
    } {
        Ok(r) => r,
        Err(e) => {
            return IngestReport {
                status: IngestStatus::RejectedInvalid,
                validated_amount: 0,
                dataset_hash: ds_hash,
                quality_score: 0.0,
                sample: vec![],
                key_hashes: vec![],
                validation_report: json!({
                    "error": format!("Failed to parse file: {e}"),
                    "total_rows": 0, "conforming_rows": 0, "rejected_rows": 0,
                }),
                key_hash_ref: None,
                sample_ref: None,
                media_meta: None,
                perceptual_hashes: None,
                errors: vec![format!("Failed to parse file: {e}")],
            };
        }
    };

    let unique_key = spec.unique_key.clone().unwrap_or_default();
    let total_rows = rows.len();
    let mut conforming: Vec<Map<String, Value>> = Vec::new();
    let mut key_hashes: Vec<String> = Vec::new();
    let mut seen: HashSet<Vec<String>> = HashSet::new();
    let mut rejected = 0usize;
    let mut dupes = 0usize;
    let mut row_errors: Vec<Value> = Vec::new();

    for (i, row) in rows.iter().enumerate() {
        let (conforms, parsed, key_strs, errors) = validate_row(row, spec);
        if !conforms {
            rejected += 1;
            if row_errors.len() < 10 {
                row_errors.push(json!({"row": i + 1, "errors": errors}));
            }
            continue;
        }

        if !unique_key.is_empty() {
            let parts: Vec<String> = unique_key
                .iter()
                .map(|k| normalize_value(key_strs.get(k).map(String::as_str).unwrap_or("")))
                .collect();
            if !seen.insert(parts.clone()) {
                dupes += 1;
                continue;
            }
            key_hashes.push(key_hash(&parts));
        }
        conforming.push(parsed);
    }

    let validated_amount = conforming.len();
    let sample: Vec<Value> = conforming
        .iter()
        .take(SAMPLE_ROWS)
        .map(|r| {
            let mut m = Map::new();
            for (k, v) in r {
                m.insert(k.clone(), neutralize(v));
            }
            Value::Object(m)
        })
        .collect();

    // quality_score = conformance × (1 - duplicate_density) × completeness
    let conformance_rate = ratio(validated_amount, total_rows);
    let duplicate_density = ratio(dupes, total_rows);
    let optional_cols: Vec<&String> = spec
        .columns
        .iter()
        .filter(|c| !c.required)
        .map(|c| &c.name)
        .collect();
    let mut null_rate = 0.0;
    if !optional_cols.is_empty() && !conforming.is_empty() {
        let cells = optional_cols.len() * conforming.len();
        let filled: usize = conforming
            .iter()
            .map(|r| optional_cols.iter().filter(|c| r.contains_key(**c)).count())
            .sum();
        null_rate = round4(1.0 - (filled as f64 / cells as f64));
    }
    let completeness = 1.0 - null_rate;
    let quality_score = round4(
        (conformance_rate * (1.0 - duplicate_density) * completeness)
            .clamp(0.0, 1.0),
    );

    let mut report = json!({
        "total_rows": total_rows,
        "conforming_rows": validated_amount,
        "rejected_rows": rejected,
        "duplicate_rows": dupes,
        "sample_rows": sample.len(),
        "row_errors": row_errors,
        "stats": {
            "conformance_rate": round4(conformance_rate),
            "duplicate_density": round4(duplicate_density),
            "null_rate": null_rate,
            "quality_score": quality_score,
        },
    });
    if !unique_key.is_empty() {
        report["unique_key"] = json!(unique_key);
    }

    IngestReport {
        status: if validated_amount > 0 {
            IngestStatus::Validated
        } else {
            IngestStatus::RejectedInvalid
        },
        validated_amount: validated_amount as u64,
        dataset_hash: ds_hash,
        quality_score,
        sample,
        key_hashes,
        validation_report: report,
        key_hash_ref: None,
        sample_ref: None,
        media_meta: None,
        perceptual_hashes: None,
        errors: vec![],
    }
}

fn ratio(n: usize, d: usize) -> f64 {
    if d == 0 {
        0.0
    } else {
        n as f64 / d as f64
    }
}

fn round4(x: f64) -> f64 {
    (x * 10_000.0).round() / 10_000.0
}

fn parse_csv(bytes: &[u8]) -> Result<Vec<Map<String, Value>>, String> {
    // utf-8-sig: strip a leading BOM, like Python's "utf-8-sig" decode.
    let data = bytes.strip_prefix(&[0xEF, 0xBB, 0xBF]).unwrap_or(bytes);
    let mut rdr = csv::ReaderBuilder::new()
        .has_headers(true)
        .flexible(true)
        .from_reader(data);
    let headers = rdr
        .headers()
        .map_err(|e| e.to_string())?
        .iter()
        .map(String::from)
        .collect::<Vec<_>>();
    let mut out = Vec::new();
    for rec in rdr.records() {
        let rec = rec.map_err(|e| e.to_string())?;
        let mut m = Map::new();
        for (i, h) in headers.iter().enumerate() {
            m.insert(h.clone(), Value::String(rec.get(i).unwrap_or("").to_string()));
        }
        out.push(m);
    }
    Ok(out)
}

fn parse_jsonl(bytes: &[u8]) -> Result<Vec<Map<String, Value>>, String> {
    let text = String::from_utf8_lossy(bytes);
    let mut out = Vec::new();
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let obj: Value = serde_json::from_str(line).map_err(|e| e.to_string())?;
        let mut m = Map::new();
        if let Value::Object(o) = obj {
            for (k, v) in o {
                // Python stringifies every value before validating.
                let s = match v {
                    Value::String(s) => s,
                    Value::Bool(b) => if b { "True" } else { "False" }.to_string(),
                    Value::Null => "None".to_string(),
                    other => other.to_string(),
                };
                m.insert(k, Value::String(s));
            }
        }
        out.push(m);
    }
    Ok(out)
}
