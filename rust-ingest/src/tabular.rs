//! Tabular ingest — a port of Python `app/ingest.py` (P1).
//!
//! Produces the same `validated_amount`, `dataset_hash`, sample, stats, and
//! normalized key hashes as the Python implementation, so it can run in SHADOW
//! mode and be proven at parity before cutover. PII scanning stays in Python
//! (not part of the Rust contract).

use crate::contract::{IngestReport, IngestStatus, Spec, SpecColumn, Stats};
use crate::keys::{key_hash, normalize_value};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::HashSet;

const SAMPLE_ROWS: usize = 5;
const FORMULA_TRIGGERS: [char; 6] = ['=', '+', '-', '@', '\t', '\r'];

/// A type-coerced cell value, mirroring Python's parsed types so str()-for-keys
/// and JSON-for-sample both match.
#[derive(Clone, Debug)]
enum Cell {
    Int(i64),
    Float(f64),
    Bool(bool),
    Str(String),
}

impl Cell {
    /// Equivalent of Python `str(value)` — used before key normalization.
    fn to_py_str(&self) -> String {
        match self {
            Cell::Int(n) => n.to_string(),
            // PARITY CAVEAT: Python str(float) and Rust {} can differ for some
            // values (e.g. 1e-05). Float keys are discouraged; covered by shadow.
            Cell::Float(f) => format!("{}", f),
            Cell::Bool(b) => if *b { "True" } else { "False" }.to_string(),
            Cell::Str(s) => s.clone(),
        }
    }

    /// JSON rendering for the sample preview, matching Python typed values.
    fn to_json(&self) -> Value {
        match self {
            Cell::Int(n) => json!(n),
            Cell::Float(f) => json!(f),
            Cell::Bool(b) => json!(b),
            Cell::Str(s) => json!(s),
        }
    }
}

/// Outcome of the tabular pass: the report plus the staged key hashes (which the
/// pipeline writes to the staging table / S3, not inline in the report).
pub struct TabularOutput {
    pub report: IngestReport,
    pub key_hashes: Vec<String>,
}

pub fn process_tabular(
    file_bytes: &[u8],
    filename: &str,
    spec: &Option<Spec>,
    job_id: &str,
    submission_id: &str,
) -> TabularOutput {
    let dataset_hash = sha256_hex(file_bytes);
    let ext = filename.rsplit('.').next().unwrap_or("").to_lowercase();

    let rows = if ext == "jsonl" {
        parse_jsonl(file_bytes)
    } else {
        parse_csv(file_bytes)
    };

    let rows = match rows {
        Ok(r) => r,
        Err(e) => {
            let mut report = base_report(job_id, submission_id, dataset_hash);
            report.set_status(IngestStatus::RejectedInvalid);
            report.errors.push(format!("Failed to parse file: {e}"));
            return TabularOutput { report, key_hashes: Vec::new() };
        }
    };

    let empty_spec = Spec::default();
    let spec_ref = spec.as_ref().unwrap_or(&empty_spec);
    let spec_columns = &spec_ref.columns;
    let unique_key = &spec_ref.unique_key;

    let total_rows = rows.len() as i64;
    let mut conforming: Vec<Vec<(String, Cell)>> = Vec::new();
    let mut rejected_count: i64 = 0;
    let mut dupe_count: i64 = 0;
    let mut row_errors: Vec<Value> = Vec::new();
    let mut seen_keys: HashSet<Vec<String>> = HashSet::new();
    let mut key_hashes: Vec<String> = Vec::new();

    for (i, row) in rows.iter().enumerate() {
        let (conforms, parsed, errors) = validate_row(row, spec_columns);
        if !conforms {
            rejected_count += 1;
            if row_errors.len() < 10 {
                row_errors.push(json!({ "row": i + 1, "errors": errors }));
            }
            continue;
        }

        if !unique_key.is_empty() {
            let norm = normalized_key(&parsed, unique_key);
            if seen_keys.contains(&norm) {
                dupe_count += 1;
                continue;
            }
            seen_keys.insert(norm.clone());
            key_hashes.push(key_hash(&norm));
        }

        conforming.push(parsed);
    }

    let validated_amount = conforming.len() as i64;
    let sample = build_sample(&conforming);

    // ---- stats ----
    let conformance_rate = ratio(validated_amount, total_rows);
    let duplicate_density = ratio(dupe_count, total_rows);

    let optional_cols: Vec<&str> = spec_columns
        .iter()
        .filter(|c| !c.required)
        .map(|c| c.name.as_str())
        .collect();

    let mut null_rate = 0.0;
    if !optional_cols.is_empty() && !conforming.is_empty() {
        let cells = optional_cols.len() * conforming.len();
        let filled: usize = conforming
            .iter()
            .map(|row| {
                optional_cols
                    .iter()
                    .filter(|c| row.iter().any(|(k, _)| k == *c))
                    .count()
            })
            .sum();
        null_rate = if cells > 0 {
            round4(1.0 - (filled as f64 / cells as f64))
        } else {
            0.0
        };
    }
    let completeness = 1.0 - null_rate;
    let quality_score = round4(
        (conformance_rate * (1.0 - duplicate_density) * completeness)
            .clamp(0.0, 1.0),
    );

    let mut report = base_report(job_id, submission_id, dataset_hash);
    report.set_status(if validated_amount > 0 {
        IngestStatus::Validated
    } else {
        IngestStatus::RejectedInvalid
    });
    report.validated_amount = validated_amount;
    report.total_rows = total_rows;
    report.rejected_rows = rejected_count;
    report.duplicate_rows = dupe_count;
    report.quality_score = quality_score;
    report.stats = Stats {
        conformance_rate: round4(conformance_rate),
        duplicate_density: round4(duplicate_density),
        null_rate,
        quality_score,
    };
    report.sample = sample;
    report.key_hash_count = key_hashes.len() as i64;

    TabularOutput { report, key_hashes }
}

fn base_report(job_id: &str, submission_id: &str, dataset_hash: String) -> IngestReport {
    IngestReport {
        job_id: job_id.to_string(),
        submission_id: submission_id.to_string(),
        dataset_hash,
        ..Default::default()
    }
}

/// Port of Python `_validate_row`. Returns (conforms, parsed cells, errors).
fn validate_row(
    row: &std::collections::HashMap<String, String>,
    spec_columns: &[SpecColumn],
) -> (bool, Vec<(String, Cell)>, Vec<String>) {
    let mut parsed: Vec<(String, Cell)> = Vec::new();
    let mut errors: Vec<String> = Vec::new();

    for col in spec_columns {
        let raw = row.get(&col.name).map(|s| s.as_str()).unwrap_or("");
        if raw.is_empty() {
            if col.required {
                errors.push(format!("missing required column '{}'", col.name));
            }
            continue;
        }
        match parse_value(raw, &col.col_type) {
            Some(val) => parsed.push((col.name.clone(), val)),
            None => {
                if col.required {
                    errors.push(format!(
                        "column '{}' cannot be parsed as {}: '{}'",
                        col.name, col.col_type, raw
                    ));
                }
            }
        }
    }

    (errors.is_empty(), parsed, errors)
}

/// Port of Python `TYPE_PARSERS`. None = parse failure (only matters if required).
fn parse_value(raw: &str, col_type: &str) -> Option<Cell> {
    match col_type {
        "integer" => raw.trim().parse::<i64>().ok().map(Cell::Int),
        "float" => raw.trim().parse::<f64>().ok().map(Cell::Float),
        "boolean" => {
            // Python's bool parser never fails: membership test -> True/False.
            let v = raw.trim().to_lowercase();
            Some(Cell::Bool(matches!(v.as_str(), "true" | "1" | "yes")))
        }
        // string / date / datetime -> identity string.
        _ => Some(Cell::Str(raw.to_string())),
    }
}

/// Port of Python `normalized_key`: normalized value per unique_key column, "" if absent.
fn normalized_key(parsed: &[(String, Cell)], unique_key: &[String]) -> Vec<String> {
    unique_key
        .iter()
        .map(|k| {
            parsed
                .iter()
                .find(|(name, _)| name == k)
                .map(|(_, cell)| normalize_value(&cell.to_py_str()))
                .unwrap_or_default()
        })
        .collect()
}

/// First SAMPLE_ROWS conforming rows, with leading formula triggers neutralized
/// in string cells only (preview safety; the stored dataset is untouched).
fn build_sample(conforming: &[Vec<(String, Cell)>]) -> Vec<Value> {
    conforming
        .iter()
        .take(SAMPLE_ROWS)
        .map(|row| {
            let mut obj = serde_json::Map::new();
            for (k, cell) in row {
                obj.insert(k.clone(), neutralize(cell));
            }
            Value::Object(obj)
        })
        .collect()
}

fn neutralize(cell: &Cell) -> Value {
    if let Cell::Str(s) = cell {
        if let Some(first) = s.chars().next() {
            if FORMULA_TRIGGERS.contains(&first) {
                return json!(format!("'{}", s));
            }
        }
    }
    cell.to_json()
}

// ---------------------------------------------------------------------------
// Parsers
// ---------------------------------------------------------------------------

fn parse_csv(file_bytes: &[u8]) -> Result<Vec<std::collections::HashMap<String, String>>, String> {
    // Strip a UTF-8 BOM like Python's "utf-8-sig".
    let bytes = strip_bom(file_bytes);
    let mut rdr = csv::ReaderBuilder::new()
        .has_headers(true)
        .flexible(true)
        .from_reader(bytes);

    let headers = rdr
        .headers()
        .map_err(|e| e.to_string())?
        .iter()
        .map(|h| h.to_string())
        .collect::<Vec<_>>();

    let mut out = Vec::new();
    for rec in rdr.records() {
        let rec = rec.map_err(|e| e.to_string())?;
        let mut map = std::collections::HashMap::new();
        for (i, h) in headers.iter().enumerate() {
            map.insert(h.clone(), rec.get(i).unwrap_or("").to_string());
        }
        out.push(map);
    }
    Ok(out)
}

fn parse_jsonl(file_bytes: &[u8]) -> Result<Vec<std::collections::HashMap<String, String>>, String> {
    let text = String::from_utf8_lossy(file_bytes);
    let mut out = Vec::new();
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() {
            continue;
        }
        let obj: Value = serde_json::from_str(line).map_err(|e| e.to_string())?;
        let map_obj = obj.as_object().ok_or("JSONL line is not an object")?;
        let mut map = std::collections::HashMap::new();
        for (k, v) in map_obj {
            // Normalise to strings so validate_row parses them, like Python str(v).
            let s = match v {
                Value::String(s) => s.clone(),
                Value::Null => "".to_string(),
                other => other.to_string(),
            };
            map.insert(k.clone(), s);
        }
        out.push(map);
    }
    Ok(out)
}

fn strip_bom(b: &[u8]) -> &[u8] {
    if b.starts_with(&[0xEF, 0xBB, 0xBF]) {
        &b[3..]
    } else {
        b
    }
}

// ---------------------------------------------------------------------------
// Numeric helpers
// ---------------------------------------------------------------------------

fn sha256_hex(bytes: &[u8]) -> String {
    let mut h = Sha256::new();
    h.update(bytes);
    hex::encode(h.finalize())
}

fn ratio(num: i64, den: i64) -> f64 {
    if den == 0 {
        0.0
    } else {
        num as f64 / den as f64
    }
}

/// Round to 4 decimals using banker's rounding, to match Python's round(x, 4).
fn round4(x: f64) -> f64 {
    let scaled = x * 10_000.0;
    let rounded = round_half_even(scaled);
    rounded / 10_000.0
}

fn round_half_even(x: f64) -> f64 {
    let floor = x.floor();
    let diff = x - floor;
    if diff > 0.5 {
        floor + 1.0
    } else if diff < 0.5 {
        floor
    } else {
        // Exactly .5 -> round to even.
        if (floor as i64) % 2 == 0 {
            floor
        } else {
            floor + 1.0
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::contract::Spec;

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
    fn counts_and_dedup() {
        let csv = b"email,n\na@x.com,1\na@x.com,1\nb@x.com,2\n";
        let s = spec(&[("email", "string", true), ("n", "integer", true)], &["email"]);
        let out = process_tabular(csv, "f.csv", &s, "j", "sub");
        assert_eq!(out.report.validated_amount, 2); // one dupe removed
        assert_eq!(out.report.duplicate_rows, 1);
        assert_eq!(out.key_hashes.len(), 2);
    }

    #[test]
    fn rejects_unparseable_required() {
        let csv = b"n\n1\nnotnum\n";
        let s = spec(&[("n", "integer", true)], &[]);
        let out = process_tabular(csv, "f.csv", &s, "j", "sub");
        assert_eq!(out.report.validated_amount, 1);
        assert_eq!(out.report.rejected_rows, 1);
    }

    #[test]
    fn dataset_hash_is_sha256_of_bytes() {
        let out = process_tabular(b"a\n1\n", "f.csv", &None, "j", "sub");
        assert_eq!(out.report.dataset_hash, sha256_hex(b"a\n1\n"));
    }
}
