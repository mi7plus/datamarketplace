//! Perceptual near-duplicate search (P3 follow-up) — a BK-tree over Hamming
//! distance of the image perceptual hashes (`media::phash`).
//!
//! This is the deliberately-deferred piece from the media plan: perceptual
//! near-dup detection is approximate-nearest-neighbour over hash space, a DIFFERENT
//! data structure than the exact-key SQL anti-join used for tabular/exact-file
//! dedup. It does NOT touch allocation/settlement — exact-file `dataset_hash` stays
//! the dedup key; this index is a *detection* tool (flag likely-duplicate media for
//! review, find a buyer's prior near-identical assets, etc.).
//!
//! A BK-tree exploits the triangle inequality of the Hamming metric: to find all
//! items within `max` of a target, at each node (distance `d` from the target) only
//! children whose edge-distance lies in `[d-max, d+max]` need visiting — so a query
//! prunes most of the tree instead of scanning every hash.
//!
//! Scope: image perceptual hashes (fixed-width bit vectors → Hamming applies).
//! Audio Chromaprint near-dup is correlation-based over variable-length
//! fingerprints, a separate problem — not this index.

use crate::media::perceptual_distance;

/// Hamming distance between two base64 perceptual hashes; an undecodable hash is
/// treated as infinitely far (never a near-dup match).
fn dist(a: &str, b: &str) -> u32 {
    perceptual_distance(a, b).unwrap_or(u32::MAX)
}

#[derive(Debug, Clone, PartialEq)]
pub struct Match {
    pub id: String,
    pub distance: u32,
}

struct Node {
    hash: String,
    id: String,
    children: Vec<(u32, Node)>, // edge keyed by distance from this node
}

impl Node {
    fn insert(&mut self, hash: String, id: String) {
        let d = dist(&self.hash, &hash);
        if let Some(pos) = self.children.iter().position(|(k, _)| *k == d) {
            self.children[pos].1.insert(hash, id);
        } else {
            self.children.push((
                d,
                Node {
                    hash,
                    id,
                    children: Vec::new(),
                },
            ));
        }
    }

    fn query(&self, target: &str, max: u32, out: &mut Vec<Match>) {
        let d = dist(&self.hash, target);
        if d <= max {
            out.push(Match {
                id: self.id.clone(),
                distance: d,
            });
        }
        let lo = d.saturating_sub(max);
        let hi = d.saturating_add(max);
        for (k, child) in &self.children {
            if *k >= lo && *k <= hi {
                child.query(target, max, out);
            }
        }
    }
}

/// A BK-tree index of perceptual hashes. Insert `(perceptual_hash_b64, id)` pairs,
/// then query for everything within a Hamming threshold of a probe hash.
#[derive(Default)]
pub struct NearDupIndex {
    root: Option<Node>,
    len: usize,
}

impl NearDupIndex {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn len(&self) -> usize {
        self.len
    }

    pub fn is_empty(&self) -> bool {
        self.len == 0
    }

    pub fn insert(&mut self, perceptual_hash: &str, id: &str) {
        match &mut self.root {
            Some(root) => root.insert(perceptual_hash.to_string(), id.to_string()),
            None => {
                self.root = Some(Node {
                    hash: perceptual_hash.to_string(),
                    id: id.to_string(),
                    children: Vec::new(),
                });
            }
        }
        self.len += 1;
    }

    /// All indexed items within `max_distance` (Hamming) of `perceptual_hash`,
    /// sorted nearest-first.
    pub fn query(&self, perceptual_hash: &str, max_distance: u32) -> Vec<Match> {
        let mut out = Vec::new();
        if let Some(root) = &self.root {
            root.query(perceptual_hash, max_distance, &mut out);
        }
        out.sort_by_key(|m| m.distance);
        out
    }

    /// True if any indexed item is within `max_distance` of the probe.
    pub fn contains_near(&self, perceptual_hash: &str, max_distance: u32) -> bool {
        !self.query(perceptual_hash, max_distance).is_empty()
    }
}
