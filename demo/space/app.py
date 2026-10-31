"""Entry file of the Hugging Face Space. It only starts the playground in demo/playground.py."""

from demo.playground import LAUNCH, demo

demo.queue(max_size=20).launch(**LAUNCH)
