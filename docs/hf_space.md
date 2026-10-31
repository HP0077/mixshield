# Hugging Face Space notes

Space: https://huggingface.co/spaces/HP0077/mixshield. Files for it are in `demo/space/`; `python demo/space/build.py <new folder>` copies everything the Space needs.

The Space runs on ZeroGPU hardware (CPU basic was not available). MixShield itself runs on CPU. Three things had to be fixed on Hugging Face, and the repo now matches:

1. **`short_description` is limited to 60 characters.** The first text was too long. It is now "Guards AI agents from Hinglish & Hindi prompt injection". `python_version` is `"3.12"`.
2. **ZeroGPU supports only some torch versions:** 2.13.0, 2.12.1, 2.11.0, 2.10.0, 2.9.1 and 2.8.0 (as reported by the Space). `demo/space/requirements.txt` pins `torch==2.13.0` and has no CPU `--extra-index-url` line. The benchmark results were run with torch 2.14.1 (`requirements.txt` in the repo root); only the Space uses 2.13.0.
3. **ZeroGPU needs one function decorated with `@spaces.GPU`.** `demo/space/app.py` defines a placeholder (`_zerogpu_placeholder`, `duration=1`) that does nothing. The import of `spaces` is optional, so local runs and tests work without it.
