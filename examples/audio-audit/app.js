"use strict";

const lab = globalThis.ECHO_LAB;
const perf = globalThis.ECHO_LAB_PERF;
const query = document.getElementById("query");
const support = document.getElementById("support");
const margin = document.getElementById("margin");
const refAudio = document.getElementById("ref-audio");
const queryAudio = document.getElementById("query-audio");
const byId = id => document.getElementById(id);
const set = (id, value) => { byId(id).textContent = value; };
const formatCount = number => number.toLocaleString("en-US");
const seconds = value => `${value >= 0 ? "+" : "−"}${Math.abs(value).toFixed(3)} s`;
const frameTime = lab.config.hop_size / lab.config.sample_rate;
const binFrequency = lab.config.sample_rate / lab.config.fft_size;
const nyquist = lab.config.sample_rate / 2;
const peakTime = frame => frame * frameTime + lab.config.fft_size / (2 * lab.config.sample_rate);
const resultNames = {
  matched: "Match accepted",
  no_match: "No match accepted",
  insufficient_evidence: "Insufficient evidence",
};

function currentCase() {
  return lab.cases.find(item => item.id === query.value);
}

function replayDecision(item, minimumSupport, minimumLead) {
  const { match } = item;
  const policy = lab.policy;
  if (match.query_landmarks < policy.min_support) return "insufficient_evidence";
  const [top, runner] = match.candidates;
  if (!top) return "no_match";
  const passed = top.score >= policy.min_support &&
    top.anchor_frames >= policy.min_anchor_frames &&
    top.distinct_hashes >= policy.min_distinct_hashes &&
    top.coverage >= policy.min_coverage &&
    top.support_fraction >= minimumSupport &&
    top.score - (runner?.score ?? 0) >= minimumLead;
  return passed ? "matched" : "no_match";
}

function resetPolicy() {
  support.value = lab.policy.min_support_fraction * 100;
  margin.value = lab.policy.min_score_margin;
}

function updateDecision() {
  const item = currentCase();
  const [top, runner] = item.match.candidates;
  const current = replayDecision(item, Number(support.value) / 100, Number(margin.value));
  byId("summary").dataset.result = current;
  set("status", resultNames[current]);
  set("policy-verdict", resultNames[current]);
  set("decision", top
    ? `${(100 * top.support_fraction).toFixed(2)}% fingerprint support · ${formatCount(top.score - (runner?.score ?? 0))} vote lead`
    : `${formatCount(item.match.query_landmarks)} extracted fingerprints`);
  set("offset", top ? seconds(top.offset_seconds) : "—");
  set("score", top ? formatCount(top.score) : "—");
  set("byte", item.byte_equal_reference ? "Identical" : "Different");
  set("support-value", `${Number(support.value).toFixed(1)}%`);
  set("margin-value", `${formatCount(Number(margin.value))} votes`);
  byId("jump").disabled = current !== "matched" || top.offset_seconds < 0;
  byId("jump").textContent = current === "matched" && top.offset_seconds >= 0
    ? `Play catalog at ${seconds(top.offset_seconds)}`
    : "Playback offset unavailable for this decision";
}

function source(element, id) {
  const asset = lab.audio[id];
  const anchor = document.createElement("a");
  anchor.href = asset.source_url;
  anchor.textContent = `Freesound ${asset.source_id}`;
  element.replaceChildren(
    document.createTextNode(`${asset.dataset} · ${asset.change} · `), anchor
  );
}

function plotFrame(id, name) {
  const canvas = byId(id);
  const dpr = window.devicePixelRatio || 1;
  const width = canvas.clientWidth;
  const height = canvas.clientHeight;
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  canvas.setAttribute("aria-label", name);
  const graphics = canvas.getContext("2d");
  graphics.scale(dpr, dpr);
  graphics.font = "11px system-ui";
  graphics.fillStyle = "#4f625a";
  const box = { left: 39, right: width - 13, top: 14, bottom: height - 24 };
  return { graphics, box };
}

function plotPeaks(id, data, markedFrame, anchorBin) {
  const duration = data.samples / lab.config.sample_rate;
  const { graphics: g, box: b } = plotFrame(
    id,
    `Spectral peaks from 0 to ${duration.toFixed(2)} seconds and 0 to ${nyquist / 1000} kilohertz. Highlight is one shared anchor when available.`
  );
  const plotX = x => b.left + x / duration * (b.right - b.left);
  const plotY = frequency => b.bottom - frequency / nyquist * (b.bottom - b.top);
  for (const frequency of [0, nyquist / 2, nyquist]) {
    const y = plotY(frequency);
    g.strokeStyle = "#d8ded4";
    g.beginPath();
    g.moveTo(b.left, y);
    g.lineTo(b.right, y);
    g.stroke();
    g.fillStyle = "#4f625a";
    g.fillText(frequency ? `${frequency / 1000} kHz` : "0", 0, y + 3);
  }
  g.fillText("0 s", b.left, b.bottom + 16);
  const end = `${duration.toFixed(1)} s`;
  g.fillText(end, b.right - g.measureText(end).width, b.bottom + 16);
  g.fillStyle = "#4b7d70a0";
  for (const [frame, bin] of data.displayed) {
    g.fillRect(plotX(peakTime(frame)), plotY(bin * binFrequency), 1.55, 1.55);
  }
  if (markedFrame != null) {
    const x = plotX(peakTime(markedFrame));
    g.strokeStyle = "#a7472b";
    g.setLineDash([3, 3]);
    g.beginPath(); g.moveTo(x, b.top); g.lineTo(x, b.bottom); g.stroke();
    g.setLineDash([]);
    g.fillStyle = "#a7472b";
    g.beginPath(); g.arc(x, plotY(anchorBin * binFrequency), 4, 0, Math.PI * 2); g.fill();
  }
}

function plotVotes(trace, top) {
  const { graphics: g, box: b } = plotFrame(
    "histogram",
    `Histogram of exact offsets for the top candidate. The chosen bin is ${top.offset_frames} frames with ${trace.exact_winning_bin} exact votes.`
  );
  const pairs = trace.exact_offset_bins;
  const first = Math.min(pairs[0][0], top.offset_frames - lab.policy.offset_radius_frames) - 1;
  const last = Math.max(pairs.at(-1)[0], top.offset_frames + lab.policy.offset_radius_frames) + 1;
  const max = Math.max(...pairs.map(([, count]) => count));
  const x = frame => b.left + (frame - first) / (last - first) * (b.right - b.left);
  const y = count => b.bottom - count / max * (b.bottom - b.top);
  for (const count of [0, Math.round(max / 2), max]) {
    g.strokeStyle = "#d8ded4";
    g.beginPath(); g.moveTo(b.left, y(count)); g.lineTo(b.right, y(count)); g.stroke();
    g.fillStyle = "#4f625a";
    g.fillText(formatCount(count), 0, y(count) + 3);
  }
  const right = seconds(last * frameTime);
  g.fillText(seconds(first * frameTime), b.left, b.bottom + 16);
  g.fillText(right, b.right - g.measureText(right).width, b.bottom + 16);
  for (const [frame, count] of pairs) {
    g.fillStyle = frame === top.offset_frames ? "#a7472b" : "#397263";
    g.fillRect(x(frame), y(count), frame === top.offset_frames ? 3 : 1, b.bottom - y(count));
  }
}

function renderCharts() {
  const item = currentCase();
  const top = item.match.candidates[0];
  const vote = item.trace?.example_votes[0];
  plotPeaks("query-peaks", item.peaks, vote?.query_frame, vote?.anchor_bin);
  if (top) {
    plotPeaks("ref-peaks", lab.references[top.asset_id], vote?.reference_frame, vote?.anchor_bin);
    plotVotes(item.trace, top);
  }
}

function showCase() {
  const item = currentCase();
  const top = item.match.candidates[0];
  set("query-name", item.label);
  source(byId("query-source"), item.id);
  queryAudio.src = lab.audio[item.id].path;
  if (top) {
    set("ref-name", lab.audio[top.asset_id].title);
    source(byId("ref-source"), top.asset_id);
    refAudio.src = lab.audio[top.asset_id].path;
    set("vote-caption", `The highlighted bin has ${formatCount(item.trace.exact_winning_bin)} exact votes. Echo combines that bin with its nearest neighbors and counts each query fingerprint once, giving ${formatCount(top.score)} aligned votes.`);
  }
  const vote = item.trace?.example_votes[0];
  if (vote) {
    const shift = vote.reference_frame - vote.query_frame;
    set("vote-detail", `Both files contain hash ${formatCount(vote.key)}. Its anchor peaks are circled at ${(vote.anchor_bin * binFrequency).toFixed(1)} Hz. Each frame advances ${frameTime * 1000} ms.`);
    set("packed", `(${vote.anchor_bin} << 20) | (${vote.target_bin} << 10) | ${vote.delay_bin} = ${vote.key}`);
    const calculation = document.createElement("span");
    calculation.textContent = `\n(${vote.reference_frame} − ${vote.query_frame}) × ${frameTime * 1000} ms = ${seconds(shift * frameTime)}`;
    byId("packed").append(document.createElement("br"), calculation);
  }
  const truth = {
    "esc-dog": "The larger audit confirmed the same dog bark by waveform at +0.613125 s.",
    "esc-rain": "Both dataset releases use rain from Freesound 21189. The larger audit’s waveform review confirmed their overlap.",
    "dog-trim": "This is a 2-second crop of the ESC-50 dog query starting at 1.6 s. Echo should find it later in the reference.",
    "dog-mp3": "This is the same crop compressed to 64 kbps. Its file hash changes and the correct timestamp is still ranked first.",
    "dog-noisy": "The source is the dog clip, but heavy noise spread the votes. The highest-ranked candidate is rain, and Echo’s default rule rejects it.",
    "other-dog": "This dog was recorded separately and its source is absent from the index. A similar label alone is weak evidence.",
  };
  set("known", truth[item.id]);
  updateDecision();
  renderCharts();
}

for (const item of lab.cases) {
  const option = document.createElement("option");
  option.value = item.id;
  option.textContent = item.label;
  query.append(option);
  if (replayDecision(item, lab.policy.min_support_fraction, lab.policy.min_score_margin) !== item.match.status) {
    throw new Error(`Saved and browser decisions differ for ${item.id}`);
  }
  const row = document.createElement("tr");
  for (const content of [
    item.label,
    item.expected ? "Indexed source" : "Absent from index",
    item.byte_equal_reference ? "Identical" : "Different",
    resultNames[item.match.status],
  ]) {
    const cell = document.createElement("td");
    cell.textContent = content;
    row.append(cell);
  }
  byId("results").append(row);
}

set("summary-copy", `Echo accepted ${lab.counts.accepted_known_overlaps} of ${lab.counts.known_overlaps} known-overlap examples. Exact file hashes caught ${lab.counts.byte_hash_hits}. Several examples use the same dog recording.`);
set("timing-description", `${perf.processor} · ${lab.counts.references} references · ${lab.counts.queries} clips · ${perf.repeats} measured passes per engine`);
for (const [name, data] of Object.entries(perf.engines)) {
  const card = document.createElement("div");
  const label = document.createElement("span");
  const median = document.createElement("strong");
  const tail = document.createElement("p");
  label.textContent = name === "rust" ? "Rust offset voting" : "Python offset voting";
  median.textContent = `${data.query.p50_ms.toFixed(1)} ms median`;
  tail.textContent = `${data.query.p95_ms.toFixed(1)} ms p95 · ${data.observations} timed queries`;
  card.append(label, median, tail);
  byId("speed").append(card);
}

query.addEventListener("change", showCase);
support.addEventListener("input", updateDecision);
margin.addEventListener("input", updateDecision);
byId("reset").addEventListener("click", () => { resetPolicy(); updateDecision(); });
byId("jump").addEventListener("click", async () => {
  queryAudio.pause();
  const target = currentCase().match.candidates[0].offset_seconds;
  try {
    refAudio.currentTime = target;
    await refAudio.play();
  } catch {
    set("known", "Your browser could not start playback. Use the catalog player to try again.");
  }
});
queryAudio.addEventListener("play", () => refAudio.pause());
refAudio.addEventListener("play", () => queryAudio.pause());
window.addEventListener("resize", renderCharts);

resetPolicy();
showCase();
