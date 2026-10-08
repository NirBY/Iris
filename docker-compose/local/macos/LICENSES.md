# Licenses and attribution

The custom API companion scripts in this bundle are supplied under the [MIT license](LICENSE). They are independent integration code, not a modified Mila application. The bundle does not contain Mila, whisper.cpp, FFmpeg, Python wheels or model weights. Installation downloads those components from their own distributors; keep the licenses and notices supplied with those downloads.

| Component | License and original notices |
| --- | --- |
| Mila desktop app | [Apache-2.0](https://github.com/island-io/mila/blob/main/LICENSE), [NOTICE](https://github.com/island-io/mila/blob/main/NOTICE), [third-party notices](https://github.com/island-io/mila/blob/main/THIRD_PARTY_NOTICES.md) |
| whisper.cpp | [MIT](https://github.com/ggml-org/whisper.cpp/blob/master/LICENSE); keep its source checkout and license |
| ivrit.ai Hebrew model | [Apache-2.0 model card](https://huggingface.co/ivrit-ai/whisper-large-v3-ggml) |
| OpenAI Whisper models | [MIT](https://github.com/openai/whisper/blob/main/LICENSE) |
| FFmpeg | [LGPL/GPL depending on build configuration](https://ffmpeg.org/legal.html); installed separately by Homebrew and invoked as an executable |
| Python dependencies | Installed separately into the virtual environment; preserve each distribution's license files and metadata |

Calling a separate HTTP service or executable does not relicense that component as Iris MIT. This setup neither copies Mila source into Iris nor redistributes modified model weights. If distributing application binaries, wheels, engines or weights in a future bundle, review that exact artifact and include its required licenses, notices and any applicable source obligations first.

Upstream attribution may include the upstream authors' names and contact details. These are license notices, not installation-specific personal data; do not redact required attribution.
