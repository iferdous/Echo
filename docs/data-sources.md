# Dataset sources and release attribution

The preview contains generated audio in the demo, plus metadata, manifests, summary figures and measured results. Retrieve the original recordings from the published sources for local replay. The release does not include dataset WAVs, derived listening samples, the fingerprint index, or trained weights.

| Dataset | Release and scope | Attribution and terms |
| --- | --- | --- |
| ESC-50 | Pinned commit `33c8ce9eb2cf0b1c2f8bcf322eb349b6be34dbb6`. The upstream download is about 600 MB. | Karol J. Piczak, *ESC: Dataset for Environmental Sound Classification* (ACM MM 2015). ESC-50 is published under CC BY-NC 3.0, with an exception for the ESC-10 subset under CC BY 3.0. See the pinned per-file attributions and license statements. [Pinned project and citation](https://github.com/karolpiczak/ESC-50/tree/33c8ce9eb2cf0b1c2f8bcf322eb349b6be34dbb6) · [Pinned license and attribution](https://github.com/karolpiczak/ESC-50/blob/33c8ce9eb2cf0b1c2f8bcf322eb349b6be34dbb6/LICENSE) |
| FSD50K | Version 1.0, DOI `10.5281/zenodo.4060432`. Echo acquired a selected official eval cohort using archive ranges. The acquisition report records actual transferred and decoded bytes. | Eduardo Fonseca, Xavier Favory, Jordi Pons, Frederic Font, and Xavier Serra, *FSD50K: An Open Dataset of Human-Labeled Sound Events* (IEEE/ACM TASLP 2022). Terms vary by recording. Consult the official metadata for uploader and per-clip license. [Official release](https://zenodo.org/records/4060432) · [Companion site](https://fsannotator.upf.edu/fsd/release/FSD50K/) · [Echo acquisition ledger](results/stage-4-acquisition.csv) |

The case study links to original Freesound pages. The dog example uses source 207124. The case figure depicts timing and disposition counts. It contains no source audio or waveform samples. [Recording and source license](https://freesound.org/s/207124/) · [Example and checksum record](results/stage-4-example.json)
