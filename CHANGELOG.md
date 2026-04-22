# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
## [Unreleased]

### Added

- Rename async→polling and push→callback patterns ([d6fbd2e](https://github.com/edu2105/imnot/commit/d6fbd2e023e1de428616e05d45286ee66e1c5ee6))
- Register trailing-slash alias for all consumer routes ([5d9477e](https://github.com/edu2105/imnot/commit/5d9477ef70a0e125070beaca226404385191d2dc))

## [0.5.2] - 2026-04-21

### Fixed

- Write imnot.toml and logs to db_path.parent, not CWD ([6552d05](https://github.com/edu2105/imnot/commit/6552d05c4f4d906eb721a64a891a1418327649ca))

## [0.5.1] - 2026-04-21

### Fixed

- Resolve log dir relative to db_path.parent, not CWD ([b04f3c2](https://github.com/edu2105/imnot/commit/b04f3c23d86c1f587ace729acda2db0940a71608))

## [0.5.0] - 2026-04-21

### Added

- Add paginated pattern with offset/limit slicing and configurable default ([161d37b](https://github.com/edu2105/imnot/commit/161d37bec09fc0995abaa376bd53b68ba8a6cb65))
- Wire configure_logging into all CLI subcommands ([85fca7d](https://github.com/edu2105/imnot/commit/85fca7d2e67e0d6fba0b57d6f160a6c76f6f65c0))
- Structured logging, imnot.toml config, zero-partners start ([8e344a3](https://github.com/edu2105/imnot/commit/8e344a3f586cd51d136debec0ecf67596f45b75a))

### Fixed

- Strip trailing slashes from endpoint paths at load time ([6878537](https://github.com/edu2105/imnot/commit/687853787bfa305afb9008ffbf40d367b3e864b8))
- Ruff formatting and add missing patch coverage for paginated + server ([af340b5](https://github.com/edu2105/imnot/commit/af340b5074748ad08e1acabf853cf11c74456737))

### Maintenance

- Fix ruff lint errors in new files ([488c3a1](https://github.com/edu2105/imnot/commit/488c3a126485ebf042f60a1cdc7dc87c48b2a84b))
- Add CODECOV_TOKEN to coverage upload step ([62ad514](https://github.com/edu2105/imnot/commit/62ad514677590df6912198d2a5336153a129d668))
- Add ruff linting and pytest-cov coverage reporting ([7fd9a91](https://github.com/edu2105/imnot/commit/7fd9a91e4b5cad3720e00f2338107bac3a000eec))
- Improve git-cliff config for clean, readable release notes ([09d20eb](https://github.com/edu2105/imnot/commit/09d20ebb56ad06729581936eae878c3456af7ab8))

## [0.4.5] - 2026-04-19

### Added

- Add E2E QA suite and fix reload partners list bug ([1e7be33](https://github.com/edu2105/imnot/commit/1e7be33b488b2c8ee1e3a70ff888671a520e8e8e))
- Add imnot stop command ([fbcf0eb](https://github.com/edu2105/imnot/commit/fbcf0eb182e798c4c1d063c995c5de68b9f7e152))

### Fixed

- Export CALLBACK_PORT and CALLBACK_FILE to callback server subprocess ([331a5b5](https://github.com/edu2105/imnot/commit/331a5b5a88b7e366f8b59ec61f687a316b815b8b))

### Security

- Harden partner name validation, admin auth, CI supply chain, and Docker ([66d721b](https://github.com/edu2105/imnot/commit/66d721b2da165ac526738e67a168c04e6776f521))

## [0.4.4] - 2026-04-18

### Added

- Auto-discover imnot.db by walking up from CWD ([e2467e6](https://github.com/edu2105/imnot/commit/e2467e6b1ef5dc53ee3f9173fe7350e1e46764c3))
- Add imnot --version flag ([22e656a](https://github.com/edu2105/imnot/commit/22e656a160bcba3f3b058cba9bb0609a1f5ac2bd))

## [0.4.3] - 2026-04-16

### Added

- Add imnot init command for project scaffolding ([f677ebc](https://github.com/edu2105/imnot/commit/f677ebcafee2bd34d796df1882e7cd1eb5260064))

### Fixed

- Add environment: production to publish-pypi job for OIDC trusted publishing ([550ec86](https://github.com/edu2105/imnot/commit/550ec86e279bf8d9292b911197c4799e648ab235))

## [0.4.2] - 2026-04-16

### Documentation

- Recommend pipx in Quick Start, clarify partner concept, fix start help text ([5b2cb17](https://github.com/edu2105/imnot/commit/5b2cb17e5e4703b87154d043e437b382c1354332))
- Update Quick Start to use pip install from PyPI ([e5956fa](https://github.com/edu2105/imnot/commit/e5956fab8708781cd9358f61ee08d3b36368ed97))
- Add AI-assisted contributions policy to CONTRIBUTING.md ([cd03c37](https://github.com/edu2105/imnot/commit/cd03c37e21b2f4d3bb6e460952f65a86d47212e4))

### Fixed

- Add Python 3.13 to the CI test matrix ([1ec8ad0](https://github.com/edu2105/imnot/commit/1ec8ad00a71ac74ab23444be7796783aa3d87fa5))

## [0.4.1] - 2026-04-15

### Added

- Add nametag SVG logo and update README header ([c94e495](https://github.com/edu2105/imnot/commit/c94e4954381095b1c4d7d4b92b6eee586b9c7d27))

### Documentation

- Update test count in CONTRIBUTING.md to 228 ([12b1ebd](https://github.com/edu2105/imnot/commit/12b1ebd0fa2daf2511d81432208d3288c51c02c6))
- Replace partner API jargon with external API + tighten AI prompts ([799bf2c](https://github.com/edu2105/imnot/commit/799bf2c3bf30861448be12a95e72dd815bd1377b))
- Restructure README above the fold + add AI-ready section ([5f0f44c](https://github.com/edu2105/imnot/commit/5f0f44c60fac4fc102c666e6d9fae50d7bcdfcab))
- Rewrite Why imnot? section for clarity and broader positioning ([75002f7](https://github.com/edu2105/imnot/commit/75002f72920979734d83d0bf273ae9a21cdc64b7))

### Fixed

- Restore "Hello, my name is" header text in nametag logo ([64f0d57](https://github.com/edu2105/imnot/commit/64f0d572643ebae244a52c7de3d6cda17aad40ba))

### Maintenance

- Add authors and project URLs to pyproject.toml ([fcacedf](https://github.com/edu2105/imnot/commit/fcacedfec8b8fe5e306d0b8e2973dcad33aeff60))

## [0.4.0] - 2026-04-14

### Added

- Add GET /healthz for container health probes (#6) ([e0ab4d8](https://github.com/edu2105/imnot/commit/e0ab4d8bbb0fc4b3d4ecff5dc071994e3edd91a3))

## [0.3.0] - 2026-04-14

### Added

- Rename project from mirage to imnot ([29c72c2](https://github.com/edu2105/imnot/commit/29c72c20d4a1e6df2ea4f5c7626e34960b44b518))

### Fixed

- Finish rename — update remaining Mirage product name references ([d4d0ed1](https://github.com/edu2105/imnot/commit/d4d0ed1da4da1b30f71be973cbacdeb89d99840b))

## [0.2.0] - 2026-04-14

### Added

- Add POST /mirage/admin/partners for HTTP partner registration ([908ac14](https://github.com/edu2105/imnot/commit/908ac1437d5057ef16bb10018f21fdc915ec4f45))

## [0.1.1] - 2026-04-13

### Added

- Add /mirage/docs endpoints serving README files as plain text ([c7cc6c8](https://github.com/edu2105/imnot/commit/c7cc6c8918265f7b5242a34e6fd6e8d17cec822c))

## [0.1.0] - 2026-04-13

### Added

- Add --partner filter to mirage export postman ([4d95707](https://github.com/edu2105/imnot/commit/4d957075ebf8e1cdc265cdda76933a85a18c8fac))
- Add Postman collection export ([1e09785](https://github.com/edu2105/imnot/commit/1e09785e89fae49bc1057f5c399bf4f751c3f5c5))
- Implement push pattern (webhooks) ([064a5c5](https://github.com/edu2105/imnot/commit/064a5c51ae4d1c3bf395b1edc3aa0660e5707112))
- Add mirage generate command ([02f4fe9](https://github.com/edu2105/imnot/commit/02f4fe9595205f8dadba10e3efe484bcc81f4734))
- Migrate staylink partner from poll to async pattern ([7e0cd70](https://github.com/edu2105/imnot/commit/7e0cd70c3cbb57918737d70a3e62e9125ae203d3))
- Add async pattern dispatch to router ([9fd50a8](https://github.com/edu2105/imnot/commit/9fd50a8abaa0b12a58d6c435aa5034d28f8a31b9))
- Add async to supported YAML patterns, remove poll ([1a188d2](https://github.com/edu2105/imnot/commit/1a188d28ffd262f0c0f8aa5d0fbf0099fa496990))
- Complete async pattern with static and fetch handlers ([808d506](https://github.com/edu2105/imnot/commit/808d506e15d3cc372b9fea5fec7071d21d888f32))
- Add async pattern submit handler (header and body ID delivery) ([9375172](https://github.com/edu2105/imnot/commit/9375172640a079d0aa41736e31835c8849d54f83))
- Add Docker support ([353b0f9](https://github.com/edu2105/imnot/commit/353b0f97eb74a45b8a89ebf1ba6113b92d05fd7c))
- Add SVG logo with reflection shimmer effect ([f5f1846](https://github.com/edu2105/imnot/commit/f5f1846854fd3c21cd9111a92a9d9b700329639c))
- Static/fetch patterns, LeanPMS partner, expanded CLI, and CI ([ccedb56](https://github.com/edu2105/imnot/commit/ccedb5653ae41c2e7a509025ad5fd0510eda2cc6))
- Admin GET endpoints to inspect stored payloads ([4c018c4](https://github.com/edu2105/imnot/commit/4c018c40ca8d5348b9a2aae63959aea01b0cb58d))
- App factory, CLI, and smoke test — POC complete ([dffa5d9](https://github.com/edu2105/imnot/commit/dffa5d99aa2995ee9302363875aafd6f27c0861b))
- Router, pattern handlers, and session store ([4837b26](https://github.com/edu2105/imnot/commit/4837b26b75ba6766e433fe3cee9d5af1a61efd13))
- Project scaffold, loader, session store, and pattern handlers ([f55f36a](https://github.com/edu2105/imnot/commit/f55f36acea314f63cca67e5ef3fba625b5961fef))

### Changed

- Rename poll_requests table and methods to async_requests ([054c7d5](https://github.com/edu2105/imnot/commit/054c7d57a8f3978d62a62eb20b4c39e07827ae8a))

### Documentation

- Replace provider-specific cloud section with agnostic deployment notes ([303460e](https://github.com/edu2105/imnot/commit/303460e9853c6057cf5d5d8e1feda52484433ac1))
- Document --partner filter for mirage export postman ([c1f63cd](https://github.com/edu2105/imnot/commit/c1f63cdcb77744298221f5331a64553e7fc2ea68))
- Add going-public design doc and workstream plan ([4932dd9](https://github.com/edu2105/imnot/commit/4932dd9b641e722bf579323abe14b2ed1b1eab80))
- Add end-to-end example to mirage generate design doc ([de47b8d](https://github.com/edu2105/imnot/commit/de47b8d255b802ec10e91413ba417c17062c03c3))
- Add design doc for mirage generate command ([210d1b8](https://github.com/edu2105/imnot/commit/210d1b808f4e259b5b632624562c020ac4d98504))
- Make local install the primary quick start, demote Docker ([8b80cb9](https://github.com/edu2105/imnot/commit/8b80cb9f64b83e740b829cd5ae1052dd44a55666))
- Fix Docker quick start to show mirage routes via exec ([38efb88](https://github.com/edu2105/imnot/commit/38efb88f7515e522a6e50467248e8c3fe71df43c))
- Update README and partners guide to replace poll with async pattern ([84ee268](https://github.com/edu2105/imnot/commit/84ee268b75a9902facd2bc19f3f6442ae2c53cef))
- Fix stale poll comment in staylink partner.yaml ([36da756](https://github.com/edu2105/imnot/commit/36da756f95889dd1d74bfb86b8423a3b76b27de5))
- Add async pattern implementation plan ([c6d4182](https://github.com/edu2105/imnot/commit/c6d41821d350c9aef810b54599e207f553db7a06))
- Add design spec for async pattern (replaces poll) ([0b199cd](https://github.com/edu2105/imnot/commit/0b199cd53b5b61de7e663118914e02e4077177ad))
- Expand README with Why Mirage, sequence diagram, Quick Start, Deploy, Limitations, Contributing ([1368803](https://github.com/edu2105/imnot/commit/136880318d56754550da03e4fe30ec092ad5c545))
- Document admin endpoint auth and Docker network exposure ([73c94b9](https://github.com/edu2105/imnot/commit/73c94b9dcf0f3ba855da597419cfba635b206db5))
- Use PNG logo, clean up stale references in README ([0a3a950](https://github.com/edu2105/imnot/commit/0a3a950cc6d22e39e6f8553440e88aee724886ce))
- Add partner YAML authoring guide ([90d09db](https://github.com/edu2105/imnot/commit/90d09dbe70706b106b6e51636f314601a734f436))

### Fixed

- Detect and reject cross-partner route collisions at startup ([5de4d47](https://github.com/edu2105/imnot/commit/5de4d47eeb5766e5bc0c3ce7bb56c00f584c7645))
- Partners dir discovery, remove admin routes for oauth/static, add hot reload ([8cf8c91](https://github.com/edu2105/imnot/commit/8cf8c914b3762f84ab16e4941e52e5a625c42b32))
- Include partner in static handler __name__ to prevent OpenAPI operationId collisions ([469b665](https://github.com/edu2105/imnot/commit/469b665c01902540eb1e942fd0da9a3e7d19d17d))
- Async stubs return callables and validate id delivery config ([849d59a](https://github.com/edu2105/imnot/commit/849d59ad13fbf09c9441fbe2290847bbaebfcd05))
- Update poll.py callers and harden migration guard after store rename ([b7b4ce4](https://github.com/edu2105/imnot/commit/b7b4ce4f51bf63be7d08b49c7a46d62e3227f763))
- Copy README.md before pip install and use non-editable install ([98beead](https://github.com/edu2105/imnot/commit/98beead61ee9b6985dbf7151a289c51190e9db1d))
- Return 400 on malformed JSON in admin payload endpoints ([259bdc0](https://github.com/edu2105/imnot/commit/259bdc07bc403df200bac7f0a67f2db24bb68b15))
- Smoke test counter arithmetic and global payload fallback assertion ([01f29ac](https://github.com/edu2105/imnot/commit/01f29ac6890788ebe809d7adc2f1e2e4517e4588))

### Maintenance

- Update README and gitignore for release tooling ([9ed9129](https://github.com/edu2105/imnot/commit/9ed912980614a8afc2202ff7f4161f439d9fb479))
- Add CHANGELOG, cliff config, and ghcr.io publish workflow ([6ff49c5](https://github.com/edu2105/imnot/commit/6ff49c5122c7f1c83bad345c95673c534d3d1928))
- Remove provider-specific references from SECURITY.md scope ([ef8d034](https://github.com/edu2105/imnot/commit/ef8d034dc9142934939bfc190524535519f97a3f))
- Fix copyright year and broaden SECURITY.md deployment scope ([e496ae1](https://github.com/edu2105/imnot/commit/e496ae1841b74913ede94c5aa56c047e476de1e4))
- Add CODE_OF_CONDUCT, PR template, and issue templates ([cd77e07](https://github.com/edu2105/imnot/commit/cd77e0792c23be1a567a2af9e859505aaeb9f252))
- Add LICENSE, SECURITY.md, and CONTRIBUTING.md ([2d512c8](https://github.com/edu2105/imnot/commit/2d512c8f5d7114bbae845471e6acb341a9b7dd69))
- Suppress bandit false positives and add bandit to CI ([7d88cdf](https://github.com/edu2105/imnot/commit/7d88cdf664f63bbebd69a927f97eaa4453b21cf1))
- Remove apaleo partner (was testing only) ([7b19f4d](https://github.com/edu2105/imnot/commit/7b19f4d66a46c1ef8040afefff5d4327e415b374))
- Add apaleo example partner (oauth + fetch + static) ([04b9169](https://github.com/edu2105/imnot/commit/04b916939b92d74b2f21555b20cf7140b74d56f5))
- Remove real partner names from README ([6e374a5](https://github.com/edu2105/imnot/commit/6e374a5b4cfafd891cb559e57d83281bf5919de3))
- Remove superpowers plugin output and ignore it ([84b79fd](https://github.com/edu2105/imnot/commit/84b79fdcb5af67a6f74a0655bf219f736bac92cc))
- Remove poll pattern (replaced by async) ([331c610](https://github.com/edu2105/imnot/commit/331c6104df6ec6fe05e0252798d7402b8f6dce11))
- Replace ohip with fictional staylink example partner ([7adba19](https://github.com/edu2105/imnot/commit/7adba19ce3e716b8f037caa0c87aa48c07c44efc))
- Replace leanpms with fictional bookingco example partner ([d190fa6](https://github.com/edu2105/imnot/commit/d190fa6c14e1ab01345dcc36e320e8bcf641d278))
- Tighten .gitignore ([3a19fff](https://github.com/edu2105/imnot/commit/3a19fff45a1151e9e0504f05829f1f856247677c))
- Exclude CLAUDE.md and PLAN.md from version control ([cdd65c0](https://github.com/edu2105/imnot/commit/cdd65c06a22b9425ea717f6a4f66282e5b1d0844))

### Security

- Restrict admin endpoint exposure and add optional auth ([ade5942](https://github.com/edu2105/imnot/commit/ade59426b2d246033449a84c2a87c9597143af81))

