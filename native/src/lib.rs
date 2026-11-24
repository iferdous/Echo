//! Offset voting over the fingerprints and filtered postings supplied by Echo.

use std::cmp::Reverse;
use std::collections::{HashMap, HashSet};

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyDict, PyList, PyString, PyTuple};

type Landmark = (i64, i64);
type Posting = (usize, i64);
type Votes = HashMap<i128, Vec<usize>>;
type Alignment = (String, i128, i64, i64, usize, usize, usize);

struct References {
    names: Vec<String>,
    postings: HashMap<i64, Vec<Posting>>,
}

fn read_postings(postings: &Bound<'_, PyDict>) -> PyResult<References> {
    let mut names = Vec::new();
    let mut track_by_pointer = HashMap::new();
    let mut track_by_name = HashMap::new();
    let mut grouped = HashMap::with_capacity(postings.len());
    for (key, entries) in postings.iter() {
        let entries = entries.cast::<PyList>()?;
        let mut group = Vec::with_capacity(entries.len());
        for entry in entries.iter() {
            let tuple = entry.cast::<PyTuple>()?;
            if tuple.len() != 2 {
                return Err(PyValueError::new_err(
                    "expected an asset ID and a reference frame",
                ));
            }
            let asset = tuple.get_item(0)?.cast_into::<PyString>()?;
            // The source dictionary keeps these objects alive for the entire conversion.
            let pointer = asset.as_ptr() as usize;
            let track = if let Some(&track) = track_by_pointer.get(&pointer) {
                track
            } else {
                let text = asset.to_str()?;
                let track = if let Some(&track) = track_by_name.get(text) {
                    track
                } else {
                    let track = names.len();
                    names.push(text.to_owned());
                    track_by_name.insert(text.to_owned(), track);
                    track
                };
                track_by_pointer.insert(pointer, track);
                track
            };
            group.push((track, tuple.get_item(1)?.extract()?));
        }
        grouped.insert(key.extract()?, group);
    }
    Ok(References {
        names,
        postings: grouped,
    })
}

fn vote(query: &[Landmark], references: &References) -> Vec<Votes> {
    let mut tracks: Vec<Votes> = (0..references.names.len())
        .map(|_| HashMap::new())
        .collect();
    for (id, &(frame, key)) in query.iter().enumerate() {
        if let Some(postings) = references.postings.get(&key) {
            for &(track, reference_frame) in postings {
                let offset = i128::from(reference_frame) - i128::from(frame);
                let support = tracks[track].entry(offset).or_default();
                // A query point can vote at most once for a track at this exact offset.
                if support.last() != Some(&id) {
                    support.push(id);
                }
            }
        }
    }
    tracks
}

fn best_offset<'a>(
    ordered: &'a [(i128, Vec<usize>)],
    radius: i128,
    counts: &mut [usize],
) -> (i128, &'a [(i128, Vec<usize>)]) {
    let mut left = 0;
    let mut right = 0;
    let mut distinct = 0;
    let mut best = None;
    let mut bounds = (0, 0, 0);
    for (offset, exact) in ordered {
        // Slide over populated offsets. Counts preserve distinct query points across bins.
        while right < ordered.len() && ordered[right].0 <= offset + radius {
            for &point in &ordered[right].1 {
                distinct += usize::from(counts[point] == 0);
                counts[point] += 1;
            }
            right += 1;
        }
        while left < right && ordered[left].0 < offset - radius {
            for &point in &ordered[left].1 {
                counts[point] -= 1;
                distinct -= usize::from(counts[point] == 0);
            }
            left += 1;
        }
        let key = (
            distinct,
            exact.len(),
            Reverse(offset.abs()),
            Reverse(*offset),
        );
        if best.is_none_or(|previous| key > previous) {
            best = Some(key);
            bounds = (*offset, left, right);
        }
    }
    for (_, points) in &ordered[left..right] {
        for &point in points {
            counts[point] = 0;
        }
    }
    (bounds.0, &ordered[bounds.1..bounds.2])
}

fn align_owned(query: &[Landmark], references: References, radius: i128) -> Vec<Alignment> {
    let tracks = vote(query, &references);
    let mut alignments = Vec::new();
    let mut counts = vec![0; query.len()];
    let mut seen_track = vec![usize::MAX; query.len()];
    for (track, (name, votes)) in references.names.into_iter().zip(tracks).enumerate() {
        if votes.is_empty() {
            continue;
        }
        let mut ordered: Vec<_> = votes.into_iter().collect();
        ordered.sort_unstable_by_key(|(offset, _)| *offset);
        let (offset, winners) = best_offset(&ordered, radius, &mut counts);
        let mut frames = HashSet::new();
        let mut hashes = HashSet::new();
        let mut score = 0;
        let mut first = i64::MAX;
        let mut last = i64::MIN;
        for (_, points) in winners {
            for &id in points {
                if seen_track[id] == track {
                    continue;
                }
                seen_track[id] = track;
                let (frame, key) = query[id];
                first = first.min(frame);
                last = last.max(frame);
                frames.insert(frame);
                hashes.insert(key);
                score += 1;
            }
        }
        alignments.push((name, offset, first, last, score, frames.len(), hashes.len()));
    }
    alignments
}

#[pyfunction]
fn align(
    py: Python<'_>,
    query: Vec<Landmark>,
    postings: &Bound<'_, PyDict>,
    radius: u64,
) -> PyResult<Vec<Alignment>> {
    let references = read_postings(postings)?;
    Ok(py.detach(|| align_owned(&query, references, i128::from(radius))))
}

#[pymodule]
fn _echo_offsets(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("API_VERSION", 1)?;
    module.add_function(wrap_pyfunction!(align, module)?)?;
    Ok(())
}
