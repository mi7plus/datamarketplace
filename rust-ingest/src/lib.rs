//! Library surface for the Rowbound ingest service, so integration tests and the
//! binary share the same modules. The discipline: Rust computes, Python settles —
//! nothing here writes money/lifecycle state.

pub mod callback;
pub mod config;
pub mod contract;
pub mod error;
pub mod keys;
pub mod media;
pub mod metrics;
pub mod pipeline;
pub mod queue;
pub mod staging;
pub mod storage;
pub mod tabular;
