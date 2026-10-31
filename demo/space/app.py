"""Entry file of the Hugging Face Space. It only starts the playground in demo/playground.py."""

try:
    import spaces  # only installed on Hugging Face; import it before anything that loads torch
except ImportError:
    spaces = None

if spaces is not None:
    @spaces.GPU(duration=1)
    def _zerogpu_placeholder():
        """ZeroGPU requires one GPU function; MixShield itself runs on CPU."""
        return None

from demo.playground import LAUNCH, demo  # noqa: E402

demo.queue(max_size=20).launch(**LAUNCH)
