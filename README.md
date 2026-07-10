# ChanterLab

**The product is the choir-practice training app in
[`training-prototype/`](training-prototype/README.md), live at
[chanterlab.com](https://chanterlab.com).** Everything else in this README
describes the standalone Byzantine chant engine that shares this repository —
a maintenance-only app (tuning grids, pthora/chroa controls, ison and synth
tools), not the product roadmap. Its architecture is documented in
[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and deployed separately via
GitHub Pages (see below); its "crown jewels" (the Rust/WASM pitch detector,
PSOLA, Byzantine notation) are migrating into the training app over time
rather than being developed as a second product. See
[`docs/AGILE-RESET-2026-07.md`](docs/AGILE-RESET-2026-07.md) for the current
plan of record.

---

ChanterLab (legacy engine) is browser-based Byzantine chanting practice
software. It provides interactive tuning grids, pthora and chroa controls,
microphone pitch feedback, ison and synth tools, and short pitch-holding
exercises.

The app runs locally in the browser. Microphone audio is processed in the page's
AudioWorklet and is not uploaded to a server.

## License

This repository is licensed under GPL-3.0-only. See [LICENSE](LICENSE).

The bundled Neanes font has its own license in
[web/fonts/neanes/LICENSE.txt](web/fonts/neanes/LICENSE.txt).

## Contact

For questions, inquiries, support, or source code requests:

- Email: [justinpeter0815theotokos@gmail.com](mailto:justinpeter0815theotokos@gmail.com)
- GitHub: [github.com/jayfurz](https://github.com/jayfurz)
- LinkedIn: [linkedin.com/in/justinfursov](https://www.linkedin.com/in/justinfursov)

## Requirements

- Rust with the `wasm32-unknown-unknown` target
- `wasm-pack`

Install the target:

```sh
rustup target add wasm32-unknown-unknown
```

Install `wasm-pack` using the method recommended for your platform:

```sh
cargo install wasm-pack
```

## Build

```sh
make build
```

This generates the browser WASM packages in `web/pkg` and `web/pkg-worklet`.
Those generated files are intentionally ignored in git; the GitHub Pages
workflow rebuilds them during deployment.

The deployed page includes a **Source** link to
[github.com/jayfurz/ChanterLab](https://github.com/jayfurz/ChanterLab).

## Run Locally

After building, serve the `web` directory with any static file server. For
example:

```sh
python3 -m http.server 8000 --directory web
```

Then open `http://localhost:8000`.

## Test

Rust tests. Use `--all-features` to include the worklet FFT-detector tests and
the serde serialization tests (the default feature set skips both):

```sh
cargo test --all-features
```

JavaScript score-engine tests (Node's built-in test runner, no install needed):

```sh
cd web/score && node --test
```

To run everything CI runs — `rustfmt`, `clippy`, and both test suites — in one
command:

```sh
make check
```

Both suites, plus `cargo fmt --check` and `cargo clippy`, run in CI on every
push and pull request.

## GitHub Pages Deployment

This repo includes a GitHub Actions workflow at
[.github/workflows/pages.yml](.github/workflows/pages.yml) that deploys this
legacy Byzantine engine only. After pushing to GitHub, enable Pages for the
repository and choose **GitHub Actions** as the source. Pushes to `master` or
`main` build the WASM artifacts and deploy a staging copy of `web` with
`web/training` (the training-app symlink) excluded, so the Pages site can
never accidentally ship the product. The training app itself is not deployed
via Pages — see [Deployment](docs/plans/00-baseline/01-branch-and-deployment.md)
for how chanterlab.com is actually released.
