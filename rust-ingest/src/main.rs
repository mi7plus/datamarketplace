//! Rowbound ingest/dedup/media service.
//!
//! The discipline that makes this safe: **Rust computes, Python settles.** This
//! service does pure, stateless heavy computation (parse, validate, hash, media
//! crunch). It never touches money/lifecycle tables and never decides what's
//! accepted — it returns a deterministic report and Python does the locked
//! allocation. See PLAN: rowbound-rust-ingest-service-plan.md.

use rowbound_ingest::{
    callback, config, contract, error, metrics, pipeline, queue, staging, storage,
};

use axum::extract::{DefaultBodyLimit, State};
use axum::http::HeaderMap;
use axum::routing::{get, post};
use axum::{Json, Router};
use callback::Callback;
use config::Config;
use contract::{IngestReport, IngestRequest};
use error::AppError;
use pipeline::Pipeline;
use staging::Staging;
use std::sync::Arc;
use storage::S3;

#[derive(Clone)]
struct AppState {
    pipeline: Pipeline,
    staging: Option<Staging>,
    internal_token: String,
}

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .json()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env().unwrap_or_else(|_| "info".into()),
        )
        .init();

    let cfg = Config::from_env();
    metrics::init(&cfg);

    let s3 = S3::new(&cfg).await?;
    let staging = match &cfg.database_url {
        Some(url) => match Staging::connect(url).await {
            Ok(s) => Some(s),
            Err(e) => {
                tracing::warn!(error = %e, "staging DB unavailable; using S3 artifact fallback");
                None
            }
        },
        None => None,
    };

    let pipeline = Pipeline {
        s3: s3.clone(),
        staging: staging.clone(),
    };
    let callback = Callback::new(&cfg);

    // Async worker pool (no-op if no queue configured).
    {
        let cfg = cfg.clone();
        let pipeline = pipeline.clone();
        let callback = callback.clone();
        tokio::spawn(async move {
            queue::run_workers(cfg, pipeline, callback).await;
        });
    }

    let state = Arc::new(AppState {
        pipeline,
        staging,
        internal_token: cfg.internal_token.clone(),
    });

    let app = Router::new()
        .route("/health", get(health))
        .route("/ingest", post(ingest_sync))
        .layer(DefaultBodyLimit::max(2 * 1024 * 1024)) // request body is small JSON
        .with_state(state);

    let listener = tokio::net::TcpListener::bind(&cfg.bind_addr).await?;
    tracing::info!(addr = %cfg.bind_addr, "ingest service listening");
    axum::serve(listener, app).await?;
    Ok(())
}

async fn health(State(state): State<Arc<AppState>>) -> Json<serde_json::Value> {
    let staging_ok = match &state.staging {
        Some(s) => s.ping().await.is_ok(),
        None => true, // not configured == not unhealthy
    };
    Json(serde_json::json!({
        "status": "ok",
        "staging": staging_ok,
        "version": env!("CARGO_PKG_VERSION"),
    }))
}

/// Synchronous ingest (small tabular files / dev). Shares the same pipeline core
/// as the workers, so behavior is identical to the async path.
async fn ingest_sync(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(req): Json<IngestRequest>,
) -> Result<Json<IngestReport>, AppError> {
    // Same shared-secret gate as the callback — the sync path is internal-only.
    if !state.internal_token.is_empty() {
        let provided = headers
            .get("X-Internal-Token")
            .and_then(|v| v.to_str().ok())
            .unwrap_or("");
        if provided != state.internal_token {
            return Err(AppError::Unauthorized);
        }
    }
    if req.s3_key.trim().is_empty() {
        return Err(AppError::BadRequest("s3_key is required".into()));
    }
    let report = state.pipeline.run(&req).await?;
    Ok(Json(report))
}
