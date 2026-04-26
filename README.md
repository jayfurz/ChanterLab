# ChanterLab

ChanterLab is browser-based Byzantine chanting practice software. It provides
interactive tuning grids, pthora and chroa controls, microphone pitch feedback,
ison and synth tools, and short pitch-holding exercises.

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

The deployed page includes a **Source** link. During GitHub Pages deployment,
the workflow replaces the placeholder URL in `web/index.html` with the public
repository URL from `GITHUB_REPOSITORY`.

## Run Locally

After building, serve the `web` directory with any static file server. For
example:

```sh
python3 -m http.server 8000 --directory web
```

Then open `http://localhost:8000`.

## Test

```sh
cargo test
```

## GitHub Pages Deployment

This repo includes a GitHub Actions workflow at
[.github/workflows/pages.yml](.github/workflows/pages.yml). After pushing to
GitHub, enable Pages for the repository and choose **GitHub Actions** as the
source. Pushes to `master` or `main` will build the WASM artifacts and deploy
the `web` directory.
