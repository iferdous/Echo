# Stage 7 — Demo and delivery

**Outcome.** A reader can understand the match in a short recording and reproduce the same workflow from the command line.

## Build

1. Write a fresh-checkout walkthrough that generates or retrieves permitted example inputs, builds an index, queries it, and displays the output. Use generated audio for the public demo by default. Include a permitted dataset example or textual evidence from the cross-dataset run where useful.
2. Show a crop going in, the correct reference and timestamp coming out, and a similar but separate recording being rejected. Include a representative failure from the recorded evaluation.
3. Show the ML outcome as a generated chart with both training conditions, a fixed test set, and the observed score difference or lack of one. Use the saved output files from one named run.
4. If a later use case benefits from a browser interface, scope a local demo that calls the same matcher and reads the same evidence as the CLI. Adding an upload path would require documented format and size limits, predictable error handling, and a retention choice.

## Check and capture

- Execute the copyable walkthrough in a clean output directory. Verify the displayed offset, acceptance status, and dataset source against the saved scope.
- Confirm that examples, charts and run labels agree with the underlying artifacts and that public media follows dataset terms.
- Capture a short recording, an accessible transcript or captions, and the commands demonstrated.

**Done when** a reviewer can watch the example and reproduce the fixture walkthrough from the repository.

[Stage index](README.md) · [Next stage](08-benchmark-and-evidence-bundle.md)
